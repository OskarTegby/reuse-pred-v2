// pacipv.cc — Prefetch-Aware Coarse-grained Insertion and Promotion Vectors.
//
// Extended from the original PACIPV (Mostofi et al., ISCA 2025) to also split
// by predicted liveness class (DoA / mostly-dead / mostly-alive), giving six
// independent IPVs selected by the cross-product of access type and liveness.
//
// An IPV is a 5-element array:
//   ipv[k]  (k = 0..3) : new RRPV assigned on a hit to a line at RRPV = k
//   ipv[4]              : RRPV assigned on insertion (fill)
//
// Default vectors
// ---------------
// Mostly-alive demand/prefetch use the paper-optimal PACIPV values.
// Dead class vectors use graduated promotion (more hits required to reach
// RRPV=0 as liveness confidence decreases).  DoA prefetch and mostly-dead
// prefetch share the same conservative vector since a prefetched block
// predicted dead should be held very weakly.
//
//   PACIPV_DOA_DEMAND         = {0, 0, 1, 2, 3}   3 hits to RRPV=0
//   PACIPV_DOA_PREFETCH       = {0, 0, 0, 2, 3}   insert maxRRPV, weak promotion
//   PACIPV_MOSTLY_DEAD_DEMAND = {0, 0, 0, 2, 3}   2 hits to RRPV=0
//   PACIPV_MOSTLY_DEAD_PREFETCH={0, 0, 0, 2, 3}   same as DoA prefetch
//   PACIPV_MOSTLY_ALIVE_DEMAND= {0, 1, 1, 0, 3}   paper default
//   PACIPV_MOSTLY_ALIVE_PREFETCH={0,1, 0, 0, 3}   paper default
//
// All six vectors are runtime-configurable via the env vars above.
// Optimal values should be found via coordinate-descent sweep.

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

// [liveness: doa=0, mostly_dead=1, mostly_alive=2][access: demand=0, prefetch=1]
ipv_t g_ipvs[3][2] = {
    /* doa         */ {{0, 0, 1, 2, maxRRPV}, {0, 0, 0, 2, maxRRPV}},
    /* mostly_dead */ {{0, 0, 0, 2, maxRRPV}, {0, 0, 0, 2, maxRRPV}},
    /* mostly_alive*/ {{0, 1, 1, 0, maxRRPV}, {0, 1, 0, 0, maxRRPV}},
};

bool g_parsed = false;

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
  g_parsed = true;
  g_ipvs[0][0] = parse_ipv("PACIPV_DOA_DEMAND",          g_ipvs[0][0]);
  g_ipvs[0][1] = parse_ipv("PACIPV_DOA_PREFETCH",        g_ipvs[0][1]);
  g_ipvs[1][0] = parse_ipv("PACIPV_MOSTLY_DEAD_DEMAND",  g_ipvs[1][0]);
  g_ipvs[1][1] = parse_ipv("PACIPV_MOSTLY_DEAD_PREFETCH",g_ipvs[1][1]);
  g_ipvs[2][0] = parse_ipv("PACIPV_MOSTLY_ALIVE_DEMAND", g_ipvs[2][0]);
  g_ipvs[2][1] = parse_ipv("PACIPV_MOSTLY_ALIVE_PREFETCH",g_ipvs[2][1]);
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

  auto& rrpv = ::rrpv_values[this][set * NUM_WAY + way];

  const int lc        = static_cast<int>(predict_liveness(full_addr, ip));
  const int is_pref   = (type == PREFETCH) ? 1 : 0;
  const auto& ipv     = ::g_ipvs[lc][is_pref];

  if (hit)
    rrpv = ipv[rrpv];
  else
    rrpv = ipv[4];
}

void CACHE::replacement_final_stats() {}
