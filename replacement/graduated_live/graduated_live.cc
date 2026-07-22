// graduated_live — per-PC graduated insertion-position scheme, isolated
// from cache_liveness.cc's THD_DOA/pc_counters system.
//
// Fresh PC -> inserted at N/2 (middle). Hit -> promote to MRU. Eviction
// judges the outgoing PC by its own accessed bit: accessed -> PC goes on
// the safe list (next fill inserts at MRU, num_doa cleared); !accessed ->
// off the safe list, num_doa += 1. A PC's num_doa sets its next insertion
// position (LRU end = 1, 1-indexed): N / 2^(num_doa+1). Once that would be
// <=1, the PC bypasses instead: literal skip, no cache line used.
//
// Per-PC state keyed by full PC, not hashed -- hashing would conflate
// unrelated PCs' history. A hashed variant is a separate later change.

#include <cassert>
#include <cstdint>
#include <optional>
#include <unordered_map>
#include <vector>

#include "cache.h"

namespace
{

constexpr uint16_t MAX_NUM_DOA = 20;

struct PCState {
    uint16_t num_doa = 0;
    bool     is_safe = false;
};

std::unordered_map<CACHE*, std::unordered_map<uint64_t, PCState>> pc_state;

PCState& state_for(CACHE* c, uint64_t pc) { return pc_state[c][pc]; }

struct InsertionDecision { bool bypass; uint32_t rank; };

uint32_t graduated_position(uint32_t N, uint16_t num_doa)
{
    return N / (1u << (num_doa + 1));
}

InsertionDecision decide_insertion(const PCState& st, uint32_t N)
{
    if (st.is_safe)
        return {false, N - 1};
    const uint32_t pos = graduated_position(N, st.num_doa);
    if (pos <= 1)
        return {true, 0};
    return {false, pos - 1};
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

struct Stats {
    uint64_t ins_middle = 0, ins_graduated = 0, ins_mru_safe = 0, ins_bypass = 0;
    uint64_t fills_seen = 0;
    uint64_t evict_to_safe = 0, evict_doa_streak = 0;
    uint64_t evictions_seen = 0;
    uint64_t hits = 0;
};
std::unordered_map<CACHE*, Stats> stats;

// Decision computed once in find_victim; update_replacement_state consumes
// it instead of recomputing. Empty means a free-slot fill (find_victim
// never ran), which computes fresh.
std::unordered_map<CACHE*, std::optional<InsertionDecision>> pending_decision;

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
    ::pc_state[this].clear();
    ::stats[this] = ::Stats{};
    ::pending_decision[this] = std::nullopt;
}

uint32_t CACHE::find_victim(uint32_t triggering_cpu, uint64_t instr_id, uint32_t set,
                             const BLOCK* current_set, uint64_t ip, uint64_t full_addr,
                             uint32_t type)
{
    if (!::applies_to(*this))
        return ::find_lru_victim(::ranks_by_cache[this].data() + set * NUM_WAY, NUM_WAY);

    auto& st = ::stats[this];
    const uint32_t* ranks = ::ranks_by_cache[this].data() + set * NUM_WAY;
    const uint32_t victim = ::find_lru_victim(ranks, NUM_WAY);
    const BLOCK& outgoing = current_set[victim];
    if (outgoing.valid) {
        st.evictions_seen++;
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

    const ::PCState& incoming = ::state_for(this, ip);
    const ::InsertionDecision d = ::decide_insertion(incoming, NUM_WAY);
    st.fills_seen++;
    if (d.bypass) {
        st.ins_bypass++;
        ::pending_decision[this] = std::nullopt;
        return NUM_WAY;
    }
    if (incoming.is_safe) st.ins_mru_safe++;
    else if (incoming.num_doa == 0) st.ins_middle++;
    else st.ins_graduated++;
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
    auto* ranks = ::ranks_by_cache[this].data() + base;
    auto& st = ::stats[this];

    if (hit) {
        if (type != WRITE) {
            shift_rank(ranks, NUM_WAY, way, ranks[way], NUM_WAY - 1);
            st.hits++;
        }
        return;
    }

    auto& pending = ::pending_decision[this];
    ::InsertionDecision d;
    if (pending) {
        d = *pending;
        pending = std::nullopt;
    } else {
        // Free-slot fill: find_victim never ran, compute fresh.
        const ::PCState& incoming = ::state_for(this, ip);
        d = ::decide_insertion(incoming, NUM_WAY);
        st.fills_seen++;
        if (incoming.is_safe) st.ins_mru_safe++;
        else if (incoming.num_doa == 0) st.ins_middle++;
        else st.ins_graduated++;
    }
    // A free-slot d.bypass can't actually skip (nothing to evict); its
    // rank=0 fallback still lands it at the LRU end.
    ::shift_rank(ranks, NUM_WAY, way, /*old_rank=*/0, d.rank);
}

void CACHE::replacement_final_stats()
{
    const auto& st = ::stats[this];
    const uint64_t total_ins = st.ins_middle + st.ins_graduated + st.ins_mru_safe + st.ins_bypass;
    const uint64_t total_evict = st.evict_to_safe + st.evict_doa_streak;

    auto pct = [](uint64_t n, uint64_t d) -> double { return d ? 100.0 * n / d : 0.0; };

    printf("%s GRADUATED-LIVE STATS:\n", NAME.c_str());
    printf("  Insertions       : middle=%lu  graduated=%lu  mru(safe)=%lu  bypassed=%lu\n",
           st.ins_middle, st.ins_graduated, st.ins_mru_safe, st.ins_bypass);
    printf("  Insert mix       : middle=%.1f%%  graduated=%.1f%%  mru(safe)=%.1f%%  bypassed=%.1f%%\n",
           pct(st.ins_middle, total_ins), pct(st.ins_graduated, total_ins),
           pct(st.ins_mru_safe, total_ins), pct(st.ins_bypass, total_ins));
    printf("  Evictions        : to-safe-list=%lu  doa-streak-continues=%lu\n",
           st.evict_to_safe, st.evict_doa_streak);
    printf("  Hits             : %lu\n", st.hits);

    const bool ins_closed = (total_ins == st.fills_seen);
    const bool evict_closed = (total_evict == st.evictions_seen);
    printf("  Closure          : insertions %lu/%lu (%s)   evictions %lu/%lu (%s)\n",
           total_ins, st.fills_seen, ins_closed ? "OK" : "MISMATCH",
           total_evict, st.evictions_seen, evict_closed ? "OK" : "MISMATCH");
    assert(ins_closed && "graduated_live: insertion buckets don't sum to fills_seen");
    assert(evict_closed && "graduated_live: eviction outcomes don't sum to evictions_seen");

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
