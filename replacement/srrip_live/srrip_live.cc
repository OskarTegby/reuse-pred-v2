// srrip_live — SRRIP with liveness-informed insertion and promotion.
//
// Policy rules (three liveness classes)
// --------------------------------------
//   DoA fill:         RRPV = maxRRPV     (evict first)
//   DoA hit:          RRPV = maxRRPV-1   (partial promotion)
//   Mostly-dead fill: RRPV = maxRRPV-1   (standard SRRIP insertion)
//   Mostly-dead hit:  RRPV = maxRRPV-2   (moderate promotion)
//   Mostly-alive fill:RRPV = maxRRPV-1   (same insertion as mostly-dead)
//   Mostly-alive hit: RRPV = 0           (full promotion, protect the block)
//
// Statistics printed in replacement_final_stats()
// ------------------------------------------------
// Activation rate      — fraction of insertions where liveness set the RRPV.
//                        Low rate → policy mostly falling back to plain SRRIP.
// Insert class mix     — DoA / mostly-alive / unguided breakdown.
// Hit rate per class   — key discriminability metric: DoA entries should have
//                        a much lower hit rate than mostly-alive entries.
//                        If similar, the predictor is not discriminating well.
// RRPV at eviction     — histogram of RRPV values when each class is evicted.
//   DoA entries:   ideally maxRRPV (evicted immediately, no aging needed).
//   Alive entries: ideally 0-1 (evicted only after being promoted by hits).
//   If DoA entries frequently leave at RRPV<maxRRPV they are being aged up
//   and consuming residency — the policy is not shedding them quickly enough.
//   If alive entries leave at maxRRPV they never got a hit — wasted residency.
// Aging loops          — how many scan-and-increment passes find_victim needed.
//                        Fewer loops = less cache pressure from protected entries.

#include <array>
#include <cassert>
#include <cstdint>
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
    std::array<uint64_t, 4> evict_rrpv_doa      = {};
    std::array<uint64_t, 4> evict_rrpv_dead      = {};
    std::array<uint64_t, 4> evict_rrpv_alive     = {};
    std::array<uint64_t, 4> evict_rrpv_unguided  = {};
    uint64_t aging_loops = 0;
};
std::unordered_map<CACHE*, Stats> stats;

} // namespace

void CACHE::initialize_replacement()
{
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

  const uint32_t way = static_cast<uint32_t>(std::distance(begin, victim));
  const std::size_t idx = set * NUM_WAY + way;
  const int8_t  cls  = ::slot_class[this][idx];
  const int     rrpv = ::rrpv_values[this][idx];
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
  // NOTE: plain SRRIP promotes every hit (including write hits) to RRPV 0.
  // We deliberately do NOT special-case write hits here, so that when liveness
  // provides no signal (block defaults to mostly-alive), this policy behaves
  // identically to baseline SRRIP. Any speedup over SRRIP is then attributable
  // to liveness guidance alone, not to incidental write-hit handling.
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
      // Use the class stored at insertion time — do not re-classify at hit time.
      // Re-classifying allows a block inserted as alive to lose full promotion if
      // its PC accumulates DoA history while the block sits in the cache, which
      // causes live blocks to be evicted prematurely.
      switch (cls) {
        case 1:  rrpv = ::maxRRPV - 1; st.hit_doa++;   break;  // DoA: partial
        case 2:  rrpv = ::maxRRPV - 2; st.hit_dead++;  break;  // mostly-dead: moderate
        default: rrpv = 0;             st.hit_alive++;  break;  // alive or unguided: full
      }
    } else {
      const liveness_class lc = classify_block_liveness(full_addr, ip);
      if      (lc == liveness_class::doa)         { rrpv = ::maxRRPV;     cls = 1; st.ins_doa++;  }
      else if (lc == liveness_class::mostly_dead)  { rrpv = ::maxRRPV - 1; cls = 2; st.ins_dead++; }
      else                                         { rrpv = ::maxRRPV - 1; cls = 3; st.ins_alive++;}
    }
  } else {
    if (hit) { rrpv = 0;             st.hit_unguided++; }
    else     { rrpv = ::maxRRPV - 1; cls = 0; st.ins_unguided++; }
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
  const uint64_t evict_total= evict_doa + evict_dead + evict_alive + evict_ung;

  printf("%s SRRIP-Live STATS:\n", NAME.c_str());
  printf("  Activation rate  : %.1f%%  (%lu guided / %lu total insertions)\n",
         pct(guided_ins, total_ins), guided_ins, total_ins);
  printf("  guided_insertions=%lu\n", guided_ins);
  printf("  Insert mix       : DoA=%.1f%%  Dead=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n",
         pct(st.ins_doa,total_ins), pct(st.ins_dead,total_ins),
         pct(st.ins_alive,total_ins), pct(st.ins_unguided,total_ins));
  printf("  Hit rate/class   : DoA=%.1f%%  Dead=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n",
         pct(st.hit_doa,st.ins_doa), pct(st.hit_dead,st.ins_dead),
         pct(st.hit_alive,st.ins_alive), pct(st.hit_unguided,st.ins_unguided));
  printf("  RRPV@evict DoA   : [0]=%.1f%% [1]=%.1f%% [2]=%.1f%% [3]=%.1f%%"
         "  (ideal: ~100%% at [%d])\n",
         pct(st.evict_rrpv_doa[0],evict_doa), pct(st.evict_rrpv_doa[1],evict_doa),
         pct(st.evict_rrpv_doa[2],evict_doa), pct(st.evict_rrpv_doa[3],evict_doa),
         ::maxRRPV);
  printf("  RRPV@evict Dead  : [0]=%.1f%% [1]=%.1f%% [2]=%.1f%% [3]=%.1f%%\n",
         pct(st.evict_rrpv_dead[0],evict_dead), pct(st.evict_rrpv_dead[1],evict_dead),
         pct(st.evict_rrpv_dead[2],evict_dead), pct(st.evict_rrpv_dead[3],evict_dead));
  printf("  RRPV@evict Alive : [0]=%.1f%% [1]=%.1f%% [2]=%.1f%% [3]=%.1f%%"
         "  (ideal: low RRPV after promotion)\n",
         pct(st.evict_rrpv_alive[0],evict_alive), pct(st.evict_rrpv_alive[1],evict_alive),
         pct(st.evict_rrpv_alive[2],evict_alive), pct(st.evict_rrpv_alive[3],evict_alive));
  printf("  Aging loops      : %lu  (%.2f per eviction)\n",
         st.aging_loops, pct(st.aging_loops, evict_total) / 100.0);
  repl_hist_pc.print_stats(NAME.c_str(), mid_thd, low_thd);
  printf("\n");
}
