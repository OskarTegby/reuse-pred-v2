// srrip_live — SRRIP with liveness-informed insertion and promotion.
//
// Policy rules (two liveness classes: was the block ever touched before
// eviction? A third, intermediate "mostly-dead" wall-clock-halflife class was
// tried and removed — no configuration showed it contributing a real,
// reproducible IPC benefit.)
// --------------------------------------
//   DoA fill:   RRPV = SRRIP_DOA_INS_RRPV  (default 2: moderate, not immediate eviction)
//   DoA hit:    RRPV = SRRIP_DOA_HIT_RRPV  (default 2: reset to insertion, no reward)
//   Alive fill: RRPV = maxRRPV-1           (standard SRRIP insertion)
//   Alive hit:  RRPV = 0                   (full promotion, protect the block)
//
// Runtime overrides (LRU-Live mapping: DoA→2N/3 from MRU=RRPV2):
//   SRRIP_DOA_INS_RRPV=N  insertion RRPV for DoA blocks (default 2).
//   SRRIP_DOA_HIT_RRPV=N  RRPV on DoA hit; 2=reset-to-ins (default, no reward), 1=mild.
//
// Statistics printed in replacement_final_stats()
// ------------------------------------------------
// Activation rate      — fraction of insertions where liveness set the RRPV.
//                        Low rate → policy mostly falling back to plain SRRIP.
// Insert class mix     — DoA / alive / unguided breakdown.
// Hit rate per class   — key discriminability metric: DoA entries should have
//                        a much lower hit rate than alive entries.
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
// 0=unguided  1=doa  2=alive
std::unordered_map<CACHE*, std::vector<int8_t>> slot_class;

struct Stats {
    uint64_t ins_unguided = 0, ins_doa = 0, ins_alive = 0;
    uint64_t hit_unguided = 0, hit_doa = 0, hit_alive = 0;
    std::array<uint64_t, 4> evict_rrpv_doa      = {};
    std::array<uint64_t, 4> evict_rrpv_alive     = {};
    std::array<uint64_t, 4> evict_rrpv_unguided  = {};
    uint64_t aging_loops = 0;
    uint64_t sampler_a_hits = 0;
    uint64_t sampler_b_hits = 0;
    // Lifespan (cycles from insertion to eviction) per insertion class:
    //   [0]=unguided  [1]=doa  [2]=alive
    std::array<uint64_t, 3> lifespan_sum   = {};
    std::array<uint64_t, 3> lifespan_count = {};
};
std::unordered_map<CACHE*, Stats> stats;

constexpr int PSEL_BITS = 10;
constexpr int PSEL_MAX  = (1 << PSEL_BITS) - 1;
constexpr int PSEL_MID  = 1 << (PSEL_BITS - 1);

std::unordered_map<CACHE*, int>                  psel;
std::unordered_map<CACHE*, std::vector<uint8_t>> slot_cfg_b;
std::unordered_map<CACHE*, int64_t>              miss_lat_a;
std::unordered_map<CACHE*, int64_t>              miss_lat_b;

} // namespace

static int g_duel_metric  = -1;  // 0=hits (PSEL), 1=latency (argmin)
static int g_doa_ins_rrpv = -1;
static int g_doa_hit_rrpv = -1;

static int parse_env_rrpv(const char* var, int dflt)
{
  const char* e = std::getenv(var);
  return (e && *e) ? std::atoi(e) : dflt;
}

static int doa_ins_rrpv() { if (g_doa_ins_rrpv < 0) g_doa_ins_rrpv = parse_env_rrpv("SRRIP_DOA_INS_RRPV", 2); return g_doa_ins_rrpv; }
static int doa_hit_rrpv() { if (g_doa_hit_rrpv < 0) g_doa_hit_rrpv = parse_env_rrpv("SRRIP_DOA_HIT_RRPV", 2); return g_doa_hit_rrpv; }

// Config B: default is ins3/hit0 for DoA (opposite of default A's ins2/hit2).
// Override via SRRIP_DOA_INS_RRPV_B / SRRIP_DOA_HIT_RRPV_B.
// Set dueling (DUEL_N_SAMPLERS=N) picks A or B per workload via PSEL counter.
static int g_doa_ins_b = -1, g_doa_hit_b = -1;
static int     g_n_samplers = -1;
static int64_t g_hyst       = -1;  // cfgB must lead cfgA by this margin to win followers

static int doa_ins_b()  { if (g_doa_ins_b  < 0) g_doa_ins_b  = parse_env_rrpv("SRRIP_DOA_INS_RRPV_B", 3); return g_doa_ins_b;  }
static int doa_hit_b()  { if (g_doa_hit_b  < 0) g_doa_hit_b  = parse_env_rrpv("SRRIP_DOA_HIT_RRPV_B", 0); return g_doa_hit_b;  }
static int n_samplers() {
  if (g_n_samplers < 0) {
    const char* e = std::getenv("DUEL_N_SAMPLERS");
    g_n_samplers = (e && *e) ? std::atoi(e) : 0;
  }
  return g_n_samplers;
}
static int64_t hyst() {
  if (g_hyst < 0) {
    const char* e = std::getenv("DUEL_HYST");
    g_hyst = (e && *e) ? static_cast<int64_t>(std::atoll(e)) : 0;
  }
  return g_hyst;
}
static int duel_metric() {
  if (g_duel_metric < 0) {
    const char* e = std::getenv("DUEL_METRIC");
    g_duel_metric = (e && (std::string(e) == "latency" || std::string(e) == "1")) ? 1 : 0;
  }
  return g_duel_metric;
}

void CACHE::initialize_replacement()
{
  const std::size_t n = NUM_SET * NUM_WAY;
  ::rrpv_values[this]  = std::vector<int>   (n, ::maxRRPV);
  ::slot_class[this]   = std::vector<int8_t>(n, 0);
  ::slot_cfg_b[this]   = std::vector<uint8_t>(n, 0);
  ::stats[this]        = Stats{};
  ::psel[this]         = PSEL_MID;
  ::miss_lat_a[this]   = 0;
  ::miss_lat_b[this]   = 0;
  (void)doa_ins_rrpv(); (void)doa_hit_rrpv();
  (void)doa_ins_b();    (void)doa_hit_b();
  (void)n_samplers();   (void)duel_metric();  (void)hyst();
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
    case 2: st.evict_rrpv_alive  [rrpv]++; break;
    default:st.evict_rrpv_unguided[rrpv]++; break;
  }

  const uint64_t ins_cycle = current_set[way].install_cycle;
  if (ins_cycle > 0 && current_cycle >= ins_cycle) {
    const int ci = (cls >= 0 && cls <= 2) ? cls : 0;
    st.lifespan_sum[ci]   += current_cycle - ins_cycle;
    st.lifespan_count[ci] += 1;
  }

  return way;
}

void CACHE::update_replacement_state(uint32_t triggering_cpu, uint32_t set, uint32_t way,
                                      uint64_t full_addr, uint64_t ip, uint64_t victim_addr,
                                      uint32_t type, uint8_t hit)
{
  // NOTE: plain SRRIP promotes every hit (including write hits) to RRPV 0.
  // We deliberately do NOT special-case write hits here, so that when liveness
  // provides no signal (block defaults to alive), this policy behaves
  // identically to baseline SRRIP. Any speedup over SRRIP is then attributable
  // to liveness guidance alone, not to incidental write-hit handling.
  const std::size_t idx = set * NUM_WAY + way;
  auto& rrpv = ::rrpv_values[this][idx];
  auto& cls  = ::slot_class[this][idx];
  auto& st   = ::stats[this];

  // SRRIP_LIVE_TARGET=none explicitly disables liveness guidance while
  // still on the LLC (used by the "bypass" condition: raw DoA bypass stays
  // active in cache.cc, but insertion/promotion here falls back to plain
  // SRRIP). Liveness guidance never applies anywhere but the LLC.
  const char* target_env = std::getenv("SRRIP_LIVE_TARGET");
  const bool disabled = target_env && target_env[0] != '\0' && std::string(target_env) != "llc";
  const bool use_liveness = (NAME == "LLC") && !disabled;

  if (use_liveness) {
    // Set dueling: classify set as sampler_a, sampler_b, or follower.
    // Sampler A always uses config A; sampler B always uses config B.
    // On each demand hit, the winning sampler's PSEL edge increments toward it.
    // Followers adopt whichever config has more hits (PSEL > MID → B wins).
    // With DUEL_N_SAMPLERS=0 (default), step=0, every set is a follower using A.
    const int ns   = ::n_samplers();
    const int step = ns > 0 ? static_cast<int>(NUM_SET) / ns : 0;
    const bool is_a = step > 0 && static_cast<int>(set) % step == 0;
    const bool is_b = step > 0 && static_cast<int>(set) % step == step / 2;

    if (duel_metric() == 1) {
      // Latency mode: accumulate fill latency per sampler config; argmin wins.
      if (!hit && type != WRITE) {
        if (is_a) ::miss_lat_a[this] += static_cast<int64_t>(this->last_fill_latency);
        if (is_b) ::miss_lat_b[this] += static_cast<int64_t>(this->last_fill_latency);
      }
    } else {
      // Hit-count mode: PSEL increments toward the sampler with more demand hits.
      if (hit && type != WRITE) {
        if (is_a) { ::psel[this] = std::max(0,        ::psel[this] - 1); st.sampler_a_hits++; }
        if (is_b) { ::psel[this] = std::min(PSEL_MAX, ::psel[this] + 1); st.sampler_b_hits++; }
      }
    }
    // ub: this slot should use config B
    const bool b_wins = (duel_metric() == 1)
        ? (::miss_lat_a[this] - ::miss_lat_b[this] > ::hyst())
        : (::psel[this] > PSEL_MID + static_cast<int>(::hyst()));
    const bool ub = is_b || (!is_a && step > 0 && b_wins);

    auto& cfg_b = ::slot_cfg_b[this][idx];
    if (hit) {
      // Use the config stored at insertion time — do not re-classify.
      const bool promote = (type != WRITE);
      switch (cls) {
        case 1:  if (promote) rrpv = cfg_b ? ::doa_hit_b() : ::doa_hit_rrpv(); st.hit_doa++;  break;
        default: if (promote) rrpv = 0;                                         st.hit_alive++; break;
      }
    } else {
      const liveness_class lc = classify_block_liveness(full_addr, ip);
      cfg_b = ub;
      if (lc == liveness_class::doa) { rrpv = ub ? ::doa_ins_b() : ::doa_ins_rrpv(); cls = 1; st.ins_doa++; }
      else                           { rrpv = ::maxRRPV - 1; cls = 2; st.ins_alive++; }
    }
  } else {
    // No liveness signal: behave exactly like baseline SRRIP.
    if (hit) { if (type != WRITE) rrpv = 0; st.hit_unguided++; }
    else     { rrpv = ::maxRRPV - 1; cls = 0; st.ins_unguided++; }
  }
}

void CACHE::replacement_final_stats()
{
  const auto& st = ::stats[this];
  const uint64_t total_ins  = st.ins_unguided + st.ins_doa + st.ins_alive;
  const uint64_t guided_ins = st.ins_doa + st.ins_alive;

  auto pct = [](uint64_t n, uint64_t d) -> double {
    return d ? 100.0 * n / d : 0.0;
  };
  auto tot = [](const std::array<uint64_t,4>& a) {
    return a[0]+a[1]+a[2]+a[3];
  };

  const uint64_t evict_doa  = tot(st.evict_rrpv_doa);
  const uint64_t evict_alive= tot(st.evict_rrpv_alive);
  const uint64_t evict_ung  = tot(st.evict_rrpv_unguided);
  const uint64_t evict_total= evict_doa + evict_alive + evict_ung;

  printf("%s SRRIP-Live STATS:\n", NAME.c_str());
  if (::n_samplers() > 0) {
    const bool lat = (::duel_metric() == 1);
    const bool b_wins = lat ? (::miss_lat_b[this] < ::miss_lat_a[this])
                            : (::psel[this] > PSEL_MID);
    if (lat) {
      printf("  Set dueling      : metric=latency  winner=%s"
             "  lat_a=%ld  lat_b=%ld\n",
             b_wins ? "config_B" : "config_A",
             ::miss_lat_a[this], ::miss_lat_b[this]);
    } else {
      const int p = ::psel[this];
      printf("  Set dueling      : metric=hits  PSEL=%d/%d  winner=%s"
             "  sampler_a_hits=%lu  sampler_b_hits=%lu\n",
             p, PSEL_MAX, b_wins ? "config_B" : "config_A",
             st.sampler_a_hits, st.sampler_b_hits);
    }
    printf("  Config A: DoA ins=%d hit=%d\n", ::doa_ins_rrpv(), ::doa_hit_rrpv());
    printf("  Config B: DoA ins=%d hit=%d"
           "  (SRRIP_DOA_INS_RRPV_B / _HIT_RRPV_B)\n",
           ::doa_ins_b(), ::doa_hit_b());
  } else {
    printf("  DoA ins RRPV     : %d  (SRRIP_DOA_INS_RRPV; 2=default, 3=legacy)\n",    ::doa_ins_rrpv());
    printf("  DoA hit RRPV     : %d  (SRRIP_DOA_HIT_RRPV; 2=reset-to-ins, 1=mild)\n", ::doa_hit_rrpv());
  }
  printf("  Activation rate  : %.1f%%  (%lu guided / %lu total insertions)\n",
         pct(guided_ins, total_ins), guided_ins, total_ins);
  printf("  guided_insertions=%lu\n", guided_ins);
  printf("  Insert mix       : DoA=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n",
         pct(st.ins_doa,total_ins), pct(st.ins_alive,total_ins), pct(st.ins_unguided,total_ins));
  printf("  Hit rate/class   : DoA=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n",
         pct(st.hit_doa,st.ins_doa), pct(st.hit_alive,st.ins_alive), pct(st.hit_unguided,st.ins_unguided));
  printf("  RRPV@evict DoA   : [0]=%.1f%% [1]=%.1f%% [2]=%.1f%% [3]=%.1f%%"
         "  (ideal: ~100%% at [%d])\n",
         pct(st.evict_rrpv_doa[0],evict_doa), pct(st.evict_rrpv_doa[1],evict_doa),
         pct(st.evict_rrpv_doa[2],evict_doa), pct(st.evict_rrpv_doa[3],evict_doa),
         ::maxRRPV);
  printf("  RRPV@evict Alive : [0]=%.1f%% [1]=%.1f%% [2]=%.1f%% [3]=%.1f%%"
         "  (ideal: low RRPV after promotion)\n",
         pct(st.evict_rrpv_alive[0],evict_alive), pct(st.evict_rrpv_alive[1],evict_alive),
         pct(st.evict_rrpv_alive[2],evict_alive), pct(st.evict_rrpv_alive[3],evict_alive));
  printf("  Aging loops      : %lu  (%.2f per eviction)\n",
         st.aging_loops, pct(st.aging_loops, evict_total) / 100.0);

  auto avg_life = [&](int ci) -> double {
    return st.lifespan_count[ci] ? static_cast<double>(st.lifespan_sum[ci]) / st.lifespan_count[ci] : 0.0;
  };
  printf("  Avg lifespan(cy) : DoA=%.0f  Alive=%.0f  Unguided=%.0f\n",
         avg_life(1), avg_life(2), avg_life(0));

  liveness_hist.print_stats(NAME.c_str());
  printf("\n");
}
