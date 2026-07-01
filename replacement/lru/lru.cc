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
  // The mechanism: one 2-bit state per resident block, updated online.
  std::vector<uint8_t> state;      // 0=dead 1=mid_lru 2=mid_mru 3=live
  uint64_t st_count[4] = {};       // eviction tally by final state (the classification)
  // Test oracle: raw last-hit data to re-derive the selected version offline.
  std::vector<uint32_t> hitcnt;    // demand hits on the currently resident block
  std::vector<uint32_t> lastrank;  // recency rank at its last hit
  std::vector<uint64_t> rank_one;   // exactly one hit, by that hit's rank
  std::vector<uint64_t> rank_multi; // two or more hits, by last-hit rank
  uint64_t never_hit = 0;          // evicted without ever being hit
};
std::map<CACHE*, RecencyChar> rc;

// Update a block's 2-bit state on a demand hit at recency rank r (out of n ways).
uint8_t next_state(uint8_t cur, uint32_t r, uint32_t n)
{
  switch (recency_version()) {
    case 1:  return (r == n - 1) ? 3 : (r >= n / 2) ? 2 : 1;
    case 3:  return (r < n / 4) ? 0 : (r < n / 2) ? 1 : (r < n - 1) ? 2 : 3;
    default: return (cur == 0) ? (r < n / 2 ? 1 : 2) : 3; // V2
  }
}
} // namespace

void CACHE::initialize_replacement()
{
  ::last_used_cycles[this] = std::vector<uint64_t>(NUM_SET * NUM_WAY);
  if (char_enabled()) {
    auto& c = ::rc[this];
    const std::size_t n = NUM_SET * NUM_WAY;
    c.state.assign(n, 0);
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
    c.st_count[c.state[s]]++;               // the mechanism's classification
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
        c.state[s] = next_state(c.state[s], rank, NUM_WAY);  // the mechanism
        c.lastrank[s] = rank;                                // oracle
        ++c.hitcnt[s];
      } else {
        // Fill: reset the incoming block's state and oracle fields.
        c.state[s] = 0;
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
