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

// ---- Recency-at-last-hit characterization (LIVENESS_CHAR=1) ------------------
// Purely observational. For each resident block we record the recency-stack rank
// at its most recent hit (0 = LRU, N-1 = MRU) plus two sticky bits — was it ever
// hit while in the LRU half, and while in the MRU half. At eviction we tally the
// block into a last-hit-rank histogram and a 2x2 half-bit table. This feeds a
// four-state, recency-based liveness breakdown (a recency-based Figure 1):
//   never hit            -> DoA
//   hit only in one half -> the two middle states
//   hit in both halves   -> "hot"
// and the rank histogram supports finer cuts (MRU-top, soft-dead bottom region).
//
// It never influences victim selection or the last-use update below, so IPC is
// bit-identical to plain LRU; when LIVENESS_CHAR is unset it does nothing.
bool char_enabled()
{
  static const bool e = [] {
    const char* v = std::getenv("LIVENESS_CHAR");
    return v && v[0] && v[0] != '0';
  }();
  return e;
}

struct RecencyChar {
  std::vector<uint32_t> hitcnt;    // demand hits on the currently resident block
  std::vector<uint32_t> lastrank;  // recency rank (0=LRU..N-1=MRU) at its last hit
  std::vector<uint8_t>  lru_bit;   // ever hit while in the LRU half of the stack
  std::vector<uint8_t>  mru_bit;   // ever hit while in the MRU half of the stack
  // Last-hit rank histograms, split by hit count so the count-based "hot" rule
  // (V2: >=2 hits) and the rank-based rules (V1/V3) are both derivable offline.
  std::vector<uint64_t> rank_one;   // exactly one hit, by that hit's rank
  std::vector<uint64_t> rank_multi; // two or more hits, by last-hit rank
  uint64_t never_hit = 0;          // evicted without ever being hit (DoA)
  uint64_t half[2][2] = {};        // [lru_bit][mru_bit] sticky-bit tally at eviction
};
std::map<CACHE*, RecencyChar> rc;
} // namespace

void CACHE::initialize_replacement()
{
  ::last_used_cycles[this] = std::vector<uint64_t>(NUM_SET * NUM_WAY);
  if (char_enabled()) {
    auto& c = ::rc[this];
    const std::size_t n = NUM_SET * NUM_WAY;
    c.hitcnt.assign(n, 0);
    c.lastrank.assign(n, 0);
    c.lru_bit.assign(n, 0);
    c.mru_bit.assign(n, 0);
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

  // Tally the outgoing block's recency characterization before it is replaced.
  // Only real evictions (a valid resident block) count, so cold-start fills into
  // empty ways are excluded.
  if (char_enabled() && current_set[way].valid) {
    auto& c = ::rc[this];
    const std::size_t s = set * NUM_WAY + way;
    if (c.hitcnt[s] == 0) {
      c.never_hit++;
      c.half[0][0]++;
    } else {
      if (c.hitcnt[s] == 1)
        c.rank_one[c.lastrank[s]]++;
      else
        c.rank_multi[c.lastrank[s]]++;
      c.half[c.lru_bit[s]][c.mru_bit[s]]++;
    }
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
        // rank = number of ways in the set more recently used than this one,
        // 0 = LRU end, N-1 = MRU end.
        const uint64_t mine = luc[s];
        const std::size_t base = set * NUM_WAY;
        uint32_t rank = 0;
        for (uint32_t w = 0; w < NUM_WAY; ++w)
          if (luc[base + w] < mine)
            ++rank;
        c.lastrank[s] = rank;
        if (rank < NUM_WAY / 2)
          c.lru_bit[s] = 1;
        else
          c.mru_bit[s] = 1;
        ++c.hitcnt[s];
      } else {
        // Fill: reset the incoming block's characterization state.
        c.hitcnt[s] = 0;
        c.lastrank[s] = 0;
        c.lru_bit[s] = 0;
        c.mru_bit[s] = 0;
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
  printf("%s RECENCY_LASTHIT BEGIN\n", NAME.c_str());
  printf("  n_ways=%u never_hit=%lu\n", NUM_WAY, c.never_hit);
  printf("  half L0M0=%lu L0M1=%lu L1M0=%lu L1M1=%lu\n", c.half[0][0], c.half[0][1], c.half[1][0], c.half[1][1]);
  printf("  lasthit_rank_hist_one");
  for (uint32_t r = 0; r < NUM_WAY; ++r)
    printf(" r%u=%lu", r, c.rank_one[r]);
  printf("\n  lasthit_rank_hist_multi");
  for (uint32_t r = 0; r < NUM_WAY; ++r)
    printf(" r%u=%lu", r, c.rank_multi[r]);
  printf("\n");
  printf("%s RECENCY_LASTHIT END\n", NAME.c_str());
}
