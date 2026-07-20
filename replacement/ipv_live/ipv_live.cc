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

const std::vector<int>& ipv_for_insert(liveness_class lc, const std::vector<int>& alive, const std::vector<int>& doa)
{
  return (lc == liveness_class::doa) ? doa : alive;
}
const std::vector<int>& ipv_for_hit(int8_t cls, const std::vector<int>& alive, const std::vector<int>& doa)
{
  return (cls == 1) ? doa : alive;
}

// --- Set dueling ------------------------------------------------------
std::unordered_map<CACHE*, std::array<std::vector<int>, MAX_DUEL_CFGS>> g_duel_doa;
std::unordered_map<CACHE*, std::vector<uint8_t>>               g_slot_cfg_idx; // duel config active at insertion
std::unordered_map<CACHE*, std::array<int64_t, MAX_DUEL_CFGS>> g_hit_counts;
std::unordered_map<CACHE*, std::array<int64_t, MAX_DUEL_CFGS>> g_miss_latency;

int g_n_configs   = -1;
int g_n_samplers  = -1;
int g_hit_filter  = -1;
int g_duel_metric = -1;
int64_t g_hyst    = -1;

int parse_env_int(const char* var, int dflt)
{
  const char* e = std::getenv(var);
  return (e && *e) ? std::atoi(e) : dflt;
}

int64_t parse_env_i64(const char* var, int64_t dflt)
{
  const char* e = std::getenv(var);
  return (e && *e) ? static_cast<int64_t>(std::atoll(e)) : dflt;
}

int parse_n_configs(int n_samplers)
{
  int n = parse_env_int("DUEL_N_CONFIGS", 0);
  if (n < 2 && n_samplers > 0) n = 2;
  return std::min(n, MAX_DUEL_CFGS);
}

int parse_hit_filter()
{
  const char* hf = std::getenv("DUEL_HIT_FILTER");
  if (!hf || !*hf) return 0;
  if (std::strcmp(hf, "alive") == 0 || std::strcmp(hf, "2") == 0) return 2;
  if (std::strcmp(hf, "live")  == 0 || std::strcmp(hf, "1") == 0) return 1;
  return 0;
}

int parse_duel_metric()
{
  const char* dm = std::getenv("DUEL_METRIC");
  return (dm && (std::strcmp(dm, "latency") == 0 || std::strcmp(dm, "1") == 0)) ? 1 : 0;
}

void ensure_parsed_duel()
{
  if (g_n_configs >= 0) return;
  g_n_samplers  = parse_env_int("DUEL_N_SAMPLERS", 0);
  g_n_configs   = parse_n_configs(g_n_samplers);
  g_hyst        = parse_env_i64("DUEL_HYST", 0);
  g_hit_filter  = parse_hit_filter();
  g_duel_metric = parse_duel_metric();
}

int best_config_by_metric(const std::array<int64_t, MAX_DUEL_CFGS>& m, int n_configs, bool lat)
{
  int best = 0;
  for (int i = 1; i < n_configs; ++i) {
    const bool better = lat ? (m[i] < m[best]) : (m[i] > m[best]);
    if (better) best = i;
  }
  return best;
}

bool clears_hysteresis(const std::array<int64_t, MAX_DUEL_CFGS>& m, int n_configs, bool lat, int best, int64_t hyst)
{
  for (int i = 0; i < n_configs; ++i) {
    if (i == best) continue;
    const int64_t margin = lat ? (m[i] - m[best]) : (m[best] - m[i]);
    if (margin <= hyst) return false;
  }
  return true;
}

int winner_config(CACHE* c)
{
  const bool lat = (g_duel_metric == 1);
  const auto& m = lat ? g_miss_latency[c] : g_hit_counts[c];
  const int best = best_config_by_metric(m, g_n_configs, lat);
  if (g_hyst > 0 && !clears_hysteresis(m, g_n_configs, lat, best, g_hyst)) return 0;
  return best;
}

int sampler_config_of(int set, int step, int n_configs)
{
  const int j = set % step;
  for (int i = 0; i < n_configs; ++i)
    if (j == (i * step) / n_configs) return i;
  return -1;
}

bool should_count_hit(int8_t cls, int hit_filter)
{
  if (hit_filter == 1) return cls != 1;
  if (hit_filter == 2) return cls == 2;
  return true;
}

int duel_step(bool targeted, int n_configs, int n_samplers, uint32_t num_set)
{
  return (targeted && n_configs >= 2 && n_samplers > 0) ? static_cast<int>(num_set) / n_samplers : 0;
}

struct FillConfig { int cfg; int sampler_idx; };
FillConfig decide_fill_config(CACHE* c, int set, int step, int n_configs)
{
  if (step <= 0) return {0, -1};
  const int sc = sampler_config_of(set, step, n_configs);
  return {(sc >= 0) ? sc : winner_config(c), sc};
}

void update_duel_hit_signal(CACHE* c, int set, int step, int n_configs, int8_t cls, int hit_filter)
{
  if (step <= 0) return;
  const int sc = sampler_config_of(set, step, n_configs);
  if (sc >= 0 && should_count_hit(cls, hit_filter)) g_hit_counts[c][sc]++;
}

void record_fill_latency(CACHE* c, int sampler_idx, uint32_t type, int64_t fill_latency)
{
  if (type != WRITE && sampler_idx >= 0) g_miss_latency[c][sampler_idx] += fill_latency;
}

void init_duel_doa_configs(std::array<std::vector<int>, MAX_DUEL_CFGS>& duel, std::size_t k, const std::vector<int>& dflt_b)
{
  for (int i = 1; i < MAX_DUEL_CFGS; ++i) {
    char var[32];
    std::snprintf(var, sizeof(var), "IPV_DOA_%d", i);
    const std::vector<int>& dflt = (i == 1) ? parse_ipv_env("IPV_DOA_B", k, dflt_b) : dflt_b;
    duel[i] = parse_ipv_env(var, k, dflt);
  }
}
// --- end set dueling ----------------------------------------------------

void init_ipv_vectors(CACHE* c, std::size_t k)
{
  const std::vector<int> alive = parse_ipv_env("IPV_ALIVE", k, default_ipv(k));
  g_ipv_alive[c] = alive;

  auto& duel = g_duel_doa[c];
  const int floor_a = static_cast<int>(2 * k / 3);
  duel[0] = parse_ipv_env("IPV_DOA", k, clamp_ipv(alive, k, floor_a));
  const int floor_b = static_cast<int>(k) - 1; // most aggressive: insert at the tail
  init_duel_doa_configs(duel, k, clamp_ipv(alive, k, floor_b));
}

void init_ipv_stack(CACHE* c, uint32_t num_set, uint32_t num_way)
{
  auto& order = g_order[c];
  auto& rank  = g_rank[c];
  const std::size_t n = static_cast<std::size_t>(num_set) * num_way;
  order.assign(n, 0);
  rank.assign(n, 0);
  for (std::size_t s = 0; s < num_set; ++s) {
    for (std::size_t w = 0; w < num_way; ++w) {
      order[s * num_way + w] = static_cast<uint16_t>(w);
      rank [s * num_way + w] = static_cast<uint16_t>(w);
    }
  }
}

void record_hit(Stats& st, int8_t cls)
{
  switch (cls) {
    case 1:  st.hit_doa++; break;
    case 2:  st.hit_alive++; break;
    default: st.hit_unguided++; break;
  }
}

int8_t record_insertion(Stats& st, liveness_class lc)
{
  if (lc == liveness_class::doa) { st.ins_doa++; return 1; }
  st.ins_alive++;
  return 2;
}

struct SlotContext {
  uint16_t* order;
  uint16_t* rank;
  bool targeted;
  int  n_configs;
  int  step;
};

SlotContext make_slot_context(CACHE* c, uint32_t set, uint32_t num_set, uint32_t num_way)
{
  const std::size_t base = static_cast<std::size_t>(set) * num_way;
  SlotContext ctx;
  ctx.order     = g_order[c].data() + base;
  ctx.rank      = g_rank[c].data() + base;
  ctx.targeted  = is_targeted(*c);
  ctx.n_configs = g_n_configs;
  ctx.step      = duel_step(ctx.targeted, ctx.n_configs, g_n_samplers, num_set);
  return ctx;
}

void handle_hit(CACHE* c, const SlotContext& ctx, uint32_t set, uint32_t way, int8_t cls, uint8_t cfg_stored, Stats& st)
{
  update_duel_hit_signal(c, static_cast<int>(set), ctx.step, ctx.n_configs, cls, g_hit_filter);
  const std::vector<int>& ipv = ipv_for_hit(cls, g_ipv_alive[c], g_duel_doa[c][cfg_stored]);
  record_hit(st, cls);
  move_to(ctx.order, ctx.rank, ctx.rank[way], ipv[ctx.rank[way]]);
}

struct FillOutcome { int8_t cls; uint8_t cfg_stored; };

FillOutcome handle_targeted_fill(CACHE* c, const SlotContext& ctx, uint32_t set, uint32_t num_way, liveness_class lc, uint32_t type,
                                  int64_t fill_latency, Stats& st)
{
  const FillConfig fc = decide_fill_config(c, static_cast<int>(set), ctx.step, ctx.n_configs);
  record_fill_latency(c, fc.sampler_idx, type, fill_latency);

  const std::vector<int>& ipv = ipv_for_insert(lc, g_ipv_alive[c], g_duel_doa[c][fc.cfg]);
  const int8_t cls = record_insertion(st, lc);
  move_to(ctx.order, ctx.rank, static_cast<int>(num_way) - 1, ipv[num_way]);
  return {cls, static_cast<uint8_t>(fc.cfg)};
}

FillOutcome handle_unguided_fill(CACHE* c, const SlotContext& ctx, uint32_t num_way, Stats& st)
{
  st.ins_unguided++;
  move_to(ctx.order, ctx.rank, static_cast<int>(num_way) - 1, g_ipv_alive[c][num_way]);
  return {0, 0};
}
} // namespace

void CACHE::initialize_replacement()
{
  ::ensure_parsed_duel();
  ::init_ipv_vectors(this, NUM_WAY);
  ::init_ipv_stack(this, NUM_SET, NUM_WAY);
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
  int8_t&  cls        = ::g_slot_class[this][base + way];
  uint8_t& cfg_stored = ::g_slot_cfg_idx[this][base + way];
  auto& st = ::g_stats[this];
  const ::SlotContext ctx = ::make_slot_context(this, set, NUM_SET, NUM_WAY);

  if (hit) {
    if (type == WRITE) return; // store hits don't trigger promotion
    ::handle_hit(this, ctx, set, way, cls, cfg_stored, st);
    return;
  }

  const ::FillOutcome outcome = ctx.targeted
      ? ::handle_targeted_fill(this, ctx, set, NUM_WAY, classify_block_liveness(full_addr, ip), type,
                                static_cast<int64_t>(this->last_fill_latency), st)
      : ::handle_unguided_fill(this, ctx, NUM_WAY, st);
  cls        = outcome.cls;
  cfg_stored = outcome.cfg_stored;
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
