// ipv.cc — Insertion/Promotion Vector replacement (Jimenez, MICRO 2013).
//
// Each set is a strict permutation of positions 0..k-1 (0 = most protected,
// k-1 = next victim). V[p] = promotion target on a hit at position p; V[k] =
// insertion position. Both hit and miss are the same move_to() shift.
//
// Default vector: Jimenez's WI-GIPPR (paper Sec 5.3) for k=16, scaled down
// (position-resampled, value-rescaled, clamped) for k=12 to match this
// project's Redwood Cove LLC. Any other k falls back to the trivial vector,
// which is exactly LRU (insert at the tail, promote straight to the head).
//
// No liveness guidance here — this is the non-liveness IPV baseline, same
// role replacement/lru/lru.cc plays for champsim_lru. See
// replacement/ipv_live/ipv_live.cc for the liveness-guided variant, which
// shares this same permutation mechanism.
//
// Runtime configuration
// ----------------------
// IPV=<k+1 comma/colon-separated ints> overrides the vector.

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>

#include "cache.h"

namespace
{

#include "../ipv_common.h"

std::unordered_map<CACHE*, std::vector<int>>      g_ipv;
std::unordered_map<CACHE*, std::vector<uint16_t>> g_order;  // set*NUM_WAY + position -> way
std::unordered_map<CACHE*, std::vector<uint16_t>> g_rank;   // set*NUM_WAY + way -> position

} // namespace

void CACHE::initialize_replacement()
{
  const std::size_t k = NUM_WAY;
  ::g_ipv[this] = ::parse_ipv_env("IPV", k, ::default_ipv(k));

  auto& order = ::g_order[this];
  auto& rank  = ::g_rank[this];
  order.assign(static_cast<std::size_t>(NUM_SET) * NUM_WAY, 0);
  rank.assign(static_cast<std::size_t>(NUM_SET) * NUM_WAY, 0);
  for (std::size_t s = 0; s < NUM_SET; ++s) {
    for (std::size_t w = 0; w < NUM_WAY; ++w) {
      order[s * NUM_WAY + w] = static_cast<uint16_t>(w);
      rank [s * NUM_WAY + w] = static_cast<uint16_t>(w);
    }
  }
}

uint32_t CACHE::find_victim(uint32_t triggering_cpu, uint64_t instr_id, uint32_t set,
                             const BLOCK* current_set, uint64_t ip, uint64_t full_addr,
                             uint32_t type)
{
  const auto& order = ::g_order[this];
  return order[static_cast<std::size_t>(set) * NUM_WAY + (NUM_WAY - 1)];
}

void CACHE::update_replacement_state(uint32_t triggering_cpu, uint32_t set, uint32_t way,
                                      uint64_t full_addr, uint64_t ip, uint64_t victim_addr,
                                      uint32_t type, uint8_t hit)
{
  const std::size_t base = static_cast<std::size_t>(set) * NUM_WAY;
  uint16_t* order = ::g_order[this].data() + base;
  uint16_t* rank  = ::g_rank[this].data() + base;
  const auto& ipv = ::g_ipv[this];

  if (hit) {
    if (type == WRITE) return;  // store hits don't trigger promotion
    move_to(order, rank, rank[way], ipv[rank[way]]);
  } else {
    // find_victim() guarantees the evicted way sits at the tail position.
    move_to(order, rank, static_cast<int>(NUM_WAY) - 1, ipv[NUM_WAY]);
  }
}

void CACHE::replacement_final_stats() {}
