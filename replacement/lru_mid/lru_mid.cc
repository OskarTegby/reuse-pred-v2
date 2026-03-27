// lru_mid — LRU with mid-point insertion for LLC and STLB.
//
// Motivation
// ----------
// Blocks and pages that have been observed as DoA or mostly-dead in the past
// are poor candidates for occupying the MRU end of the recency stack: they
// are unlikely to be reused before newer entries.  Giving them a mid-point
// position instead makes room for entries that are more likely to survive.
//
// Policy rules
// ------------
// For every fill or hit on the LLC or STLB, needs_mid_insertion() is
// consulted.  It returns true when the block's/page's history entry shows a
// non-zero doa or mostly_dead counter — meaning the most recent eviction of
// that block/page was DoA or mostly-dead (see update_eviction_counters in
// cache.cc).
//
//   Mid-insertion fill:    timestamp = current-set median  (not MRU)
//   Mid-insertion hit:     timestamp = current-set median  (refresh to midpoint, not MRU)
//   Normal (or non-LLC/STLB): timestamp = current_cycle    (standard LRU)
//
// "Median" is computed as the (NUM_WAY/2)-th smallest last_used timestamp in
// the set, evaluated at the time of the fill or hit.  This gives a stable
// reference that degrades gracefully as ways are accessed.
//
// For all caches other than the LLC and STLB the policy is identical to
// plain LRU.  There is no need to configure those caches separately, but the
// config does assign lru_mid only to the LLC and STLB for clarity.

#include <algorithm>
#include <map>
#include <vector>

#include "cache.h"

namespace
{
std::map<CACHE*, std::vector<uint64_t>> last_used_cycles;
}

void CACHE::initialize_replacement()
{
  ::last_used_cycles[this] = std::vector<uint64_t>(NUM_SET * NUM_WAY, 0);
}

uint32_t CACHE::find_victim(uint32_t triggering_cpu, uint64_t instr_id, uint32_t set,
                             const BLOCK* current_set, uint64_t ip, uint64_t full_addr,
                             uint32_t type)
{
  // Evict the way whose timestamp is furthest in the past (standard LRU rule).
  // Mid-insertion changes WHERE new blocks sit in the recency stack, but does
  // not change which block is selected as the victim.
  auto begin = std::next(::last_used_cycles[this].begin(), set * NUM_WAY);
  auto end   = std::next(begin, NUM_WAY);
  auto victim = std::min_element(begin, end);
  assert(begin <= victim && victim < end);
  return static_cast<uint32_t>(std::distance(begin, victim));
}

void CACHE::update_replacement_state(uint32_t triggering_cpu, uint32_t set, uint32_t way,
                                      uint64_t full_addr, uint64_t ip, uint64_t victim_addr,
                                      uint32_t type, uint8_t hit)
{
  // Writeback hits do not change recency (same as plain LRU).
  if (hit && type == WRITE)
    return;

  auto& way_cycle = ::last_used_cycles[this].at(set * NUM_WAY + way);

  if ((NAME == "cpu0_STLB" || NAME == "LLC") && needs_mid_insertion(full_addr, ip)) {
    // ── Mid-point insertion / refresh ────────────────────────────────────────
    // Compute the (NUM_WAY/2)-th smallest timestamp in this set.  nth_element
    // is O(n) and n == NUM_WAY (≤ 16 in the default config), so this is cheap.
    const auto begin = std::next(::last_used_cycles[this].cbegin(), set * NUM_WAY);
    const auto end   = std::next(begin, NUM_WAY);
    std::vector<uint64_t> tmp(begin, end);
    std::nth_element(tmp.begin(), tmp.begin() + NUM_WAY / 2, tmp.end());
    const uint64_t mid = tmp[NUM_WAY / 2];

    // Both fill and hit set the timestamp to the current median.
    // A hit refreshes the block to the midpoint, not to MRU.
    way_cycle = mid;
  } else {
    // ── Normal LRU: promote/insert at MRU ────────────────────────────────────
    way_cycle = current_cycle;
  }
}

void CACHE::replacement_final_stats() {}
