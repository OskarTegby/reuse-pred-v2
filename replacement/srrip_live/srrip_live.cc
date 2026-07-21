#include <array>
#include <cassert>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include "cache.h"
#include "../srrip_common.h"

namespace
{
#include "../duel_common.h"

constexpr int maxRRPV = 3;

// SRRIP_LIVE_TARGET=none explicitly disables liveness guidance while still
// on the LLC (used by the "bypass" condition: raw DoA bypass stays active in
// cache.cc, but insertion/promotion here falls back to plain SRRIP). Liveness
// guidance never applies anywhere but the LLC.
bool liveness_enabled_for(const CACHE& c)
{
  const char* target_env = std::getenv("SRRIP_LIVE_TARGET");
  const bool disabled = target_env && target_env[0] != '\0' && std::string(target_env) != "llc";
  return (c.NAME == "LLC") && !disabled;
}

std::unordered_map<CACHE*, std::vector<int>>    rrpv_values;
std::unordered_map<CACHE*, std::vector<int8_t>> slot_class; // 0=unguided 1=doa 2=alive

struct Stats {
  uint64_t ins_unguided = 0, ins_doa = 0, ins_alive = 0;
  uint64_t hit_unguided = 0, hit_doa = 0, hit_alive = 0;
  std::array<uint64_t, 4> evict_rrpv_doa = {}, evict_rrpv_alive = {}, evict_rrpv_unguided = {};
  uint64_t aging_loops = 0;
  uint64_t sampler_a_hits = 0, sampler_b_hits = 0;
  // Cycles ins->evict per insertion class; [0]=unguided [1]=doa [2]=alive
  std::array<uint64_t, 3> lifespan_sum = {}, lifespan_count = {};
};
std::unordered_map<CACHE*, Stats> stats;

int g_doa_ins_rrpv = -1;
int g_doa_hit_rrpv = -1;

int parse_env_rrpv(const char* var, int dflt)
{
  const char* e = std::getenv(var);
  return (e && *e) ? std::atoi(e) : dflt;
}

int doa_ins_rrpv() { if (g_doa_ins_rrpv < 0) g_doa_ins_rrpv = parse_env_rrpv("SRRIP_DOA_INS_RRPV", 2); return g_doa_ins_rrpv; }
int doa_hit_rrpv() { if (g_doa_hit_rrpv < 0) g_doa_hit_rrpv = parse_env_rrpv("SRRIP_DOA_HIT_RRPV", 2); return g_doa_hit_rrpv; }

// --- Set dueling ------------------------------------------------------
std::unordered_map<CACHE*, PselState>            duel;
std::unordered_map<CACHE*, std::vector<uint8_t>> slot_cfg_b;

int g_duel_metric = -1;  // 0=hits (PSEL), 1=latency (argmin)
int g_doa_ins_b = -1, g_doa_hit_b = -1;
int     g_n_samplers = -1;
int64_t g_hyst       = -1;  // cfgB must lead cfgA by this margin to win followers

int doa_ins_b() { if (g_doa_ins_b < 0) g_doa_ins_b = parse_env_rrpv("SRRIP_DOA_INS_RRPV_B", 3); return g_doa_ins_b; }
int doa_hit_b() { if (g_doa_hit_b < 0) g_doa_hit_b = parse_env_rrpv("SRRIP_DOA_HIT_RRPV_B", 0); return g_doa_hit_b; }
int n_samplers()
{
  if (g_n_samplers < 0) {
    const char* e = std::getenv("DUEL_N_SAMPLERS");
    g_n_samplers = (e && *e) ? std::atoi(e) : 0;
  }
  return g_n_samplers;
}
int64_t hyst()
{
  if (g_hyst < 0) {
    const char* e = std::getenv("DUEL_HYST");
    g_hyst = (e && *e) ? static_cast<int64_t>(std::atoll(e)) : 0;
  }
  return g_hyst;
}
int duel_metric()
{
  if (g_duel_metric < 0) {
    const char* e = std::getenv("DUEL_METRIC");
    g_duel_metric = (e && (std::string(e) == "latency" || std::string(e) == "1")) ? 1 : 0;
  }
  return g_duel_metric;
}

struct DuelContext { SamplerRole role; bool use_b; };

DuelContext make_duel_context(CACHE* c, Stats& st, uint32_t set, uint32_t num_set, bool hit, uint32_t type, int64_t fill_latency)
{
  DuelContext ctx;
  ctx.role = sampler_role(set, num_set, n_samplers());
  const bool use_latency = (duel_metric() == 1);
  auto& d = duel[c];
  psel_update(d, ctx.role, use_latency, hit, type, fill_latency);
  if (!use_latency && hit && type != WRITE) {
    if (ctx.role.is_a) st.sampler_a_hits++;
    if (ctx.role.is_b) st.sampler_b_hits++;
  }
  ctx.use_b = ctx.role.is_b || (!ctx.role.is_a && ctx.role.dueling && psel_b_wins(d, use_latency, hyst()));
  return ctx;
}
// --- end set dueling ----------------------------------------------------

int rrpv_for_insert(liveness_class lc, bool use_cfg_b)
{
  if (lc != liveness_class::doa) return maxRRPV - 1;
  return use_cfg_b ? doa_ins_b() : doa_ins_rrpv();
}
int rrpv_for_hit(int8_t cls, bool use_cfg_b)
{
  if (cls != 1) return 0;
  return use_cfg_b ? doa_hit_b() : doa_hit_rrpv();
}

void record_hit(Stats& st, int8_t cls)
{
  if (cls == 1) st.hit_doa++; else st.hit_alive++;
}

int8_t record_insertion(Stats& st, liveness_class lc)
{
  if (lc == liveness_class::doa) { st.ins_doa++; return 1; }
  st.ins_alive++;
  return 2;
}

void record_eviction(Stats& st, int8_t cls, int rrpv)
{
  switch (cls) {
    case 1:  st.evict_rrpv_doa[rrpv]++; break;
    case 2:  st.evict_rrpv_alive[rrpv]++; break;
    default: st.evict_rrpv_unguided[rrpv]++; break;
  }
}

void record_lifespan(Stats& st, int8_t cls, uint64_t ins_cycle, uint64_t current_cycle)
{
  if (ins_cycle == 0 || current_cycle < ins_cycle) return;
  const int ci = (cls >= 0 && cls <= 2) ? cls : 0;
  st.lifespan_sum[ci] += current_cycle - ins_cycle;
  st.lifespan_count[ci] += 1;
}

void handle_hit(int& rrpv, int8_t cls, uint8_t cfg_b, uint32_t type, Stats& st)
{
  // Use the config stored at insertion time — do not re-classify.
  if (type != WRITE) rrpv = rrpv_for_hit(cls, cfg_b);
  record_hit(st, cls);
}

int8_t handle_fill(int& rrpv, liveness_class lc, bool use_b, Stats& st)
{
  rrpv = rrpv_for_insert(lc, use_b);
  return record_insertion(st, lc);
}

void handle_unguided(int& rrpv, int8_t& cls, bool hit, uint32_t type, Stats& st)
{
  if (hit) { if (type != WRITE) rrpv = 0; st.hit_unguided++; }
  else     { rrpv = maxRRPV - 1; cls = 0; st.ins_unguided++; }
}
} // namespace

void CACHE::initialize_replacement()
{
  const std::size_t n = NUM_SET * NUM_WAY;
  ::rrpv_values[this] = std::vector<int>(n, ::maxRRPV);
  ::slot_class[this]  = std::vector<int8_t>(n, 0);
  ::slot_cfg_b[this]  = std::vector<uint8_t>(n, 0);
  ::stats[this]       = Stats{};
  ::duel[this]        = PselState{};
  (void)doa_ins_rrpv(); (void)doa_hit_rrpv();
  (void)doa_ins_b();    (void)doa_hit_b();
  (void)n_samplers();   (void)duel_metric();  (void)hyst();
}

uint32_t CACHE::find_victim(uint32_t triggering_cpu, uint64_t instr_id, uint32_t set, const BLOCK* current_set, uint64_t ip, uint64_t full_addr,
                             uint32_t type)
{
  auto begin  = std::next(std::begin(::rrpv_values[this]), set * NUM_WAY);
  auto end    = std::next(begin, NUM_WAY);
  auto& st    = ::stats[this];
  auto victim = srrip_common::find_rrpv_victim(begin, end, ::maxRRPV, [&] { ++st.aging_loops; });
  assert(begin <= victim);
  assert(victim < end);

  const uint32_t way = static_cast<uint32_t>(std::distance(begin, victim));
  const std::size_t idx = set * NUM_WAY + way;
  const int8_t cls  = ::slot_class[this][idx];
  const int    rrpv = ::rrpv_values[this][idx];

  ::record_eviction(st, cls, rrpv);
  ::record_lifespan(st, cls, current_set[way].install_cycle, current_cycle);
  return way;
}

void CACHE::update_replacement_state(uint32_t triggering_cpu, uint32_t set, uint32_t way, uint64_t full_addr, uint64_t ip, uint64_t victim_addr,
                                      uint32_t type, uint8_t hit)
{
  // NOTE: plain SRRIP promotes every hit (including write hits) to RRPV 0. We
  // deliberately do NOT special-case write hits here, so that when liveness
  // provides no signal (block defaults to alive), this policy behaves
  // identically to baseline SRRIP -- any speedup is then attributable to
  // liveness guidance alone.
  const std::size_t idx = set * NUM_WAY + way;
  auto& rrpv = ::rrpv_values[this][idx];
  auto& cls  = ::slot_class[this][idx];
  auto& st   = ::stats[this];

  if (!::liveness_enabled_for(*this)) {
    ::handle_unguided(rrpv, cls, hit, type, st);
    return;
  }

  const bool use_b = duel_bypass_enabled
      ? true
      : ::make_duel_context(this, st, set, NUM_SET, hit, type, static_cast<int64_t>(this->last_fill_latency)).use_b;
  auto& cfg_b = ::slot_cfg_b[this][idx];

  if (hit) {
    ::handle_hit(rrpv, cls, cfg_b, type, st);
  } else {
    const liveness_class lc = classify_block_liveness(full_addr, ip);
    cfg_b = use_b;
    cls = ::handle_fill(rrpv, lc, use_b, st);
  }
}

void CACHE::replacement_final_stats()
{
  const auto& st = ::stats[this];
  const uint64_t total_ins  = st.ins_unguided + st.ins_doa + st.ins_alive;
  const uint64_t guided_ins = st.ins_doa + st.ins_alive;

  auto pct = [](uint64_t n, uint64_t d) -> double { return d ? 100.0 * n / d : 0.0; };
  auto tot = [](const std::array<uint64_t, 4>& a) { return a[0] + a[1] + a[2] + a[3]; };

  const uint64_t evict_doa   = tot(st.evict_rrpv_doa);
  const uint64_t evict_alive = tot(st.evict_rrpv_alive);
  const uint64_t evict_ung   = tot(st.evict_rrpv_unguided);
  const uint64_t evict_total = evict_doa + evict_alive + evict_ung;

  printf("%s SRRIP-Live STATS:\n", NAME.c_str());
  if (::n_samplers() > 0) {
    const bool lat = (::duel_metric() == 1);
    const auto& d = ::duel[this];
    const bool b_wins = ::psel_b_wins(d, lat, ::hyst());
    if (lat) {
      printf("  Set dueling      : metric=latency  winner=%s  lat_a=%ld  lat_b=%ld\n", b_wins ? "config_B" : "config_A", d.miss_lat_a,
             d.miss_lat_b);
    } else {
      printf("  Set dueling      : metric=hits  PSEL=%d/%d  winner=%s  sampler_a_hits=%lu  sampler_b_hits=%lu\n", d.psel, ::PSEL_MAX,
             b_wins ? "config_B" : "config_A", st.sampler_a_hits, st.sampler_b_hits);
    }
    printf("  Config A: DoA ins=%d hit=%d\n", ::doa_ins_rrpv(), ::doa_hit_rrpv());
    printf("  Config B: DoA ins=%d hit=%d  (SRRIP_DOA_INS_RRPV_B / _HIT_RRPV_B)\n", ::doa_ins_b(), ::doa_hit_b());
  } else {
    printf("  DoA ins RRPV     : %d  (SRRIP_DOA_INS_RRPV; 2=default, 3=legacy)\n", ::doa_ins_rrpv());
    printf("  DoA hit RRPV     : %d  (SRRIP_DOA_HIT_RRPV; 2=reset-to-ins, 1=mild)\n", ::doa_hit_rrpv());
  }
  printf("  Activation rate  : %.1f%%  (%lu guided / %lu total insertions)\n", pct(guided_ins, total_ins), guided_ins, total_ins);
  printf("  guided_insertions=%lu\n", guided_ins);
  printf("  Insert mix       : DoA=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n", pct(st.ins_doa, total_ins), pct(st.ins_alive, total_ins),
         pct(st.ins_unguided, total_ins));
  printf("  Hit rate/class   : DoA=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n", pct(st.hit_doa, st.ins_doa), pct(st.hit_alive, st.ins_alive),
         pct(st.hit_unguided, st.ins_unguided));
  printf("  RRPV@evict DoA   : [0]=%.1f%% [1]=%.1f%% [2]=%.1f%% [3]=%.1f%%  (ideal: ~100%% at [%d])\n", pct(st.evict_rrpv_doa[0], evict_doa),
         pct(st.evict_rrpv_doa[1], evict_doa), pct(st.evict_rrpv_doa[2], evict_doa), pct(st.evict_rrpv_doa[3], evict_doa), ::maxRRPV);
  printf("  RRPV@evict Alive : [0]=%.1f%% [1]=%.1f%% [2]=%.1f%% [3]=%.1f%%  (ideal: low RRPV after promotion)\n", pct(st.evict_rrpv_alive[0], evict_alive),
         pct(st.evict_rrpv_alive[1], evict_alive), pct(st.evict_rrpv_alive[2], evict_alive), pct(st.evict_rrpv_alive[3], evict_alive));
  printf("  Aging loops      : %lu  (%.2f per eviction)\n", st.aging_loops, pct(st.aging_loops, evict_total) / 100.0);

  auto avg_life = [&](int ci) -> double { return st.lifespan_count[ci] ? static_cast<double>(st.lifespan_sum[ci]) / st.lifespan_count[ci] : 0.0; };
  printf("  Avg lifespan(cy) : DoA=%.0f  Alive=%.0f  Unguided=%.0f\n", avg_life(1), avg_life(2), avg_life(0));

  print_pc_counter_stats(NAME.c_str());
  printf("\n");
}
