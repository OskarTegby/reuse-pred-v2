#include <cassert>
#include <cctype>
#include <cstdint>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "cache.h"

namespace
{

enum class DoAIns { Pos2N3, LRUpos, Bypass };

bool bypass_allowed()
{
    const char* e = std::getenv("LRU_LIVE_ALLOW_BYPASS");
    return !(e && e[0] == '0');
}

DoAIns parse_ins_mode()
{
    const char* v = std::getenv("LRU_LIVE_DOA_INS");
    const std::string mode = (v && v[0]) ? v : "lru";
    if (mode == "2n3")    return DoAIns::Pos2N3;
    if (mode == "bypass") return bypass_allowed() ? DoAIns::Bypass : DoAIns::LRUpos;
    return DoAIns::LRUpos;
}

DoAIns g_ins = DoAIns::LRUpos;

bool hit_init_enabled()
{
    const char* e = std::getenv("LRU_LIVE_HIT_INIT");
    return e && e[0] != '\0' && e[0] != '0';
}

bool liveness_enabled_for(const CACHE& c)
{
    const char* target_env = std::getenv("SRRIP_LIVE_TARGET");
    if (!target_env || target_env[0] == '\0' || std::string(target_env) == "llc")
        return c.NAME == "LLC";
    if (std::string(target_env) == "none")
        return false;
    std::string want = target_env;
    for (auto& ch : want) ch = static_cast<char>(std::toupper(static_cast<unsigned char>(ch)));
    return c.NAME == want || c.NAME == ("cpu0_" + want);
}

void shift_rank(uint32_t* ranks, uint32_t N, uint32_t way, uint32_t old_rank, uint32_t new_rank)
{
    if (new_rank > old_rank) {
        for (uint32_t w = 0; w < N; ++w)
            if (w != way && ranks[w] > old_rank && ranks[w] <= new_rank)
                --ranks[w];
    } else if (new_rank < old_rank) {
        for (uint32_t w = 0; w < N; ++w)
            if (w != way && ranks[w] >= new_rank && ranks[w] < old_rank)
                ++ranks[w];
    }
    ranks[way] = new_rank;
}

struct DoAInsertion { uint32_t rank; bool bypass; };

DoAInsertion doa_insertion(uint32_t N)
{
    switch (g_ins) {
        case DoAIns::LRUpos: return {0, false};
        case DoAIns::Bypass: return {0, true};
        default:             return {N - 1 - (2 * N / 3), false};
    }
}

uint32_t hit_promotion_target(int8_t cls, uint32_t N)
{
    if (hit_init_enabled() && cls == 1) return 0;
    return N - 1;
}

std::unordered_map<CACHE*, std::vector<uint32_t>> lru_rank;
std::unordered_map<CACHE*, std::vector<int8_t>>   slot_class;
std::unordered_map<CACHE*, std::vector<bool>>     bypassed;

std::unordered_map<CACHE*, std::vector<uint64_t>> fill_time;
std::unordered_map<CACHE*, std::vector<uint64_t>> last_hit_time;
std::unordered_map<CACHE*, std::vector<uint32_t>> hit_cnt;
std::unordered_map<CACHE*, std::vector<uint64_t>> set_clock;

struct Stats {
    uint64_t ins_unguided = 0, ins_doa = 0, ins_alive = 0, ins_doa_bypass = 0;
    uint64_t hit_unguided = 0, hit_doa = 0, hit_alive = 0, hit_doa_bypass = 0;
    uint64_t promo_capped_doa = 0;
    uint64_t evict_doa = 0, evict_alive = 0, evict_unguided = 0, evict_doa_bypass = 0;
    double   res_sum[3][2] = {};
    uint64_t res_cnt[3][2] = {};
    double   afterhit_sum[3] = {};
    uint64_t afterhit_cnt[3] = {};
};
std::unordered_map<CACHE*, Stats> stats;

uint32_t find_lru_victim(const uint32_t* ranks, uint32_t N)
{
    uint32_t victim = 0;
    for (uint32_t w = 1; w < N; ++w)
        if (ranks[w] < ranks[victim])
            victim = w;
    return victim;
}

void record_eviction(Stats& st, int8_t cls)
{
    switch (cls) {
        case 1:  st.evict_doa++;      break;
        case 2:  st.evict_alive++;    break;
        default: st.evict_unguided++; break;
    }
}

void record_residency(Stats& st, int8_t cls, uint64_t now, uint64_t fill_t, uint64_t last_hit_t, uint32_t hits)
{
    const int c  = (cls >= 0 && cls < 3) ? cls : 0;
    const int hb = hits > 0 ? 1 : 0;
    st.res_sum[c][hb] += static_cast<double>(now - fill_t);
    st.res_cnt[c][hb] += 1;
    if (hits > 0) {
        st.afterhit_sum[c] += static_cast<double>(now - last_hit_t);
        st.afterhit_cnt[c] += 1;
    }
}

void record_hit_class(Stats& st, int8_t cls)
{
    switch (cls) {
        case 1:  st.hit_doa++;   break;
        case 2:  st.hit_alive++; break;
        default: st.hit_unguided++; break;
    }
}

void promote_on_hit(uint32_t* ranks, uint32_t N, uint32_t way, int8_t cls, Stats& st)
{
    const uint32_t target = hit_promotion_target(cls, N);
    if (target != N - 1 && cls == 1)
        st.promo_capped_doa++;
    shift_rank(ranks, N, way, ranks[way], target);
}

bool handle_hit(uint32_t* ranks, uint32_t N, uint32_t way, int8_t cls, uint32_t type, bool use_liveness,
                 Stats& st, bool was_bypassed, uint64_t& last_hit_t, uint32_t& hits, uint64_t clk)
{
    if (type != WRITE) {
        promote_on_hit(ranks, N, way, cls, st);
        last_hit_t = clk;
        ++hits;
    }
    if (!use_liveness) {
        st.hit_unguided++;
        return was_bypassed;
    }
    if (cls == 1 && was_bypassed) {
        st.hit_doa_bypass++;
        record_hit_class(st, cls);
        return false;
    }
    record_hit_class(st, cls);
    return was_bypassed;
}

struct FillDecision { int8_t cls; uint32_t rank; bool bypass; };

FillDecision decide_fill(liveness_class lc, uint32_t N, Stats& st)
{
    if (lc == liveness_class::doa) {
        const DoAInsertion ins = doa_insertion(N);
        st.ins_doa++;
        if (ins.bypass) st.ins_doa_bypass++;
        return {1, ins.rank, ins.bypass};
    }
    st.ins_alive++;
    return {2, N - 1, false};
}

FillDecision handle_fill(uint32_t* ranks, uint32_t N, uint32_t way, bool use_liveness, liveness_class lc, Stats& st)
{
    const FillDecision d = use_liveness
        ? decide_fill(lc, N, st)
        : FillDecision{0, N - 1, false};
    if (!use_liveness) st.ins_unguided++;
    shift_rank(ranks, N, way, 0, d.rank);
    return d;
}

} // namespace

void CACHE::initialize_replacement()
{
    ::g_ins = ::parse_ins_mode();
    const std::size_t n = NUM_SET * NUM_WAY;
    auto& ranks = ::lru_rank[this];
    ranks.resize(n);
    for (uint32_t set = 0; set < NUM_SET; ++set)
        for (uint32_t way = 0; way < NUM_WAY; ++way)
            ranks[set * NUM_WAY + way] = way;
    ::slot_class[this]    = std::vector<int8_t>(n, 0);
    ::bypassed[this]      = std::vector<bool>(n, false);
    ::fill_time[this]     = std::vector<uint64_t>(n, 0);
    ::last_hit_time[this] = std::vector<uint64_t>(n, 0);
    ::hit_cnt[this]       = std::vector<uint32_t>(n, 0);
    ::set_clock[this]     = std::vector<uint64_t>(NUM_SET, 0);
    ::stats[this] = Stats{};
}

uint32_t CACHE::find_victim(uint32_t triggering_cpu, uint64_t instr_id, uint32_t set,
                             const BLOCK* current_set, uint64_t ip, uint64_t full_addr,
                             uint32_t type)
{
    const auto* ranks = ::lru_rank[this].data() + set * NUM_WAY;

    const std::vector<bool>& bypass_vec = ::bypassed[this];
    std::optional<uint32_t> bypass_victim;
    for (uint32_t w = 0; w < NUM_WAY; ++w)
        if (bypass_vec[set * NUM_WAY + w] && (!bypass_victim || ranks[w] < ranks[*bypass_victim]))
            bypass_victim = w;
    if (bypass_victim) return *bypass_victim;

    return ::find_lru_victim(ranks, NUM_WAY);
}

void CACHE::update_replacement_state(uint32_t triggering_cpu, uint32_t set, uint32_t way,
                                      uint64_t full_addr, uint64_t ip, uint64_t victim_addr,
                                      uint32_t type, uint8_t hit)
{
    const std::size_t base = set * NUM_WAY;
    const std::size_t slot = base + way;
    auto* ranks = ::lru_rank[this].data() + base;
    auto& cls   = ::slot_class[this][slot];
    auto& st    = ::stats[this];

    const uint64_t clk = ++::set_clock[this][set];
    const bool use_liveness = ::liveness_enabled_for(*this);

    if (hit) {
        ::bypassed[this][slot] = ::handle_hit(ranks, NUM_WAY, way, cls, type, use_liveness, st,
                                               ::bypassed[this][slot], ::last_hit_time[this][slot],
                                               ::hit_cnt[this][slot], clk);
        return;
    }

    if (::fill_time[this][slot] != 0) {
        ::record_eviction(st, cls);
        if (::bypassed[this][slot]) st.evict_doa_bypass++;
        ::record_residency(st, cls, clk, ::fill_time[this][slot], ::last_hit_time[this][slot], ::hit_cnt[this][slot]);
    }

    const liveness_class lc = use_liveness ? classify_block_liveness(full_addr, ip) : liveness_class::alive;
    const ::FillDecision fill = ::handle_fill(ranks, NUM_WAY, way, use_liveness, lc, st);
    cls = fill.cls;
    ::bypassed[this][slot] = fill.bypass;

    ::fill_time[this][slot]     = clk;
    ::last_hit_time[this][slot] = clk;
    ::hit_cnt[this][slot]       = 0;
}

void CACHE::replacement_final_stats()
{
    const auto& st = ::stats[this];
    const uint64_t total_ins  = st.ins_unguided + st.ins_doa + st.ins_alive;
    const uint64_t guided_ins = st.ins_doa + st.ins_alive;
    const uint64_t total_evict = st.evict_doa + st.evict_alive + st.evict_unguided;

    auto pct = [](uint64_t n, uint64_t d) -> double {
        return d ? 100.0 * n / d : 0.0;
    };

    const uint32_t N = NUM_WAY;

    const bool cap_doa = ::hit_init_enabled();

    auto ins_str = [](DoAIns m) -> const char* {
        switch (m) {
            case DoAIns::LRUpos: return "lru (rank 0, default)";
            case DoAIns::Bypass: return "bypass (rank 0, priority eviction)";
            default:             return "2n3";
        }
    };

    printf("%s LRU-Live STATS:\n", NAME.c_str());
    printf("  DoA ins mode     : %s  (LRU_LIVE_DOA_INS)\n", ins_str(::g_ins));
    printf("  Insertion positions: DoA=%s  Alive=%u/MRU  (N=%u)\n",
           ins_str(::g_ins), N - 1, N);
    printf("  Hit promotion    : %s\n",
           cap_doa ? "DoA capped to class initial position (LRU_LIVE_HIT_INIT=1)"
                   : "full to MRU");
    printf("  Activation rate  : %.1f%%  (%lu guided / %lu total insertions)\n",
           pct(guided_ins, total_ins), guided_ins, total_ins);
    printf("  guided_insertions=%lu\n", guided_ins);
    printf("  Insert mix       : DoA=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n",
           pct(st.ins_doa,total_ins), pct(st.ins_alive,total_ins), pct(st.ins_unguided,total_ins));
    printf("  Hit rate/class   : DoA=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n",
           pct(st.hit_doa,st.ins_doa), pct(st.hit_alive,st.ins_alive), pct(st.hit_unguided,st.ins_unguided));
    printf("  Promo capped (raw): DoA=%lu/%lu  (capped / hits-on-class, LRU_LIVE_HIT_INIT=%d)\n",
           st.promo_capped_doa, st.hit_doa, cap_doa ? 1 : 0);
    printf("  Evict class mix  : DoA=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n",
           pct(st.evict_doa,total_evict), pct(st.evict_alive,total_evict), pct(st.evict_unguided,total_evict));

    const char* cn[3] = {"Unguided", "DoA", "Alive"};
    auto mean = [](double s, uint64_t n) -> double { return n ? s / n : 0.0; };
    printf("  Residency (ticks) by class x reuse:\n");
    for (int c = 0; c < 3; ++c)
        printf("    %-11s  0hit: mean=%9.1f (n=%lu)   >=1hit: mean=%9.1f (n=%lu)   "
               "after-last-hit: mean=%9.1f (n=%lu)\n",
               cn[c], mean(st.res_sum[c][0], st.res_cnt[c][0]), st.res_cnt[c][0],
               mean(st.res_sum[c][1], st.res_cnt[c][1]), st.res_cnt[c][1],
               mean(st.afterhit_sum[c], st.afterhit_cnt[c]), st.afterhit_cnt[c]);

    print_pc_counter_stats(NAME.c_str());
    printf("\n");
}
