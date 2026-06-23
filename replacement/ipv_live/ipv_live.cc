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
// Runtime overrides (index layout: [hit@0, hit@1, hit@2, hit@3, insert]):
//   IPV_DOA=0,1,2,2,2          default: insert@2, reset to 2 on hit (mirrors LRU-Live DoA)
//   IPV_MOSTLY_DEAD=0,1,1,2,2  default: insert@2, hit@2→1, hit@1→1 (capped at RRPV=1)
//   IPV_MOSTLY_ALIVE=0,0,0,0,2 default: insert@2, full promotion on first hit
//   SRRIP_LIVE_TARGET=llc|stlb|both
//
// N-way set dueling (DUEL_N_CONFIGS=N, DUEL_N_SAMPLERS=S):
//   Partitions LLC sets into N sampler groups (S sets each) plus followers.
//   Each group i always uses IPV_DOA_i; followers use whichever group has the
//   most demand hits so far (argmax of per-group hit counters).
//   IPV_DOA_i defaults: config 0 → IPV_DOA, config 1 → IPV_DOA_B, rest → {0,1,2,2,3}.
//   MD and MA IPVs are shared across all configs (only DoA varies).
//   DUEL_HYST: config i must lead all others by HYST hits to win followers.

#include <algorithm>
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
constexpr int maxRRPV        = 3;
constexpr int MAX_DUEL_CFGS  = 8;

std::unordered_map<CACHE*, std::vector<int>>    rrpv_values;
// 0=unguided  1=doa  2=mostly_dead  3=mostly_alive
std::unordered_map<CACHE*, std::vector<int8_t>> slot_class;
// which duel config was active at insertion time (0..N-1)
std::unordered_map<CACHE*, std::vector<uint8_t>> slot_cfg_idx;
// per-config hit counters (saturating at INT64_MAX in practice, but won't overflow)
std::unordered_map<CACHE*, std::array<int64_t, MAX_DUEL_CFGS>> hit_counts;

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
ipv_t g_ipv_mostly_dead  = {0, 1, 1, 2, 2};
ipv_t g_ipv_mostly_alive = {0, 0, 0, 0, 2};

// Shared (non-dueling) DoA config read from IPV_DOA; also used as duel config 0 default.
ipv_t g_ipv_doa = {0, 1, 2, 2, 2};
bool  g_parsed  = false;

// N-way dueling state
int   g_n_configs  = 0;   // 0 = dueling disabled; 2+ = N-way
int   g_n_samplers = 0;   // sampler sets per config
int   g_hyst       = 0;   // hit-count lead required to win followers
// Which insertion-class hits count toward the duel signal (DUEL_HIT_FILTER):
//   0 = all hits (default)         — raw demand hits, any class
//   1 = exclude DoA (cls != 1)     — MD+MA hits only
//   2 = mostly-alive only (cls==3) — productive-residency hits only
// Rationale: counting DoA-block hits biases toward retention (ins@2), which on
// some suites (qmm) is anti-correlated with IPC. The benefit of ins@3 shows up
// as MORE non-DoA hits (freed space lets live data stay), so filtering DoA hits
// realigns the signal with performance. See update_replacement_state.
int   g_hit_filter = 0;
std::array<ipv_t, MAX_DUEL_CFGS> g_duel_doa;
bool  g_parsed_duel = false;

ipv_t parse_ipv(const char* var, ipv_t dflt)
{
  const char* s = std::getenv(var);
  if (!s) return dflt;
  char buf[64];
  std::strncpy(buf, s, sizeof(buf) - 1);
  buf[sizeof(buf) - 1] = '\0';
  ipv_t v = dflt;
  char* tok = std::strtok(buf, ",:");
  for (int i = 0; i < 5 && tok; ++i, tok = std::strtok(nullptr, ",:"))
    v[i] = std::atoi(tok);
  return v;
}

void ensure_parsed()
{
  if (g_parsed) return;
  g_parsed = true;
  g_ipv_doa         = parse_ipv("IPV_DOA",         g_ipv_doa);
  g_ipv_mostly_dead = parse_ipv("IPV_MOSTLY_DEAD",  g_ipv_mostly_dead);
  g_ipv_mostly_alive= parse_ipv("IPV_MOSTLY_ALIVE", g_ipv_mostly_alive);
}

void ensure_parsed_duel()
{
  if (g_parsed_duel) return;
  g_parsed_duel = true;

  const char* e = std::getenv("DUEL_N_CONFIGS");
  g_n_configs = (e && *e) ? std::atoi(e) : 0;
  const char* ns = std::getenv("DUEL_N_SAMPLERS");
  g_n_samplers = (ns && *ns) ? std::atoi(ns) : 0;
  // Backward compat: old scripts set DUEL_N_SAMPLERS without DUEL_N_CONFIGS.
  if (g_n_configs < 2 && g_n_samplers > 0) g_n_configs = 2;
  const char* h = std::getenv("DUEL_HYST");
  g_hyst = (h && *h) ? std::atoi(h) : 0;
  const char* hf = std::getenv("DUEL_HIT_FILTER");
  if (hf && *hf) {
    if      (std::strcmp(hf, "alive") == 0 || std::strcmp(hf, "2") == 0) g_hit_filter = 2;
    else if (std::strcmp(hf, "live")  == 0 || std::strcmp(hf, "1") == 0) g_hit_filter = 1;
    else                                                                  g_hit_filter = 0;
  }

  if (g_n_configs < 2) return;
  if (g_n_configs > MAX_DUEL_CFGS) g_n_configs = MAX_DUEL_CFGS;

  // Default DoA vectors per config index:
  //   0 → IPV_DOA (ins@2 conservative)
  //   1 → IPV_DOA_B if set, else {0,1,2,2,3} (ilB)
  //   2+ → {0,1,2,2,3}
  const ipv_t dflt_1 = parse_ipv("IPV_DOA_B", {0, 1, 2, 2, 3});
  const ipv_t dflt_n = {0, 1, 2, 2, 3};

  for (int i = 0; i < g_n_configs; ++i) {
    char var[32];
    std::snprintf(var, sizeof(var), "IPV_DOA_%d", i);
    ipv_t dflt = (i == 0) ? g_ipv_doa : (i == 1) ? dflt_1 : dflt_n;
    g_duel_doa[i] = parse_ipv(var, dflt);
  }
}

// Returns which duel config owns this set as a sampler (-1 = follower).
// Config i owns sets where set % step == (i * step) / n_configs.
int sampler_config_of(int set, int step, int n_configs)
{
  const int j = set % step;
  for (int i = 0; i < n_configs; ++i)
    if (j == (i * step) / n_configs) return i;
  return -1;
}

// Returns the winning config index for follower sets (argmax with hysteresis).
// If no config leads all others by at least g_hyst, returns 0 (conservative default).
int winner_config(CACHE* c)
{
  const auto& hc = ::hit_counts[c];
  int best = 0;
  for (int i = 1; i < ::g_n_configs; ++i)
    if (hc[i] > hc[best]) best = i;
  // Hysteresis: best must lead every other config by g_hyst, else fall back to 0.
  if (::g_hyst > 0) {
    for (int i = 0; i < ::g_n_configs; ++i) {
      if (i == best) continue;
      if (hc[best] - hc[i] <= static_cast<int64_t>(::g_hyst)) return 0;
    }
  }
  return best;
}

} // namespace

void CACHE::initialize_replacement()
{
  ::ensure_parsed();
  ::ensure_parsed_duel();
  const std::size_t n = NUM_SET * NUM_WAY;
  ::rrpv_values[this]  = std::vector<int>    (n, ::maxRRPV);
  ::slot_class[this]   = std::vector<int8_t> (n, 0);
  ::slot_cfg_idx[this] = std::vector<uint8_t>(n, 0);
  ::stats[this]        = Stats{};
  ::hit_counts[this]   = {};
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

  const uint32_t    way = static_cast<uint32_t>(std::distance(begin, victim));
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
    const int nc   = ::g_n_configs;
    const int ns   = ::g_n_samplers;
    const int step = (nc >= 2 && ns > 0) ? static_cast<int>(NUM_SET) / ns : 0;

    // Determine which config this set uses.
    int cfg;
    if (step > 0) {
      const int sc = ::sampler_config_of(static_cast<int>(set), step, nc);
      if (sc >= 0) {
        // Sampler set: always uses its assigned config; records a hit for it.
        // cls holds the block's insertion class (1=DoA, 2=MD, 3=MA). The hit
        // filter (DUEL_HIT_FILTER) decides which classes contribute to the
        // duel signal — excluding DoA hits removes the retention bias.
        cfg = sc;
        bool count_hit = hit && type != WRITE;
        if (count_hit && ::g_hit_filter == 1) count_hit = (cls != 1);
        if (count_hit && ::g_hit_filter == 2) count_hit = (cls == 3);
        if (count_hit)
          ::hit_counts[this][sc]++;
      } else {
        // Follower set: uses current winner.
        cfg = ::winner_config(this);
      }
    } else {
      cfg = 0;  // dueling disabled — always config 0
    }

    auto& cfg_stored = ::slot_cfg_idx[this][idx];
    if (hit) {
      // Use the config stored at insertion time for promotion.
      const int c = static_cast<int>(cfg_stored);
      const ipv_t& ipv = (cls == 1) ? ::g_duel_doa[c] :
                         (cls == 2) ? ::g_ipv_mostly_dead :
                                      ::g_ipv_mostly_alive;
      if (type != WRITE) rrpv = ipv[rrpv];
      if      (cls == 1) st.hit_doa++;
      else if (cls == 2) st.hit_dead++;
      else               st.hit_alive++;
    } else {
      const liveness_class lc = classify_block_liveness(full_addr, ip);
      const ipv_t& ipv = (lc == liveness_class::doa)         ? ::g_duel_doa[cfg] :
                         (lc == liveness_class::mostly_dead)  ? ::g_ipv_mostly_dead :
                                                                 ::g_ipv_mostly_alive;
      cfg_stored = static_cast<uint8_t>(cfg);
      rrpv = ipv[4];
      if      (lc == liveness_class::doa)         { cls = 1; st.ins_doa++;   }
      else if (lc == liveness_class::mostly_dead)  { cls = 2; st.ins_dead++;  }
      else                                         { cls = 3; st.ins_alive++; }
    }
  } else {
    const auto& ipv = ::g_ipv_mostly_alive;
    if (hit) { if (type != WRITE) rrpv = ipv[rrpv]; st.hit_unguided++; }
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

  if (::g_n_configs >= 2) {
    const int winner = ::winner_config(this);
    const char* filt = ::g_hit_filter == 2 ? "alive" :
                       ::g_hit_filter == 1 ? "live"  : "all";
    printf("  Set dueling     : N=%d  samplers/cfg=%d  hyst=%d  hit_filter=%s  winner=config_%d\n",
           ::g_n_configs, ::g_n_samplers, ::g_hyst, filt, winner);
    for (int i = 0; i < ::g_n_configs; ++i) {
      const ipv_t& d = ::g_duel_doa[i];
      printf("  Config %d%s: DoA={%d,%d,%d,%d,%d}  sampler_hits=%ld\n",
             i, (i == winner ? "*" : " "),
             d[0],d[1],d[2],d[3],d[4],
             ::hit_counts[this][i]);
    }
    printf("  MD: {%d,%d,%d,%d,%d}  MA: {%d,%d,%d,%d,%d}  (shared across configs)\n",
           ::g_ipv_mostly_dead[0],::g_ipv_mostly_dead[1],::g_ipv_mostly_dead[2],
           ::g_ipv_mostly_dead[3],::g_ipv_mostly_dead[4],
           ::g_ipv_mostly_alive[0],::g_ipv_mostly_alive[1],::g_ipv_mostly_alive[2],
           ::g_ipv_mostly_alive[3],::g_ipv_mostly_alive[4]);
  } else {
    printf("  IPV_doa         : {%d,%d,%d,%d,%d}\n",
           ::g_ipv_doa[0],::g_ipv_doa[1],::g_ipv_doa[2],::g_ipv_doa[3],::g_ipv_doa[4]);
    printf("  IPV_mostly_dead : {%d,%d,%d,%d,%d}\n",
           ::g_ipv_mostly_dead[0],::g_ipv_mostly_dead[1],::g_ipv_mostly_dead[2],
           ::g_ipv_mostly_dead[3],::g_ipv_mostly_dead[4]);
    printf("  IPV_mostly_alive: {%d,%d,%d,%d,%d}\n",
           ::g_ipv_mostly_alive[0],::g_ipv_mostly_alive[1],::g_ipv_mostly_alive[2],
           ::g_ipv_mostly_alive[3],::g_ipv_mostly_alive[4]);
  }

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
  repl_hist_pc.print_stats(NAME.c_str(), thd_doa, thd_dead);
  printf("\n");
}
