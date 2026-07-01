#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <vector>

#include "cache.h"

namespace
{
std::map<CACHE*, std::vector<uint64_t>> last_used_cycles;

// ---- Recency-based liveness classification (LIVENESS_CHAR=1) -----------------
// Each resident block carries a 2-bit state, set online as it is accessed —
// exactly the mechanism a real implementation would use (no timestamps, no
// offline post-processing). On a demand hit we read the block's recency-stack
// rank (0 = LRU .. N-1 = MRU) and update its state per the selected version:
//
//   state: 0=dead  1=mid_lru  2=mid_mru  3=live      (reset to 0 on fill)
//   V1  st = (rank==N-1) ? 3 : (rank>=N/2) ? 2 : 1
//   V2  st = (st==0) ? (rank<N/2 ? 1 : 2) : 3           // 2nd+ hit -> hot
//   V3  st = (rank<N/4) ? 0 : (rank<N/2 ? 1 : (rank<N-1 ? 2 : 3))
//
// RECENCY_VERSION selects the version (default 2). At eviction the block's final
// state is tallied. Purely observational — never influences victim choice or the
// last-use update, so IPC is bit-identical to plain LRU.
//
// The raw last-hit-rank histogram is also recorded, but ONLY as a test oracle:
// re-deriving the selected version from it offline must reproduce the online
// state counts (a check of the state machine). It is dropped in the guidance build.
bool char_enabled()
{
  static const bool e = [] {
    const char* v = std::getenv("LIVENESS_CHAR");
    return v && v[0] && v[0] != '0';
  }();
  return e;
}

int recency_version()
{
  static const int v = [] {
    const char* e = std::getenv("RECENCY_VERSION");
    const int x = (e && *e) ? std::atoi(e) : 2;
    return (x == 1 || x == 2 || x == 3) ? x : 2;
  }();
  return v;
}

struct RecencyChar {
  // The 2-bit state lives on each block (BLOCK::eviction_state); here we only
  // tally the final state at eviction.
  uint64_t st_count[4] = {};       // eviction tally by final state (the classification)
  // Test oracle: raw last-hit data to re-derive the selected version offline.
  std::vector<uint32_t> hitcnt;    // demand hits on the currently resident block
  std::vector<uint32_t> lastrank;  // recency rank at its last hit
  std::vector<uint64_t> rank_one;   // exactly one hit, by that hit's rank
  std::vector<uint64_t> rank_multi; // two or more hits, by last-hit rank
  uint64_t never_hit = 0;          // evicted without ever being hit
};
std::map<CACHE*, RecencyChar> rc;

// The four liveness states, ordered dead -> live (the 2-bit value on each block).
enum RState : uint8_t { DEAD = 0, MID_LRU = 1, MID_MRU = 2, LIVE = 3 };

// Compute a block's new state on a demand hit, given its current state `cur` and
// the recency rank `r` of this hit (0 = LRU end .. n-1 = MRU end) in an n-way set.
// A block is reset to DEAD on fill (elsewhere); this only runs on hits.
uint8_t next_state(uint8_t cur, uint32_t r, uint32_t n)
{
  // Where in the recency stack did this hit land?
  const bool at_mru_top  = (r == n - 1);   // still the most-recently-used block
  const bool in_mru_half = (r >= n / 2);   // nearer the MRU end than the LRU end
  const bool deep_in_lru = (r < n / 4);    // deep in the LRU quarter, nearly evicted

  switch (recency_version()) {
    case 1:
      // V1: classify by where THIS hit landed; each hit overwrites, so the final
      // state reflects the last hit. Top of stack = live, else by half.
      if (at_mru_top)  return LIVE;
      if (in_mru_half) return MID_MRU;
      return MID_LRU;

    case 2:
      // V2: the first hit picks a middle state by half; ANY later hit (the block
      // is no longer DEAD) promotes it to live ("hot"). Rank is ignored after the
      // first hit -- this is the only version that reads `cur`.
      if (cur != DEAD) return LIVE;
      return in_mru_half ? MID_MRU : MID_LRU;

    case 3:
      // V3: like V1, but a hit deep in the LRU quarter is treated as still-dead
      // (too close to eviction to signal liveness) -- a softer DEAD than V1/V2.
      if (deep_in_lru) return DEAD;
      if (at_mru_top)  return LIVE;
      if (in_mru_half) return MID_MRU;
      return MID_LRU;
  }
  return DEAD;  // unreachable: recency_version() is clamped to {1,2,3}
}
} // namespace

void CACHE::initialize_replacement()
{
  ::last_used_cycles[this] = std::vector<uint64_t>(NUM_SET * NUM_WAY);
  if (char_enabled()) {
    auto& c = ::rc[this];
    const std::size_t n = NUM_SET * NUM_WAY;
    c.hitcnt.assign(n, 0);
    c.lastrank.assign(n, 0);
    c.rank_one.assign(NUM_WAY, 0);
    c.rank_multi.assign(NUM_WAY, 0);
  }
}

uint32_t CACHE::find_victim(uint32_t triggering_cpu, uint64_t instr_id, uint32_t set, const BLOCK* current_set, uint64_t ip, uint64_t full_addr, uint32_t type)
{
  auto begin = std::next(std::begin(::last_used_cycles[this]), set * NUM_WAY);
  auto end = std::next(begin, NUM_WAY);

  // Find the way whose last use cycle is most distant
  auto victim = std::min_element(begin, end);
  assert(begin <= victim);
  assert(victim < end);
  const auto way = static_cast<uint32_t>(std::distance(begin, victim)); // cast protected by prior asserts

  // Tally the outgoing block before it is replaced. Only real evictions (a valid
  // resident block) count, so cold-start fills into empty ways are excluded.
  if (char_enabled() && current_set[way].valid) {
    auto& c = ::rc[this];
    const std::size_t s = set * NUM_WAY + way;
    c.st_count[current_set[way].eviction_state]++;   // the block's own 2-bit state
    if (c.hitcnt[s] == 0)                    // oracle (version-independent)
      c.never_hit++;
    else if (c.hitcnt[s] == 1)
      c.rank_one[c.lastrank[s]]++;
    else
      c.rank_multi[c.lastrank[s]]++;
  }
  return way;
}

void CACHE::update_replacement_state(uint32_t triggering_cpu, uint32_t set, uint32_t way, uint64_t full_addr, uint64_t ip, uint64_t victim_addr, uint32_t type,
                                     uint8_t hit)
{
  const std::size_t s = set * NUM_WAY + way;

  if (!hit || type != WRITE) { // Skip this for writeback hits
    if (char_enabled()) {
      auto& c = ::rc[this];
      const auto& luc = ::last_used_cycles[this];
      if (hit) {
        // Recency rank at this (demand) hit, read BEFORE the last-use bump below:
        // rank = number of ways more recently used than this one (0=LRU..N-1=MRU).
        const uint64_t mine = luc[s];
        const std::size_t base = set * NUM_WAY;
        uint32_t rank = 0;
        for (uint32_t w = 0; w < NUM_WAY; ++w)
          if (luc[base + w] < mine)
            ++rank;
        // The mechanism: update this block's own 2-bit state from its recency rank.
        block[s].eviction_state = next_state(block[s].eviction_state, rank, NUM_WAY);
        c.lastrank[s] = rank;                                // oracle
        ++c.hitcnt[s];
      } else {
        // Fill: reset the incoming block's state and oracle fields.
        block[s].eviction_state = 0;
        c.hitcnt[s] = 0;
        c.lastrank[s] = 0;
      }
    }
    // Mark the way as being used on the current cycle
    ::last_used_cycles[this].at(s) = current_cycle;
  }
}

void CACHE::replacement_final_stats()
{
  if (!char_enabled())
    return;
  auto it = ::rc.find(this);
  if (it == ::rc.end())
    return;
  const auto& c = it->second;
  printf("%s RECENCY_STATE v=%d dead=%lu mid_lru=%lu mid_mru=%lu live=%lu\n", NAME.c_str(), recency_version(), c.st_count[0], c.st_count[1], c.st_count[2],
         c.st_count[3]);
  // Test oracle: raw last-hit histogram (re-derive the version offline to check).
  printf("%s RECENCY_LASTHIT BEGIN\n", NAME.c_str());
  printf("  n_ways=%u never_hit=%lu\n", NUM_WAY, c.never_hit);
  printf("  lasthit_rank_hist_one");
  for (uint32_t r = 0; r < NUM_WAY; ++r)
    printf(" r%u=%lu", r, c.rank_one[r]);
  printf("\n  lasthit_rank_hist_multi");
  for (uint32_t r = 0; r < NUM_WAY; ++r)
    printf(" r%u=%lu", r, c.rank_multi[r]);
  printf("\n");
  printf("%s RECENCY_LASTHIT END\n", NAME.c_str());
}
