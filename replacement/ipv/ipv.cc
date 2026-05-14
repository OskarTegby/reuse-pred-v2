// ipv.cc — RRIP with configurable Insertion and Promotion Vectors.
//
// An IPV (Insertion and Promotion Vector) is a 5-element integer array that
// fully parameterises a RRIP-family replacement policy:
//
//   ipv[k]  (k = 0..3) : new RRPV assigned when hitting a line at RRPV = k
//   ipv[4]              : RRPV assigned on a fill (insertion)
//
// Examples with maxRRPV = 3:
//   {0, 0, 0, 0, 2}  — SRRIP:  hit always promotes to 0, insert at maxRRPV-1
//   {0, 0, 0, 0, 3}  — BRRIP:  hit always promotes to 0, insert at maxRRPV
//
// find_victim() is identical to plain SRRIP: evict the first maxRRPV line,
// aging all lines by +1 until one is found.
//
// Runtime configuration
// ---------------------
// Set IPV to five comma-separated integers before running the binary:
//   IPV=0,0,0,0,2   → SRRIP-equivalent (default)
//   IPV=0,1,1,0,3   → demand IPV from PACIPV (Mostofi et al., ISCA 2025)

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

// Default: SRRIP-equivalent — hit→0, insert at maxRRPV-1.
std::array<int, 5> g_ipv = {0, 0, 0, 0, maxRRPV - 1};
bool               g_ipv_parsed = false;

void ensure_ipv_parsed()
{
  if (g_ipv_parsed)
    return;
  g_ipv_parsed = true;

  const char* s = std::getenv("IPV");
  if (!s)
    return;

  char buf[64];
  std::strncpy(buf, s, sizeof(buf) - 1);
  buf[sizeof(buf) - 1] = '\0';

  std::array<int, 5> v = g_ipv;
  char* tok = std::strtok(buf, ",");
  for (int i = 0; i < 5 && tok != nullptr; ++i, tok = std::strtok(nullptr, ","))
    v[i] = std::atoi(tok);
  g_ipv = v;
}
} // namespace

void CACHE::initialize_replacement()
{
  ::ensure_ipv_parsed();
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

  if (hit)
    rrpv = ::g_ipv[rrpv];  // promotion: look up new RRPV by current RRPV
  else
    rrpv = ::g_ipv[4];     // insertion
}

void CACHE::replacement_final_stats() {}
