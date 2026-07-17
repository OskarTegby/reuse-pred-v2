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

const std::vector<int> kDefaultIpv16 = {
    0, 0, 2, 8, 4, 1, 4, 1, 8, 0, 14, 8, 12, 13, 14, 9, 5
};

// WI-GIPPR-16 resampled to k=12: position p_old = round(p * 15/11) for each
// new position p in 0..11, value rescaled by 12/16 and clamped to [0, 11].
const std::vector<int> kDefaultIpv12 = {
    0, 0, 6, 3, 1, 1, 6, 10, 6, 9, 10, 7, 4
};

std::vector<int> trivial_ipv(std::size_t k)
{
  std::vector<int> v(k + 1, 0);
  v[k] = static_cast<int>(k) - 1;
  return v;
}

std::vector<int> default_ipv(std::size_t k)
{
  if (k == 16) return kDefaultIpv16;
  if (k == 12) return kDefaultIpv12;
  return trivial_ipv(k);
}

// Parses `var` for a k-way cache; falls back to `dflt` if unset, malformed,
// wrong length, or containing an out-of-range position.
std::vector<int> parse_ipv_env(const char* var, std::size_t k, const std::vector<int>& dflt)
{
  const char* s = std::getenv(var);
  if (!s || !*s) return dflt;
  std::string buf(s);
  std::vector<int> v;
  v.reserve(k + 1);
  char* tok = std::strtok(buf.data(), ",: ");
  while (tok) {
    v.push_back(std::atoi(tok));
    tok = std::strtok(nullptr, ",: ");
  }
  if (v.size() != k + 1) return dflt;
  for (int p : v) if (p < 0 || p >= static_cast<int>(k)) return dflt;
  return v;
}

// Moves the block at position `from` to position `to`, shifting the blocks
// in between by one to close the gap. `order[p]` = way at position p;
// `rank[w]` = position of way w. Both are kept in sync.
void move_to(uint16_t* order, uint16_t* rank, int from, int to)
{
  if (from == to) return;
  const uint16_t way = order[from];
  if (to < from) {
    for (int p = from; p > to; --p) { order[p] = order[p - 1]; rank[order[p]] = static_cast<uint16_t>(p); }
  } else {
    for (int p = from; p < to; ++p) { order[p] = order[p + 1]; rank[order[p]] = static_cast<uint16_t>(p); }
  }
  order[to] = way;
  rank[way] = static_cast<uint16_t>(to);
}

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
