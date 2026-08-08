// ipv_live.cc — IPV replacement with per-liveness-class vectors.
//
// Three IPVs: ipv_doa, ipv_mostly_dead, ipv_mostly_alive.
// On miss: rrpv = ipv[4]       (insertion priority)
// On hit:  rrpv = ipv[current] (promotion step)
//
// Statistics printed in replacement_final_stats()
// ------------------------------------------------
// Activation rate      — fraction of insertions where liveness selected the IPV.
// Insert class mix     — DoA / mostly-dead / mostly-alive / unguided breakdown.
// Hit rate per class   — discriminability metric. DoA and mostly-dead entries
//                        should have much lower hit rates than mostly-alive.
// RRPV at eviction     — histogram per class showing how entries leave the cache.
//   DoA / mostly-dead: ideally evicted at maxRRPV (low-priority insertion, no
//                      promotion earned) — shows entries did not waste residency.
//   Mostly-alive:      ideally evicted at low RRPV (promoted by hits before
//                      eviction) — shows protected entries got the hits they
//                      were predicted to earn.
// Aging loops          — find_victim scan passes needed; fewer = less pressure
//                        from protected entries crowding out eviction candidates.
//
// Runtime overrides:
//   IPV_DOA=0,0,1,2,3   IPV_MOSTLY_DEAD=0,0,0,2,3   IPV_MOSTLY_ALIVE=0,0,0,0,2
//   SRRIP_LIVE_TARGET=llc|stlb|both

#include <array>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>

#include "cache.h"

namespace
{
constexpr int maxRRPV = 3;

std::unordered_map<CACHE*, std::vector<int>>    rrpv_values;
// 0=unguided  1=doa  2=mostly_dead  3=mostly_alive
std::unordered_map<CACHE*, std::vector<int8_t>> slot_class;

struct Stats {
    uint64_t ins_unguided = 0, ins_doa = 0, ins_dead = 0, ins_alive = 0;
    uint64_t hit_unguided = 0, hit_doa = 0, hit_dead = 0, hit_alive = 0;
    std::array<uint64_t, 4> evict_rrpv_doa     = {};
    std::array<uint64_t, 4> evict_rrpv_dead    = {};
    std::array<uint64_t, 4> evict_rrpv_alive   = {};
    std::array<uint64_t, 4> evict_rrpv_unguided= {};
    uint64_t aging_loops = 0;
};
std::unordered_map<CACHE*, Stats> stats;

using ipv_t = std::array<int, 5>;
ipv_t g_ipv_doa          = {0, 0, 1, 2, maxRRPV};
ipv_t g_ipv_mostly_dead  = {0, 0, 0, 2, maxRRPV};
ipv_t g_ipv_mostly_alive = {0, 0, 0, 0, maxRRPV - 1};
bool  g_parsed = false;

ipv_t parse_ipv(const char* var, ipv_t dflt)
{
  const char* s = std::getenv(var);
  if (!s) return dflt;
  char buf[64];
  std::strncpy(buf, s, sizeof(buf) - 1);
  buf[sizeof(buf) - 1] = '\0';
  ipv_t v = dflt;
  char* tok = std::strtok(buf, ",");
  for (int i = 0; i < 5 && tok; ++i, tok = std::strtok(nullptr, ","))
    v[i] = std::atoi(tok);
  return v;
}

void ensure_parsed()
{
  if (g_parsed) return;
  g_parsed = true;
  g_ipv_doa         = parse_ipv("IPV_DOA",          g_ipv_doa);
  g_ipv_mostly_dead = parse_ipv("IPV_MOSTLY_DEAD",  g_ipv_mostly_dead);
  g_ipv_mostly_alive= parse_ipv("IPV_MOSTLY_ALIVE", g_ipv_mostly_alive);
}

} // namespace

void CACHE::initialize_replacement()
{
  ::ensure_parsed();
  const std::size_t n = NUM_SET * NUM_WAY;
  ::rrpv_values[this] = std::vector<int>   (n, ::maxRRPV);
  ::slot_class[this]  = std::vector<int8_t>(n, 0);
  ::stats[this]       = Stats{};
}

uint32_t CACHE::find_victim(uint32_t triggering_cpu, uint64_t instr_id, uint32_t set,
                             const BLOCK* current_set, uint64_t ip, uint64_t full_addr,
                             uint32_t type)
{
  auto begin  = std::next(std::begin(::rrpv_values[this]), set * NUM_WAY);
  auto end    = std::next(begin, NUM_WAY);
  auto victim = std::find(begin, end, ::maxRRPV);
  while (victim == end) {
    ++::stats[this].aging_loops;
    for (auto it = begin; it != end; ++it)
      ++(*it);
    victim = std::find(begin, end, ::maxRRPV);
  }

  assert(begin <= victim);
  assert(victim < end);

  const uint32_t   way  = static_cast<uint32_t>(std::distance(begin, victim));
  const std::size_t idx = set * NUM_WAY + way;
  const int8_t cls  = ::slot_class[this][idx];
  const int    rrpv = ::rrpv_values[this][idx];
  auto& st = ::stats[this];

  switch (cls) {
    case 1: st.evict_rrpv_doa    [rrpv]++; break;
    case 2: st.evict_rrpv_dead   [rrpv]++; break;
    case 3: st.evict_rrpv_alive  [rrpv]++; break;
    default:st.evict_rrpv_unguided[rrpv]++; break;
  }

  return way;
}

void CACHE::update_replacement_state(uint32_t triggering_cpu, uint32_t set, uint32_t way,
                                      uint64_t full_addr, uint64_t ip, uint64_t victim_addr,
                                      uint32_t type, uint8_t hit)
{
  if (hit && type == WRITE)
    return;

  const std::size_t idx = set * NUM_WAY + way;
  auto& rrpv = ::rrpv_values[this][idx];
  auto& cls  = ::slot_class[this][idx];
  auto& st   = ::stats[this];

  bool use_liveness = false;
  const char* target_env = std::getenv("SRRIP_LIVE_TARGET");
  if (target_env && target_env[0] != '\0') {
    std::string t(target_env);
    if      (t == "llc"  && NAME == "LLC")        use_liveness = true;
    else if (t == "stlb" && NAME == "cpu0_STLB")  use_liveness = true;
    else if (t == "both" && (NAME == "LLC" || NAME == "cpu0_STLB")) use_liveness = true;
  } else {
    if (NAME == "LLC") use_liveness = true;
  }

  if (use_liveness) {
    if (hit) {
      // Use the IPV stored at insertion time, not a fresh re-classification.
      const auto& ipv = (cls == 1) ? ::g_ipv_doa :
                        (cls == 2) ? ::g_ipv_mostly_dead :
                                     ::g_ipv_mostly_alive;
      rrpv = ipv[rrpv];
      if      (cls == 1) st.hit_doa++;
      else if (cls == 2) st.hit_dead++;
      else               st.hit_alive++;
    } else {
      const liveness_class lc = classify_block_liveness(full_addr, ip);
      const auto& ipv = (lc == liveness_class::doa)        ? ::g_ipv_doa :
                        (lc == liveness_class::mostly_dead) ? ::g_ipv_mostly_dead :
                                                              ::g_ipv_mostly_alive;
      rrpv = ipv[4];
      if      (lc == liveness_class::doa)         { cls = 1; st.ins_doa++;   }
      else if (lc == liveness_class::mostly_dead)  { cls = 2; st.ins_dead++;  }
      else                                         { cls = 3; st.ins_alive++; }
    }
  } else {
    const auto& ipv = ::g_ipv_mostly_alive;
    if (hit) { rrpv = ipv[rrpv]; st.hit_unguided++; }
    else     { rrpv = ipv[4]; cls = 0; st.ins_unguided++; }
  }
}

void CACHE::replacement_final_stats()
{
  const auto& st = ::stats[this];
  const uint64_t total_ins  = st.ins_unguided + st.ins_doa + st.ins_dead + st.ins_alive;
  const uint64_t guided_ins = st.ins_doa + st.ins_dead + st.ins_alive;

  auto pct = [](uint64_t n, uint64_t d) -> double {
    return d ? 100.0 * n / d : 0.0;
  };
  auto tot = [](const std::array<uint64_t,4>& a) {
    return a[0]+a[1]+a[2]+a[3];
  };

  const uint64_t evict_doa  = tot(st.evict_rrpv_doa);
  const uint64_t evict_dead = tot(st.evict_rrpv_dead);
  const uint64_t evict_alive= tot(st.evict_rrpv_alive);
  const uint64_t evict_ung  = tot(st.evict_rrpv_unguided);
  const uint64_t evict_total= evict_doa+evict_dead+evict_alive+evict_ung;

  printf("%s IPV-Live STATS:\n", NAME.c_str());
  printf("  IPV_doa         : {%d,%d,%d,%d,%d}\n",
         g_ipv_doa[0],g_ipv_doa[1],g_ipv_doa[2],g_ipv_doa[3],g_ipv_doa[4]);
  printf("  IPV_mostly_dead : {%d,%d,%d,%d,%d}\n",
         g_ipv_mostly_dead[0],g_ipv_mostly_dead[1],g_ipv_mostly_dead[2],
         g_ipv_mostly_dead[3],g_ipv_mostly_dead[4]);
  printf("  IPV_mostly_alive: {%d,%d,%d,%d,%d}\n",
         g_ipv_mostly_alive[0],g_ipv_mostly_alive[1],g_ipv_mostly_alive[2],
         g_ipv_mostly_alive[3],g_ipv_mostly_alive[4]);
  printf("  Activation rate : %.1f%%  (%lu guided / %lu total insertions)\n",
         pct(guided_ins, total_ins), guided_ins, total_ins);
  printf("  guided_insertions=%lu\n", guided_ins);
  printf("  Insert mix      : DoA=%.1f%%  Dead=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n",
         pct(st.ins_doa,total_ins), pct(st.ins_dead,total_ins),
         pct(st.ins_alive,total_ins), pct(st.ins_unguided,total_ins));
  printf("  Hit rate/class  : DoA=%.1f%%  Dead=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n",
         pct(st.hit_doa,st.ins_doa), pct(st.hit_dead,st.ins_dead),
         pct(st.hit_alive,st.ins_alive), pct(st.hit_unguided,st.ins_unguided));
  printf("  RRPV@evict DoA  : [0]=%.1f%% [1]=%.1f%% [2]=%.1f%% [3]=%.1f%%"
         "  (ideal: ~100%% at [%d])\n",
         pct(st.evict_rrpv_doa[0],evict_doa), pct(st.evict_rrpv_doa[1],evict_doa),
         pct(st.evict_rrpv_doa[2],evict_doa), pct(st.evict_rrpv_doa[3],evict_doa),
         ::maxRRPV);
  printf("  RRPV@evict Dead : [0]=%.1f%% [1]=%.1f%% [2]=%.1f%% [3]=%.1f%%\n",
         pct(st.evict_rrpv_dead[0],evict_dead), pct(st.evict_rrpv_dead[1],evict_dead),
         pct(st.evict_rrpv_dead[2],evict_dead), pct(st.evict_rrpv_dead[3],evict_dead));
  printf("  RRPV@evict Alive: [0]=%.1f%% [1]=%.1f%% [2]=%.1f%% [3]=%.1f%%"
         "  (ideal: low RRPV after promotion)\n",
         pct(st.evict_rrpv_alive[0],evict_alive), pct(st.evict_rrpv_alive[1],evict_alive),
         pct(st.evict_rrpv_alive[2],evict_alive), pct(st.evict_rrpv_alive[3],evict_alive));
  printf("  Aging loops     : %lu  (%.2f per eviction)\n",
         st.aging_loops, pct(st.aging_loops, evict_total) / 100.0);
  repl_hist_pc.print_stats(NAME.c_str(), mid_thd, low_thd);
  printf("\n");
}
