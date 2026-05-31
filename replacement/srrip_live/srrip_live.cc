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
// classify_block_liveness() is consulted on every LLC/STLB fill or hit and
// queries the PC-indexed bHIST to classify the block based on DoA counters:
//
//   DoA fill:          RRPV = maxRRPV     (immediate eviction candidate)
//   DoA hit:           RRPV = maxRRPV-1   (partial promotion, MID_PROMOTE=0)
//                   or RRPV = 0           (full promotion,    MID_PROMOTE=1)
//
//   Mostly-alive fill: RRPV = maxRRPV-1   (standard SRRIP)
//   Mostly-alive hit:  RRPV = 0           (standard SRRIP)
//
// MID_PROMOTE applies only to DoA blocks (same semantics as before).
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

  if (NAME == "LLC") {
    switch (classify_block_liveness(full_addr, ip)) {
      case liveness_class::doa:
        rrpv = hit ? (mid_promote ? 0 : ::maxRRPV - 1) : ::maxRRPV;
        break;
      default: // mostly_alive
        rrpv = hit ? 0 : ::maxRRPV - 1;
        break;
    }
  } else {
    rrpv = hit ? 0 : ::maxRRPV - 1;
  }
}

void CACHE::replacement_final_stats() {}
