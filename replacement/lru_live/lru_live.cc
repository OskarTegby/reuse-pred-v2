// lru_live — LRU with liveness-informed insertion position.
//
// Policy rules (two liveness classes: was the block ever touched before
// eviction? "mostly-dead" — an intermediate, wall-clock-halflife-based third
// class — was tried and removed: no configuration tested showed it
// contributing a real, reproducible IPC benefit, and it was actively costing
// IPC on some suites. Set dueling between conservative (2N/3) and aggressive
// (rank 0) DoA insertion was tried too and removed: aggressive won outright
// on every suite tested.)
// --------------------------------------
//   DoA fill:   position 0 (LRU end) — immediate eviction candidate
//   Alive fill: position N-1 (MRU)   — standard LRU
//   All hits:   full promotion to MRU
//
// Capped-promotion variant (env LRU_LIVE_HIT_INIT=1)
// ---------------------------------------------------
//   On a (read) hit, instead of promoting every block to MRU, a DoA-classified
//   block is instead moved to its class's initial insertion position (rank 0)
//   rather than earning full credit. Default off (=0): full MRU promotion on
//   every hit.
//
// Internal representation: per-slot rank, 0=LRU, N-1=MRU.
// All N ranks in a set are always a permutation of [0, N-1].

#include <cassert>
#include <cstdint>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "cache.h"

// DoA insertion mode (LRU_LIVE_DOA_INS env var):
//   "lru"    (default): insert DoA at rank 0 (LRU position, evicted on next fill)
//   "2n3"            : insert DoA at 2N/3 from MRU
//   "bypass"         : insert DoA at rank 0 AND mark as bypass-priority, so
//                      find_victim always returns bypass slots before any other

namespace
{

enum class DoAIns { Pos2N3, LRUpos, Bypass };

bool bypass_allowed()
{
    const char* e = std::getenv("LRU_LIVE_ALLOW_BYPASS");
    // Default: bypass allowed. Set LRU_LIVE_ALLOW_BYPASS=0 to disable globally.
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

// SRRIP_LIVE_TARGET=none explicitly disables liveness guidance while still
// on the LLC (used by the "bypass" condition: raw DoA bypass stays active in
// cache.cc, but insertion/promotion here falls back to plain LRU). Liveness
// guidance never applies anywhere but the LLC.
bool liveness_enabled_for(const CACHE& c)
{
    const char* target_env = std::getenv("SRRIP_LIVE_TARGET");
    const bool disabled = target_env && target_env[0] != '\0' && std::string(target_env) != "llc";
    return (c.NAME == "LLC") && !disabled;
}

// --- Rank permutation --------------------------------------------------------
// rank[way] in [0, N-1]; 0 = LRU (next victim), N-1 = MRU. Always a
// permutation of [0, N-1] across all ways in a set.

// Moves `way` from `old_rank` to `new_rank`, shifting every way in between
// by one to keep the set a valid permutation.
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

// --- DoA insertion/promotion rules --------------------------------------------

struct DoAInsertion { uint32_t rank; bool bypass; };

DoAInsertion doa_insertion(uint32_t N)
{
    switch (g_ins) {
        case DoAIns::LRUpos: return {0, false};
        case DoAIns::Bypass: return {0, true};
        default:             return {N - 1 - (2 * N / 3), false}; // Pos2N3
    }
}

uint32_t hit_promotion_target(int8_t cls, uint32_t N)
{
    if (hit_init_enabled() && cls == 1) return 0; // DoA: capped to initial position
    return N - 1;                                  // full promotion to MRU
}

// --- Per-CACHE* state ---------------------------------------------------------

std::unordered_map<CACHE*, std::vector<uint32_t>> lru_rank;
std::unordered_map<CACHE*, std::vector<int8_t>>   slot_class; // 0=unguided 1=doa 2=alive
std::unordered_map<CACHE*, std::vector<bool>>     bypassed;   // true = evict-first

// Residency instrumentation. Time is measured in per-set "ticks": one tick per
// update_replacement_state call for that set (every access touching the set).
// Residency of a block = ticks survived between its fill and its eviction.
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

// --- Victim selection ----------------------------------------------------------

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

// Residency: ticks the victim survived. `now` is the count of set accesses so
// far; the imminent fill (a hit=false update) will advance it.
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

// --- Hit handling ----------------------------------------------------------

void record_hit_class(Stats& st, int8_t cls)
{
    switch (cls) {
        case 1:  st.hit_doa++;   break;
        case 2:  st.hit_alive++; break;
        default: st.hit_unguided++; break;
    }
}

// Promotes the hit way to its class's target rank; a DoA hit only earns full
// MRU credit unless capped by LRU_LIVE_HIT_INIT.
void promote_on_hit(uint32_t* ranks, uint32_t N, uint32_t way, int8_t cls, Stats& st)
{
    const uint32_t target = hit_promotion_target(cls, N);
    if (target != N - 1 && cls == 1)
        st.promo_capped_doa++;
    shift_rank(ranks, N, way, ranks[way], target);
}

// No write-hit special-case: keep the no-liveness default path identical to
// baseline LRU so any speedup is attributable to liveness alone (matches the
// fix applied to srrip_live/ipv_live). Returns the slot's bypass flag after
// this hit (std::vector<bool> doesn't support real references, so the
// caller assigns the result back rather than passing one in).
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
    // A bypass-flagged DoA slot that gets a hit proved itself: demote the
    // bypass flag so it is no longer eviction-priority and can age normally.
    if (cls == 1 && was_bypassed) {
        st.hit_doa_bypass++;
        record_hit_class(st, cls);
        return false;
    }
    record_hit_class(st, cls);
    return was_bypassed;
}

// --- Fill handling ---------------------------------------------------------

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
    shift_rank(ranks, N, way, /*old_rank=*/0, d.rank); // evicted way just vacated rank 0
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
    auto& st = ::stats[this];

    const std::vector<bool>& bypass_vec = ::bypassed[this];
    std::optional<uint32_t> bypass_victim;
    for (uint32_t w = 0; w < NUM_WAY; ++w)
        if (bypass_vec[set * NUM_WAY + w] && (!bypass_victim || ranks[w] < ranks[*bypass_victim]))
            bypass_victim = w;
    if (bypass_victim) {
        st.evict_doa_bypass++;
        return *bypass_victim;
    }

    const uint32_t victim = ::find_lru_victim(ranks, NUM_WAY);
    const std::size_t vi = set * NUM_WAY + victim;
    const int8_t cls = ::slot_class[this][vi];
    ::record_eviction(st, cls);
    ::record_residency(st, cls, ::set_clock[this][set], ::fill_time[this][vi], ::last_hit_time[this][vi], ::hit_cnt[this][vi]);
    return victim;
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

    // One tick per set access (hit or fill) — the residency clock.
    const uint64_t clk = ++::set_clock[this][set];
    const bool use_liveness = ::liveness_enabled_for(*this);

    if (hit) {
        ::bypassed[this][slot] = ::handle_hit(ranks, NUM_WAY, way, cls, type, use_liveness, st,
                                               ::bypassed[this][slot], ::last_hit_time[this][slot],
                                               ::hit_cnt[this][slot], clk);
        return;
    }

    const liveness_class lc = use_liveness ? classify_block_liveness(full_addr, ip, set) : liveness_class::alive;
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

    // Residency (mean ticks survived) by class x reuse. Ticks = per-set accesses.
    //   Check 1: among 0-hit blocks, DoA < Alive/Unguided (insertion logic).
    //   Check 2: after-last-hit for DoA should SHRINK under LRU_LIVE_HIT_INIT.
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
