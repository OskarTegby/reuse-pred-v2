#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>

#include "cache.h"

namespace
{
constexpr int MAX_DUEL_CFGS = 8;

#include "../ipv_common.h"

// Clamps `base`'s promotion targets to `floor`, inserting at `floor`.
std::vector<int> clamp_ipv(const std::vector<int>& base, std::size_t k, int floor)
{
  std::vector<int> v(k + 1);
  for (std::size_t p = 0; p < k; ++p) v[p] = std::max(base[p], floor);
  v[k] = floor;
  return v;
}

// SRRIP_LIVE_TARGET=none explicitly disables liveness guidance while still
// on the LLC (used by the "bypass" condition: raw DoA bypass stays active
// in cache.cc, but insertion/promotion here falls back to plain IPV).
// Liveness guidance never applies anywhere but the LLC.
bool is_targeted(const CACHE& c)
{
  if (c.NAME != "LLC") return false;
  const char* target_env = std::getenv("SRRIP_LIVE_TARGET");
  return !(target_env && target_env[0] != '\0' && std::string(target_env) != "llc");
}

// per-CACHE* state (NUM_WAY, hence vector length, varies by cache -- LLC vs STLB)
std::unordered_map<CACHE*, std::vector<int>>      g_ipv_alive;
std::unordered_map<CACHE*, std::vector<uint16_t>> g_order;
std::unordered_map<CACHE*, std::vector<uint16_t>> g_rank;
std::unordered_map<CACHE*, std::vector<int8_t>>   g_slot_class; // 0=unguided 1=doa 2=alive

struct Stats {
  uint64_t ins_unguided = 0, ins_doa = 0, ins_alive = 0;
  uint64_t hit_unguided = 0, hit_doa = 0, hit_alive = 0;
};
std::unordered_map<CACHE*, Stats> g_stats;

// The only place liveness classification becomes an IPV vector choice.
// slot_class: 0=unguided 1=doa 2=alive.
const std::vector<int>& ipv_for_insert(liveness_class lc, const std::vector<int>& alive, const std::vector<int>& doa)
{
  return (lc == liveness_class::doa) ? doa : alive;
}
const std::vector<int>& ipv_for_hit(int8_t cls, const std::vector<int>& alive, const std::vector<int>& doa)
{
  return (cls == 1) ? doa : alive;
}

// --- Set dueling ------------------------------------------------------
// Partitions LLC sets into N sampler groups (S sets each) plus followers.
// Each group i always uses IPV_DOA_i; followers use whichever group has the
// most demand hits so far (argmax of per-group hit counters), or lowest
// accumulated miss latency when DUEL_METRIC=latency. See header comment above.
std::unordered_map<CACHE*, std::array<std::vector<int>, MAX_DUEL_CFGS>> g_duel_doa;
std::unordered_map<CACHE*, std::vector<uint8_t>>               g_slot_cfg_idx; // duel config active at insertion
std::unordered_map<CACHE*, std::array<int64_t, MAX_DUEL_CFGS>> g_hit_counts;
std::unordered_map<CACHE*, std::array<int64_t, MAX_DUEL_CFGS>> g_miss_latency;

int g_n_configs   = -1;
int g_n_samplers  = -1;
int g_hit_filter  = -1;
int g_duel_metric = -1;
int64_t g_hyst    = -1;

void ensure_parsed_duel()
{
  if (g_n_configs >= 0) return;
  const char* e = std::getenv("DUEL_N_CONFIGS");
  g_n_configs = (e && *e) ? std::atoi(e) : 0;
  const char* ns = std::getenv("DUEL_N_SAMPLERS");
  g_n_samplers = (ns && *ns) ? std::atoi(ns) : 0;
  if (g_n_configs < 2 && g_n_samplers > 0) g_n_configs = 2; // backward compat
  if (g_n_configs > MAX_DUEL_CFGS) g_n_configs = MAX_DUEL_CFGS;
  const char* h = std::getenv("DUEL_HYST");
  g_hyst = (h && *h) ? static_cast<int64_t>(std::atoll(h)) : 0;
  const char* hf = std::getenv("DUEL_HIT_FILTER");
  g_hit_filter = 0;
  if (hf && *hf) {
    if      (std::strcmp(hf, "alive") == 0 || std::strcmp(hf, "2") == 0) g_hit_filter = 2;
    else if (std::strcmp(hf, "live")  == 0 || std::strcmp(hf, "1") == 0) g_hit_filter = 1;
  }
  const char* dm = std::getenv("DUEL_METRIC");
  g_duel_metric = (dm && (std::strcmp(dm, "latency") == 0 || std::strcmp(dm, "1") == 0)) ? 1 : 0;
}

int winner_config(CACHE* c)
{
  const bool lat = (g_duel_metric == 1);
  const auto& m = lat ? g_miss_latency[c] : g_hit_counts[c];
  int best = 0;
  for (int i = 1; i < g_n_configs; ++i) {
    const bool better = lat ? (m[i] < m[best]) : (m[i] > m[best]);
    if (better) best = i;
  }
  if (g_hyst > 0) {
    for (int i = 0; i < g_n_configs; ++i) {
      if (i == best) continue;
      const int64_t margin = lat ? (m[i] - m[best]) : (m[best] - m[i]);
      if (margin <= g_hyst) return 0;
    }
  }
  return best;
}

int sampler_config_of(int set, int step, int n_configs)
{
  const int j = set % step;
  for (int i = 0; i < n_configs; ++i)
    if (j == (i * step) / n_configs) return i;
  return -1;
}
// --- end set dueling ----------------------------------------------------
} // namespace

void CACHE::initialize_replacement()
{
  ::ensure_parsed_duel();
  const std::size_t k = NUM_WAY;

  const std::vector<int> alive = ::parse_ipv_env("IPV_ALIVE", k, ::default_ipv(k));
  ::g_ipv_alive[this] = alive;

  auto& duel = ::g_duel_doa[this];
  const int floor_a = static_cast<int>(2 * k / 3);
  duel[0] = ::parse_ipv_env("IPV_DOA", k, ::clamp_ipv(alive, k, floor_a));
  const int floor_b = static_cast<int>(k) - 1; // most aggressive: insert at the tail
  const std::vector<int> dflt_b = ::clamp_ipv(alive, k, floor_b);
  for (int i = 1; i < MAX_DUEL_CFGS; ++i) {
    char var[32];
    std::snprintf(var, sizeof(var), "IPV_DOA_%d", i);
    const std::vector<int>& dflt = (i == 1) ? ::parse_ipv_env("IPV_DOA_B", k, dflt_b) : dflt_b;
    duel[i] = ::parse_ipv_env(var, k, dflt);
  }

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
  ::g_slot_class[this].assign(static_cast<std::size_t>(NUM_SET) * NUM_WAY, 0);
  ::g_slot_cfg_idx[this].assign(static_cast<std::size_t>(NUM_SET) * NUM_WAY, 0);
  ::g_hit_counts[this]   = {};
  ::g_miss_latency[this] = {};
  ::g_stats[this]        = Stats{};
}

uint32_t CACHE::find_victim(uint32_t triggering_cpu, uint64_t instr_id, uint32_t set, const BLOCK* current_set, uint64_t ip, uint64_t full_addr,
                             uint32_t type)
{
  const auto& order = ::g_order[this];
  return order[static_cast<std::size_t>(set) * NUM_WAY + (NUM_WAY - 1)];
}

void CACHE::update_replacement_state(uint32_t triggering_cpu, uint32_t set, uint32_t way, uint64_t full_addr, uint64_t ip, uint64_t victim_addr,
                                      uint32_t type, uint8_t hit)
{
  const std::size_t base = static_cast<std::size_t>(set) * NUM_WAY;
  uint16_t* order = ::g_order[this].data() + base;
  uint16_t* rank  = ::g_rank[this].data() + base;
  int8_t&   cls   = ::g_slot_class[this][base + way];
  uint8_t&  cfg_stored = ::g_slot_cfg_idx[this][base + way];
  auto& st = ::g_stats[this];
  const bool targeted = ::is_targeted(*this);

  const int nc   = ::g_n_configs;
  const int ns   = ::g_n_samplers;
  const int step = (targeted && nc >= 2 && ns > 0) ? static_cast<int>(NUM_SET) / ns : 0;

  if (hit) {
    if (type == WRITE) return; // store hits don't trigger promotion

    if (step > 0) {
      const int sc = ::sampler_config_of(static_cast<int>(set), step, nc);
      if (sc >= 0) {
        bool count_hit = true;
        if (::g_hit_filter == 1) count_hit = (cls != 1);
        if (::g_hit_filter == 2) count_hit = (cls == 2);
        if (count_hit) ::g_hit_counts[this][sc]++;
      }
    }

    const std::vector<int>& ipv = ipv_for_hit(cls, ::g_ipv_alive[this], ::g_duel_doa[this][cfg_stored]);
    switch (cls) {
      case 1:  st.hit_doa++; break;
      case 2:  st.hit_alive++; break;
      default: st.hit_unguided++; break;
    }
    move_to(order, rank, rank[way], ipv[rank[way]]);
  } else if (targeted) {
    int cfg = 0;
    if (step > 0) {
      const int sc = ::sampler_config_of(static_cast<int>(set), step, nc);
      cfg = (sc >= 0) ? sc : ::winner_config(this);
    }
    if (step > 0 && type != WRITE) {
      const int sc = ::sampler_config_of(static_cast<int>(set), step, nc);
      if (sc >= 0) ::g_miss_latency[this][sc] += static_cast<int64_t>(this->last_fill_latency);
    }
    cfg_stored = static_cast<uint8_t>(cfg);

    const liveness_class lc = classify_block_liveness(full_addr, ip);
    const std::vector<int>& ipv = ipv_for_insert(lc, ::g_ipv_alive[this], ::g_duel_doa[this][cfg]);
    if (lc == liveness_class::doa) { cls = 1; st.ins_doa++; } else { cls = 2; st.ins_alive++; }
    move_to(order, rank, static_cast<int>(NUM_WAY) - 1, ipv[NUM_WAY]);
  } else {
    cls = 0;
    cfg_stored = 0;
    st.ins_unguided++;
    move_to(order, rank, static_cast<int>(NUM_WAY) - 1, ::g_ipv_alive[this][NUM_WAY]);
  }
}

void CACHE::replacement_final_stats()
{
  const auto& st = ::g_stats[this];
  const uint64_t total_ins  = st.ins_unguided + st.ins_doa + st.ins_alive;
  const uint64_t guided_ins = st.ins_doa + st.ins_alive;

  auto pct = [](uint64_t n, uint64_t d) -> double { return d ? 100.0 * n / d : 0.0; };
  auto print_vec = [](const std::vector<int>& v) {
    for (std::size_t i = 0; i < v.size(); ++i) printf("%d%s", v[i], i + 1 < v.size() ? "," : "");
  };

  printf("%s IPV-Live STATS:\n", NAME.c_str());

  if (::g_n_configs >= 2) {
    const int winner = ::winner_config(this);
    const char* filt = ::g_hit_filter == 2 ? "alive" : ::g_hit_filter == 1 ? "live" : "all";
    const char* metric = ::g_duel_metric == 1 ? "latency" : "hits";
    printf("  Set dueling     : N=%d  samplers/cfg=%d  hyst=%ld  metric=%s  hit_filter=%s  winner=config_%d\n", ::g_n_configs, ::g_n_samplers, ::g_hyst,
           metric, filt, winner);
    for (int i = 0; i < ::g_n_configs; ++i) {
      printf("  Config %d%s: DoA=[", i, (i == winner ? "*" : " "));
      print_vec(::g_duel_doa[this][i]);
      printf("]  sampler_hits=%ld  miss_latency=%ld\n", ::g_hit_counts[this][i], ::g_miss_latency[this][i]);
    }
    printf("  Alive: ["); print_vec(::g_ipv_alive[this]); printf("]  (shared across configs)\n");
  } else {
    printf("  IPV_doa   : ["); print_vec(::g_duel_doa[this][0]); printf("]\n");
    printf("  IPV_alive : ["); print_vec(::g_ipv_alive[this]);   printf("]\n");
  }

  printf("  Activation rate : %.1f%%  (%lu guided / %lu total insertions)\n", pct(guided_ins, total_ins), guided_ins, total_ins);
  printf("  guided_insertions=%lu\n", guided_ins);
  printf("  Insert mix      : DoA=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n", pct(st.ins_doa, total_ins), pct(st.ins_alive, total_ins),
         pct(st.ins_unguided, total_ins));
  printf("  Hit rate/class  : DoA=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n", pct(st.hit_doa, st.ins_doa), pct(st.hit_alive, st.ins_alive),
         pct(st.hit_unguided, st.ins_unguided));
  liveness_hist.print_stats(NAME.c_str());
  printf("\n");
}
