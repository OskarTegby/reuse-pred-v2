// srrip_live — SRRIP with liveness-informed insertion and promotion.
//
// Motivation
// ----------
// Plain SRRIP inserts every block at RRPV = maxRRPV-1, giving it one
// increment of "grace" before it becomes an eviction candidate.  Blocks that
// have historically been DoA or mostly-dead are unlikely to earn a hit before
// that grace expires, yet they still displace potentially live entries.
// Inserting them at maxRRPV instead makes them immediate eviction candidates
// and reserves the recency budget for entries more likely to survive.
//
// Policy rules
// ------------
// needs_mid_insertion() is consulted on every LLC/STLB fill or hit (same
// predicate used by lru_mid).  It returns true when the block's history shows
// doa or mostly_dead >= mid_thd evictions.
//
//   Dead-predicted fill:   RRPV = maxRRPV     (immediate eviction candidate)
//   Dead-predicted hit:    RRPV = maxRRPV-1   (partial promotion, MID_PROMOTE=0)
//                       or RRPV = 0           (full promotion,    MID_PROMOTE=1)
//   Normal fill:           RRPV = maxRRPV-1   (standard SRRIP)
//   Normal hit:            RRPV = 0           (standard SRRIP)
//
// MID_PROMOTE=0 (default) caps the promotion of dead-predicted blocks on a
// hit to maxRRPV-1 rather than 0, keeping them near the eviction frontier
// even after proving a single hit.  MID_PROMOTE=1 gives them full credit.
//
// find_victim() and the aging loop are identical to plain SRRIP.
// For caches other than the LLC and STLB the policy degrades to plain SRRIP.

#include <unordered_map>

#include "cache.h"

namespace
{
constexpr int maxRRPV = 3;
std::unordered_map<CACHE*, std::vector<int>> rrpv_values;
} // namespace

void CACHE::initialize_replacement()
{
  ::rrpv_values[this] = std::vector<int>(NUM_SET * NUM_WAY, ::maxRRPV);
}

uint32_t CACHE::find_victim(uint32_t triggering_cpu, uint64_t instr_id, uint32_t set,
                             const BLOCK* current_set, uint64_t ip, uint64_t full_addr,
                             uint32_t type)
{
  auto begin  = std::next(std::begin(::rrpv_values[this]), set * NUM_WAY);
  auto end    = std::next(begin, NUM_WAY);
  auto victim = std::find(begin, end, ::maxRRPV);
  while (victim == end) {
    for (auto it = begin; it != end; ++it)
      ++(*it);
    victim = std::find(begin, end, ::maxRRPV);
  }

  assert(begin <= victim);
  assert(victim < end);
  return static_cast<uint32_t>(std::distance(begin, victim));
}

void CACHE::update_replacement_state(uint32_t triggering_cpu, uint32_t set, uint32_t way,
                                      uint64_t full_addr, uint64_t ip, uint64_t victim_addr,
                                      uint32_t type, uint8_t hit)
{
  if (hit && type == WRITE)
    return;

  auto& rrpv = ::rrpv_values[this][set * NUM_WAY + way];

  if ((NAME == "cpu0_STLB" || NAME == "LLC") && needs_mid_insertion(full_addr, ip)) {
    if (hit)
      rrpv = mid_promote_on_hit ? 0 : ::maxRRPV - 1;
    else
      rrpv = ::maxRRPV;
  } else {
    rrpv = hit ? 0 : ::maxRRPV - 1;
  }
}

void CACHE::replacement_final_stats() {}
