// ipv_live.cc — IPV replacement with per-liveness-class vectors.
//
// Extends ipv.cc by maintaining three separate IPVs, one per predicted
// liveness class of the incoming block (DoA, mostly-dead, mostly-alive).
// The class is predicted using the same history tables and mid_thd threshold
// that drive needs_mid_insertion() / lru_mid / srrip_live.
//
// Default vectors (qualified guesses grounded in srrip_live behaviour):
//
//   ipv_doa         = {0, 2, 2, 2, 3}   insert at maxRRPV; cap hits at maxRRPV-1
//   ipv_mostly_dead = {0, 1, 1, 2, 3}   insert at maxRRPV; more generous on hits
//   ipv_mostly_alive= {0, 0, 0, 0, 2}   standard SRRIP (insert at maxRRPV-1, hit→0)
//
// The DoA default reproduces the dead-predicted path of srrip_live (MID_PROMOTE=0),
// so this policy is a strict generalisation of srrip_live.
//
// Runtime configuration
// ---------------------
// Override any vector with a comma-separated 5-integer env var:
//   IPV_DOA=0,2,2,2,3
//   IPV_MOSTLY_DEAD=0,1,1,2,3
//   IPV_MOSTLY_ALIVE=0,0,0,0,2
//
// For caches other than LLC and STLB the mostly_alive vector is always used
// (no liveness history exists for other caches).

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

ipv_t g_ipv_doa          = {0, 2, 2, 2, maxRRPV};
ipv_t g_ipv_mostly_dead  = {0, 1, 1, 2, maxRRPV};
ipv_t g_ipv_mostly_alive = {0, 0, 0, 0, maxRRPV - 1};
bool  g_parsed = false;

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
  g_ipv_doa          = parse_ipv("IPV_DOA",          g_ipv_doa);
  g_ipv_mostly_dead  = parse_ipv("IPV_MOSTLY_DEAD",  g_ipv_mostly_dead);
  g_ipv_mostly_alive = parse_ipv("IPV_MOSTLY_ALIVE", g_ipv_mostly_alive);
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

  auto& rrpv      = ::rrpv_values[this][set * NUM_WAY + way];
  const auto lc   = predict_liveness(full_addr, ip);
  const auto& ipv = (lc == liveness_class::doa)        ? ::g_ipv_doa :
                    (lc == liveness_class::mostly_dead) ? ::g_ipv_mostly_dead :
                                                          ::g_ipv_mostly_alive;
  if (hit)
    rrpv = ipv[rrpv];  // promotion: new RRPV = ipv[current RRPV]
  else
    rrpv = ipv[4];     // insertion
}

void CACHE::replacement_final_stats() {}
