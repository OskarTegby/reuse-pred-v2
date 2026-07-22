// graduated_live — self-contained (isolated from cache_liveness.cc's shared
// THD_DOA/pc_counters system) per-PC graduated insertion-position scheme.
//
// Every entry starts inserted in the middle of the recency stack, before any
// evidence exists that its PC is DoA-prone. A hit always promotes fully to
// MRU. On eviction, the outgoing block's PC is judged by its own `accessed`
// bit:
//   accessed  -> PC goes on the "safe list": its NEXT fill is inserted at
//                MRU like a plain cache, and its DoA counter is cleared.
//   !accessed -> PC leaves the safe list (if it was on it) and its DoA
//                counter (num_doa) increments by one.
//
// A PC's current num_doa sets its NEXT insertion position. With the LRU end
// denoted position 1 (1-indexed) and N = NUM_WAY:
//
//     position(num_doa) = N / 2^(num_doa + 1)
//
// num_doa=0 (a fresh PC, or one just off the safe list) -> N/2, the middle.
// num_doa=1 -> N/4 (bottom quarter), num_doa=2 -> N/8, and so on, halving
// each time that PC's blocks keep dying. Once the computed position would be
// at or past the LRU end (<=1), the PC bypasses instead of inserting at LRU:
// the fill is served straight through and never occupies a cache line at
// all (see the NUM_WAY sentinel below), continuing until (if ever) that PC
// earns its way back onto the safe list.
//
// A PC that breaks probation (DoA again right after being marked safe)
// resumes at num_doa=1 (N/4), not back at the middle -- clearing num_doa to
// 0 on the safe-list transition and incrementing normally on the very next
// DoA eviction produces exactly this without a special case.
//
// LLC only, unconditionally (no target/duel knob -- this binary's replacement
// slot is this scheme, full stop; compare it against plain LRU / other _live
// binaries at the binary level like every other policy here).
//
// Literal-skip bypass note: this module signals "no victim, skip this fill"
// by returning NUM_WAY from find_victim, a value no valid way index can ever
// take. src/cache.cc's handle_fill treats that as way=set_end, the same
// terminal state resolve_fill_bypass() produces for the *shared*
// LIVENESS_BYPASS mechanism -- but this policy never touches that shared
// mechanism's state (bypass_enabled/pc_counters/bypass_thd), so it works
// whether or not LIVENESS_BYPASS is set for this run.

#include <cstdint>
#include <unordered_map>
#include <vector>

#include "cache.h"

namespace
{

// --- Isolated per-PC state ---------------------------------------------------
// Deliberately not cache_liveness.cc's pc_counters/THD_DOA: this scheme's
// per-PC state (a DoA streak count + a safe-list flag) is a different shape
// entirely, so it gets its own small hashed table.

constexpr unsigned TABLE_SIZE = 256;
constexpr uint16_t MAX_NUM_DOA = 20; // saturates well past any real NUM_WAY's bypass point

unsigned hash_pc(uint64_t pc)
{
    return static_cast<unsigned>((pc ^ (pc >> 2) ^ (pc >> 5)) % TABLE_SIZE);
}

struct PCState {
    uint16_t num_doa = 0;
    bool     is_safe = false;
};

std::unordered_map<CACHE*, std::vector<PCState>> pc_state;

PCState& state_for(CACHE* c, uint64_t pc)
{
    return pc_state[c][hash_pc(pc)];
}

// --- Insertion decision -------------------------------------------------------

struct InsertionDecision { bool bypass; uint32_t rank; };

// 1-indexed position (1 = LRU end); N / 2^(num_doa+1). Integer division means
// this reaches <=1 (bypass territory) for any N, power-of-two or not.
uint32_t graduated_position(uint32_t N, uint16_t num_doa)
{
    const uint32_t denom = 1u << (num_doa + 1);
    return N / denom;
}

InsertionDecision decide_insertion(const PCState& st, uint32_t N)
{
    if (st.is_safe)
        return {false, N - 1}; // MRU, like normal

    const uint32_t pos = graduated_position(N, st.num_doa);
    if (pos <= 1)
        return {true, 0}; // rank unused when bypassing
    return {false, pos - 1}; // convert 1-indexed position -> 0-indexed rank
}

// --- Rank permutation (same primitive as lru_live.cc; duplicated rather than
// shared, to keep this module self-contained in its own file) ---------------

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

// --- Per-CACHE* state ---------------------------------------------------------

std::unordered_map<CACHE*, std::vector<uint32_t>> ranks_by_cache;

struct Stats {
    uint64_t ins_middle = 0, ins_graduated = 0, ins_mru_safe = 0, ins_bypass = 0;
    uint64_t evict_to_safe = 0, evict_doa_streak = 0;
    uint64_t hits = 0;
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
    ::pc_state[this] = std::vector<::PCState>(::TABLE_SIZE);
    ::stats[this] = ::Stats{};
}

uint32_t CACHE::find_victim(uint32_t triggering_cpu, uint64_t instr_id, uint32_t set,
                             const BLOCK* current_set, uint64_t ip, uint64_t full_addr,
                             uint32_t type)
{
    if (!::applies_to(*this))
        return ::find_lru_victim(::ranks_by_cache[this].data() + set * NUM_WAY, NUM_WAY);

    auto& st = ::stats[this];

    // Judge the outgoing block's PC by its own accessed bit before anything
    // else touches this set's slots.
    const uint32_t* ranks = ::ranks_by_cache[this].data() + set * NUM_WAY;
    const uint32_t victim = ::find_lru_victim(ranks, NUM_WAY);
    const BLOCK& outgoing = current_set[victim];
    if (outgoing.valid) {
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

    // Decide the incoming fill's own placement here (find_victim is the only
    // hook with both the incoming ip and the ability to signal "no victim").
    const ::PCState& incoming = ::state_for(this, ip);
    const ::InsertionDecision d = ::decide_insertion(incoming, NUM_WAY);
    if (d.bypass) {
        st.ins_bypass++;
        return NUM_WAY; // sentinel: skip this fill entirely (see cache.cc)
    }
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

    // Fill (way was just vacated at find_victim time, or is a free slot from
    // a cold set -- either way its prior rank is treated as the LRU end).
    const ::PCState& incoming = ::state_for(this, ip);
    const ::InsertionDecision d = ::decide_insertion(incoming, NUM_WAY);
    // d.bypass fills never reach here: find_victim already routed them away
    // from occupying a way (see the NUM_WAY sentinel above).
    if (incoming.is_safe) st.ins_mru_safe++;
    else if (incoming.num_doa == 0) st.ins_middle++;
    else st.ins_graduated++;

    ::shift_rank(ranks, NUM_WAY, way, /*old_rank=*/0, d.rank);
}

void CACHE::replacement_final_stats()
{
    const auto& st = ::stats[this];
    const uint64_t total_ins = st.ins_middle + st.ins_graduated + st.ins_mru_safe;

    auto pct = [](uint64_t n, uint64_t d) -> double { return d ? 100.0 * n / d : 0.0; };

    printf("%s GRADUATED-LIVE STATS:\n", NAME.c_str());
    printf("  Insertions       : middle=%lu  graduated=%lu  mru(safe)=%lu  bypassed=%lu\n",
           st.ins_middle, st.ins_graduated, st.ins_mru_safe, st.ins_bypass);
    printf("  Insert mix       : middle=%.1f%%  graduated=%.1f%%  mru(safe)=%.1f%%\n",
           pct(st.ins_middle, total_ins), pct(st.ins_graduated, total_ins), pct(st.ins_mru_safe, total_ins));
    printf("  Evictions        : to-safe-list=%lu  doa-streak-continues=%lu\n",
           st.evict_to_safe, st.evict_doa_streak);
    printf("  Hits             : %lu\n", st.hits);
    printf("\n");
}
