// pacipv.cc — Prefetch-Aware Coarse-grained Insertion and Promotion Vectors.
//
// PACIPV (Mostofi et al., ISCA 2025) maintains two IPVs — one for demand
// accesses and one for prefetch accesses — so that prefetched blocks can be
// inserted and promoted more conservatively than demand blocks, preventing
// prefetch pollution from displacing live demand lines.
//
// An IPV is a 5-element array:
//   ipv[k]  (k = 0..3) : new RRPV assigned on a hit to a line at RRPV = k
//   ipv[4]              : RRPV assigned on insertion (fill)
//
// Default vectors (optimal for instruction-heavy workloads per the paper):
//   demand   = {0, 1, 1, 0, 3}
//   prefetch = {0, 1, 0, 0, 3}
//
// Runtime configuration
// ---------------------
// Override either vector with comma-separated 5-integer env vars:
//   PACIPV_DEMAND=0,1,1,0,3
//   PACIPV_PREFETCH=0,1,0,0,3

#include <array>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <unordered_map>

#include "cache.h"

namespace
{
constexpr int maxRRPV = 3;

std::unordered_map<CACHE*, std::vector<int>> rrpv_values;

using ipv_t = std::array<int, 5>;

ipv_t g_demand   = {0, 1, 1, 0, maxRRPV};
ipv_t g_prefetch = {0, 1, 0, 0, maxRRPV};
bool  g_parsed   = false;

ipv_t parse_ipv(const char* var, ipv_t dflt)
{
  const char* s = std::getenv(var);
  if (!s)
    return dflt;

  char buf[64];
  std::strncpy(buf, s, sizeof(buf) - 1);
  buf[sizeof(buf) - 1] = '\0';

  ipv_t v = dflt;
  char* tok = std::strtok(buf, ",");
  for (int i = 0; i < 5 && tok != nullptr; ++i, tok = std::strtok(nullptr, ","))
    v[i] = std::atoi(tok);
  return v;
}

void ensure_parsed()
{
  if (g_parsed)
    return;
  g_parsed   = true;
  g_demand   = parse_ipv("PACIPV_DEMAND",   g_demand);
  g_prefetch = parse_ipv("PACIPV_PREFETCH", g_prefetch);
}
} // namespace

void CACHE::initialize_replacement()
{
  ::ensure_parsed();
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

  auto& rrpv       = ::rrpv_values[this][set * NUM_WAY + way];
  const auto& ipv  = (type == PREFETCH) ? ::g_prefetch : ::g_demand;

  if (hit)
    rrpv = ipv[rrpv];
  else
    rrpv = ipv[4];
}

void CACHE::replacement_final_stats() {}
