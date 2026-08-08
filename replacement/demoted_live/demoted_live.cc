#include <cassert>
#include <cstdint>
#include <cstdio>
#include <unordered_map>
#include <vector>

#include "cache.h"

namespace
{

std::unordered_map<CACHE*, std::unordered_map<uint64_t, bool>> pc_safe;

bool safe_for(CACHE* c, uint64_t pc) { return pc_safe[c][pc]; }

struct InsertionDecision { uint32_t rank; bool was_safe; };

InsertionDecision decide_insertion(bool is_safe, uint32_t N)
{
    if (is_safe) return {N - 1, true};
    uint32_t pos = N / 2;
    if (pos < 1) pos = 1;
    return {pos - 1, false};
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

uint32_t find_lru_victim(const uint32_t* ranks, uint32_t N)
{
    uint32_t victim = 0;
    for (uint32_t w = 1; w < N; ++w)
        if (ranks[w] < ranks[victim])
            victim = w;
    return victim;
}

std::unordered_map<CACHE*, std::vector<uint32_t>> ranks_by_cache;

struct WayTag { bool occupied = false; uint64_t ip = 0; bool was_safe = false; uint32_t hit_count = 0; };
std::unordered_map<CACHE*, std::vector<WayTag>> way_tags;

struct TierStat { uint64_t installs = 0, hit_before_evict = 0, doa_evict = 0, hit_events = 0; };
std::unordered_map<CACHE*, TierStat> reduced_stats, safe_stats;

struct Stats {
    uint64_t ins_reduced = 0, ins_safe = 0;
    uint64_t evictions_seen = 0, fills_seen = 0, hits = 0;
};
std::unordered_map<CACHE*, Stats> stats;

bool applies_to(const CACHE& c) { return c.NAME == "LLC"; }

} // namespace

void CACHE::initialize_replacement()
{
    const std::size_t n = NUM_SET * NUM_WAY;
    auto& ranks = ::ranks_by_cache[this];
    ranks.resize(n);
    for (uint32_t set = 0; set < NUM_SET; ++set)
        for (uint32_t way = 0; way < NUM_WAY; ++way)
            ranks[set * NUM_WAY + way] = way;
    ::pc_safe[this].clear();
    ::way_tags[this].assign(n, ::WayTag{});
    ::reduced_stats[this] = ::TierStat{};
    ::safe_stats[this] = ::TierStat{};
    ::stats[this] = ::Stats{};
}

uint32_t CACHE::find_victim(uint32_t triggering_cpu, uint64_t instr_id, uint32_t set,
                             const BLOCK* current_set, uint64_t ip, uint64_t full_addr,
                             uint32_t type)
{
    if (!::applies_to(*this))
        return ::find_lru_victim(::ranks_by_cache[this].data() + set * NUM_WAY, NUM_WAY);

    return ::find_lru_victim(::ranks_by_cache[this].data() + set * NUM_WAY, NUM_WAY);
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
            ::way_tags[this][idx].hit_count++;
        }
        return;
    }

    ::WayTag& outgoing = ::way_tags[this][idx];
    if (outgoing.occupied) {
        st.evictions_seen++;
        const bool was_hit = outgoing.hit_count > 0;
        ::pc_safe[this][outgoing.ip] = was_hit;
        ::TierStat& ts = outgoing.was_safe ? ::safe_stats[this] : ::reduced_stats[this];
        if (was_hit) ts.hit_before_evict++; else ts.doa_evict++;
        ts.hit_events += outgoing.hit_count;
    }

    const bool is_safe = ::safe_for(this, ip);
    const ::InsertionDecision d = ::decide_insertion(is_safe, NUM_WAY);

    st.fills_seen++;
    if (d.was_safe) st.ins_safe++; else st.ins_reduced++;

    ::TierStat& install_ts = d.was_safe ? ::safe_stats[this] : ::reduced_stats[this];
    install_ts.installs++;
    ::way_tags[this][idx] = {true, ip, d.was_safe, 0};

    ::shift_rank(ranks, NUM_WAY, way, 0, d.rank);
}

void CACHE::replacement_final_stats()
{
    const auto& st = ::stats[this];
    const uint64_t total_ins = st.ins_reduced + st.ins_safe;

    auto pct = [](uint64_t n, uint64_t d) -> double { return d ? 100.0 * n / d : 0.0; };

    printf("%s DEMOTED-LIVE STATS:\n", NAME.c_str());
    printf("  Insertions       : reduced=%lu  mru(safe)=%lu\n", st.ins_reduced, st.ins_safe);
    printf("  Insert mix       : reduced=%.1f%%  mru(safe)=%.1f%%\n",
           pct(st.ins_reduced, total_ins), pct(st.ins_safe, total_ins));
    printf("  Hits             : %lu\n", st.hits);

    const bool ins_closed = (total_ins == st.fills_seen);
    printf("  Closure          : insertions %lu/%lu (%s)\n",
           total_ins, st.fills_seen, ins_closed ? "OK" : "MISMATCH");
    assert(ins_closed && "demoted_live: insertion buckets don't sum to fills_seen");

    const ::TierStat tiers[2] = {::reduced_stats[this], ::safe_stats[this]};
    const char* names[2] = {"reduced", "safe"};
    for (int i = 0; i < 2; ++i) {
        const ::TierStat& ts = tiers[i];
        const uint64_t resolved = ts.hit_before_evict + ts.doa_evict;
        const double avg_hits = ts.hit_before_evict ? static_cast<double>(ts.hit_events) / ts.hit_before_evict : 0.0;
        printf("  Tier %-8s: installs=%-8lu resolved=%-8lu hit-rate=%6.1f%%  avg-hits/reused=%.2f\n",
               names[i], ts.installs, resolved, pct(ts.hit_before_evict, resolved), avg_hits);
    }
    printf("\n");
}
