// ipv_live.cc — IPV replacement with per-liveness-class vectors.
//
// Extends IPV by maintaining three separate Insertion Priority Vectors (IPVs),
// one per predicted liveness class: DoA, mostly_dead, mostly_alive.
// The class is predicted using the PC-indexed bHIST, same as srrip_live.
//
// Default vectors use graduated promotion: the more confident we are a block
// is dead, the more hits it must earn before reaching RRPV=0.
//
//   ipv_doa         = {0, 0, 1, 2, 3}   3 hits to reach RRPV=0 (slowest ramp)
//   ipv_mostly_dead = {0, 0, 0, 2, 3}   2 hits to reach RRPV=0 (medium)
//   ipv_mostly_alive= {0, 0, 0, 0, 2}   1 hit  to reach RRPV=0 (standard SRRIP)
//
// Compared to srrip_live, DoA-mispredicted blocks can eventually earn full
// cache priority (rrpv=0) instead of being capped at maxRRPV-1.
//
// Runtime configuration:
//   IPV_DOA=0,2,2,2,3           — override DoA insertion vector
//   IPV_MOSTLY_DEAD=0,1,1,2,3   — override mostly-dead vector
//   IPV_MOSTLY_ALIVE=0,0,0,0,2  — override mostly-alive vector
//   SRRIP_LIVE_TARGET=llc|stlb|both — which caches use liveness guidance

#include <array>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <string>
#include <unordered_map>

#include "cache.h"

namespace
{
constexpr int maxRRPV = 3;

std::unordered_map<CACHE*, std::vector<int>> rrpv_values;

using ipv_t = std::array<int, 5>;

ipv_t g_ipv_doa          = {0, 0, 1, 2, maxRRPV};
ipv_t g_ipv_mostly_dead  = {0, 0, 0, 2, maxRRPV};
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

  auto& rrpv = ::rrpv_values[this][set * NUM_WAY + way];

  // Determine which cache(s) should use liveness guidance
  // Default: LLC only. Can be overridden with SRRIP_LIVE_TARGET env var
  bool use_liveness = false;
  if (const char* target = std::getenv("SRRIP_LIVE_TARGET")) {
    std::string target_str(target);
    if (target_str == "llc" && NAME == "LLC") use_liveness = true;
    else if (target_str == "stlb" && NAME == "cpu0_STLB") use_liveness = true;
    else if (target_str == "both" && (NAME == "LLC" || NAME == "cpu0_STLB")) use_liveness = true;
  } else {
    // Default: LLC only
    if (NAME == "LLC") use_liveness = true;
  }

  if (use_liveness) {
    // Use liveness-guided IPV
    const auto lc   = classify_block_liveness(full_addr, ip);
    const auto& ipv = (lc == liveness_class::doa)        ? ::g_ipv_doa :
                      (lc == liveness_class::mostly_dead) ? ::g_ipv_mostly_dead :
                                                            ::g_ipv_mostly_alive;
    if (hit)
      rrpv = ipv[rrpv];  // promotion: new RRPV = ipv[current RRPV]
    else
      rrpv = ipv[4];     // insertion: use last entry (insertion priority)
  } else {
    // Default IPV_MOSTLY_ALIVE for non-liveness-guided caches
    const auto& ipv = ::g_ipv_mostly_alive;
    if (hit)
      rrpv = ipv[rrpv];
    else
      rrpv = ipv[4];
  }
}

void CACHE::replacement_final_stats() {}
