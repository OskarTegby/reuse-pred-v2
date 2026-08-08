#include <cassert>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "cache.h"

namespace
{

constexpr uint16_t MAX_NUM_DOA = 1023;
constexpr int SAFE_TIER = -1;

struct PCState {
    uint16_t num_doa = 0;
    bool     is_safe = false;
};

std::unordered_map<CACHE*, std::unordered_map<uint64_t, PCState>> pc_state;
std::unordered_map<CACHE*, uint16_t> bypass_thd_by_cache;

PCState& state_for(CACHE* c, uint64_t pc) { return pc_state[c][pc]; }

struct InsertionDecision { bool bypass; uint32_t rank; bool was_safe; uint16_t num_doa; };

InsertionDecision decide_insertion(const PCState& st, uint32_t N, uint16_t thd)
{
    if (st.is_safe)
        return {false, N - 1, true, 0};
    if (st.num_doa > thd)
        return {true, 0, false, st.num_doa};
    uint32_t pos = N / 2;
    if (pos < 1) pos = 1;
    return {false, pos - 1, false, st.num_doa};
}

int tier_of(const InsertionDecision& d) { return d.was_safe ? ::SAFE_TIER : static_cast<int>(d.num_doa); }

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

uint32_t find_lru_victim(const uint32_t* ranks, uint32_t N)
{
    uint32_t victim = 0;
    for (uint32_t w = 1; w < N; ++w)
        if (ranks[w] < ranks[victim])
            victim = w;
    return victim;
}

std::unordered_map<CACHE*, std::vector<uint32_t>> ranks_by_cache;

struct WayTag { bool occupied = false; bool was_safe = false; uint16_t num_doa = 0; uint32_t hit_count = 0; };
std::unordered_map<CACHE*, std::vector<WayTag>> way_tags;

struct TierStat { uint64_t installs = 0, hit_before_evict = 0, doa_evict = 0, hit_events = 0; };
std::unordered_map<CACHE*, std::map<int, TierStat>> tier_stats;

void record_install(CACHE* c, std::size_t idx, const InsertionDecision& d)
{
    ::way_tags[c][idx] = {true, d.was_safe, d.num_doa, 0};
    ::tier_stats[c][::tier_of(d)].installs++;
}

void record_hit(CACHE* c, std::size_t idx)
{
    ::WayTag& tag = ::way_tags[c][idx];
    if (tag.occupied) ++tag.hit_count;
}

void record_outcome(CACHE* c, std::size_t idx, bool accessed)
{
    const ::WayTag& tag = ::way_tags[c][idx];
    if (!tag.occupied) return;
    const int tier = tag.was_safe ? ::SAFE_TIER : static_cast<int>(tag.num_doa);
    ::TierStat& ts = ::tier_stats[c][tier];
    if (accessed) ts.hit_before_evict++;
    else ts.doa_evict++;
    ts.hit_events += tag.hit_count;
}

struct Stats {
    uint64_t ins_middle = 0, ins_mru_safe = 0, ins_bypass = 0;
    uint64_t fills_seen = 0;
    uint64_t evict_to_safe = 0, evict_doa_streak = 0;
    uint64_t evictions_seen = 0;
    uint64_t hits = 0;
};
std::unordered_map<CACHE*, Stats> stats;

std::unordered_map<CACHE*, std::optional<InsertionDecision>> pending_decision;

// Which cache this policy governs. Unset or "llc" keeps the historical
// LLC-only behaviour; "none" disables it; otherwise the value names the level,
// matching the targeting convention used by the other liveness policies.
bool applies_to(const CACHE& c)
{
    const char* target = std::getenv("MID_BYPASS_TARGET");
    if (!target || target[0] == '\0' || std::string(target) == "llc")
        return c.NAME == "LLC";
    if (std::string(target) == "none")
        return false;
    std::string want = target;
    for (auto& ch : want) ch = static_cast<char>(std::toupper(static_cast<unsigned char>(ch)));
    return c.NAME == want || c.NAME == ("cpu0_" + want);
}

uint16_t getenv_u16(const char* var, uint16_t fallback)
{
    const char* v = std::getenv(var);
    return v && *v ? static_cast<uint16_t>(std::stoul(v)) : fallback;
}

} // namespace

void CACHE::initialize_replacement()
{
    const std::size_t n = NUM_SET * NUM_WAY;
    auto& ranks = ::ranks_by_cache[this];
    ranks.resize(n);
    for (uint32_t set = 0; set < NUM_SET; ++set)
        for (uint32_t way = 0; way < NUM_WAY; ++way)
            ranks[set * NUM_WAY + way] = way;
    ::pc_state[this].clear();
    ::stats[this] = ::Stats{};
    ::pending_decision[this] = std::nullopt;
    ::bypass_thd_by_cache[this] = ::getenv_u16("BYPASS_THD", 6);
    ::way_tags[this].assign(n, ::WayTag{});
    ::tier_stats[this].clear();
}

uint32_t CACHE::find_victim(uint32_t triggering_cpu, uint64_t instr_id, uint32_t set,
                             const BLOCK* current_set, uint64_t ip, uint64_t full_addr,
                             uint32_t type)
{
    if (!::applies_to(*this))
        return ::find_lru_victim(::ranks_by_cache[this].data() + set * NUM_WAY, NUM_WAY);

    auto& st = ::stats[this];
    const uint16_t thd = ::bypass_thd_by_cache[this];
    const uint32_t* ranks = ::ranks_by_cache[this].data() + set * NUM_WAY;
    const uint32_t victim = ::find_lru_victim(ranks, NUM_WAY);
    const std::size_t victim_idx = set * NUM_WAY + victim;

    const ::PCState& incoming = ::state_for(this, ip);
    const ::InsertionDecision d = ::decide_insertion(incoming, NUM_WAY, thd);
    st.fills_seen++;
    if (d.bypass) {
        st.ins_bypass++;
        ::pending_decision[this] = std::nullopt;
        return NUM_WAY;
    }

    const BLOCK& outgoing = current_set[victim];
    if (outgoing.valid) {
        st.evictions_seen++;
        ::record_outcome(this, victim_idx, outgoing.accessed);
        ::PCState& vs = ::state_for(this, outgoing.ip);
        if (outgoing.accessed) {
            vs.is_safe = true;
            vs.num_doa = 0;
            st.evict_to_safe++;
        } else {
            vs.is_safe = false;
            if (vs.num_doa < ::MAX_NUM_DOA) ++vs.num_doa;
            st.evict_doa_streak++;
        }
    }

    if (incoming.is_safe) st.ins_mru_safe++;
    else st.ins_middle++;
    ::pending_decision[this] = d;
    return victim;
}

void CACHE::update_replacement_state(uint32_t triggering_cpu, uint32_t set, uint32_t way,
                                      uint64_t full_addr, uint64_t ip, uint64_t victim_addr,
                                      uint32_t type, uint8_t hit)
{
    if (!::applies_to(*this))
        return;

    const std::size_t base = set * NUM_WAY;
    const std::size_t idx = base + way;
    auto* ranks = ::ranks_by_cache[this].data() + base;
    auto& st = ::stats[this];

    if (hit) {
        if (type != WRITE) {
            shift_rank(ranks, NUM_WAY, way, ranks[way], NUM_WAY - 1);
            st.hits++;
            ::record_hit(this, idx);
        }
        return;
    }

    auto& pending = ::pending_decision[this];
    ::InsertionDecision d;
    if (pending) {
        d = *pending;
        pending = std::nullopt;
    } else {
        const uint16_t thd = ::bypass_thd_by_cache[this];
        const ::PCState& incoming = ::state_for(this, ip);
        d = ::decide_insertion(incoming, NUM_WAY, thd);
        st.fills_seen++;
        if (d.bypass) st.ins_bypass++;
        else if (incoming.is_safe) st.ins_mru_safe++;
        else st.ins_middle++;
    }
    if (!d.bypass) ::record_install(this, idx, d);
    ::shift_rank(ranks, NUM_WAY, way, 0, d.rank);
}

void CACHE::replacement_final_stats()
{
    const auto& st = ::stats[this];
    const uint64_t total_ins = st.ins_middle + st.ins_mru_safe + st.ins_bypass;
    const uint64_t total_evict = st.evict_to_safe + st.evict_doa_streak;

    auto pct = [](uint64_t n, uint64_t d) -> double { return d ? 100.0 * n / d : 0.0; };

    printf("%s MID-BYPASS-LIVE STATS (thd=%u):\n", NAME.c_str(), ::bypass_thd_by_cache[this]);
    printf("  Insertions       : middle=%lu  mru(safe)=%lu  bypassed=%lu\n",
           st.ins_middle, st.ins_mru_safe, st.ins_bypass);
    printf("  Insert mix       : middle=%.1f%%  mru(safe)=%.1f%%  bypassed=%.1f%%\n",
           pct(st.ins_middle, total_ins), pct(st.ins_mru_safe, total_ins), pct(st.ins_bypass, total_ins));
    printf("  Evictions        : to-safe-list=%lu  doa-streak-continues=%lu\n",
           st.evict_to_safe, st.evict_doa_streak);
    printf("  Hits             : %lu\n", st.hits);

    const bool ins_closed = (total_ins == st.fills_seen);
    const bool evict_closed = (total_evict == st.evictions_seen);
    printf("  Closure          : insertions %lu/%lu (%s)   evictions %lu/%lu (%s)\n",
           total_ins, st.fills_seen, ins_closed ? "OK" : "MISMATCH",
           total_evict, st.evictions_seen, evict_closed ? "OK" : "MISMATCH");
    assert(ins_closed && "mid_bypass_live: insertion buckets don't sum to fills_seen");
    assert(evict_closed && "mid_bypass_live: eviction outcomes don't sum to evictions_seen");

    printf("  Tier calibration (installs -> outcome before that occupant's own next eviction):\n");
    uint64_t total_doa_evict = 0, total_hit_before_evict = 0;
    for (const auto& [tier, ts] : ::tier_stats[this]) {
        const uint64_t resolved = ts.hit_before_evict + ts.doa_evict;
        total_doa_evict += ts.doa_evict;
        total_hit_before_evict += ts.hit_before_evict;
        const char* label_buf = (tier == ::SAFE_TIER) ? "safe(mru)" : nullptr;
        char numbuf[16];
        const char* label = label_buf;
        if (!label) { snprintf(numbuf, sizeof(numbuf), "doa=%d", tier); label = numbuf; }
        const double avg_hits = ts.hit_before_evict ? static_cast<double>(ts.hit_events) / ts.hit_before_evict : 0.0;
        printf("    %-10s: installs=%-8lu resolved=%-8lu hit-rate=%6.1f%%  doa-evict-rate=%6.1f%%  "
               "hit-events=%-8lu avg-hits/reused=%.2f\n",
               label, ts.installs, resolved, pct(ts.hit_before_evict, resolved), pct(ts.doa_evict, resolved),
               ts.hit_events, avg_hits);
    }

    const uint64_t still_resident = total_ins - st.ins_bypass - total_doa_evict - total_hit_before_evict;
    printf("  Miss attribution (of fills_seen=%lu):\n", st.fills_seen);
    printf("    bypassed (never cached)              : %lu (%.1f%%)\n",
           st.ins_bypass, pct(st.ins_bypass, st.fills_seen));
    printf("    cached, evicted without a hit (waste) : %lu (%.1f%%)\n",
           total_doa_evict, pct(total_doa_evict, st.fills_seen));
    printf("    cached, hit at least once (recovered) : %lu (%.1f%%)\n",
           total_hit_before_evict, pct(total_hit_before_evict, st.fills_seen));
    printf("    still resident at end of run          : %lu (%.1f%%)\n",
           still_resident, pct(still_resident, st.fills_seen));

    const auto& table = ::pc_state[this];
    uint64_t safe_count = 0;
    std::vector<uint64_t> doa_histogram(::MAX_NUM_DOA + 1, 0);
    for (const auto& [pc, s] : table) {
        if (s.is_safe) ++safe_count;
        else ++doa_histogram[s.num_doa];
    }
    printf("  PC state (end of run): %zu distinct PCs tracked, %lu (%.1f%%) on safe list\n",
           table.size(), safe_count, pct(safe_count, table.size()));
    printf("  num_doa histogram (restricted PCs only): ");
    for (uint16_t k = 0; k < doa_histogram.size(); ++k)
        if (doa_histogram[k]) printf("[%u]=%lu ", k, doa_histogram[k]);
    printf("\n\n");
}
