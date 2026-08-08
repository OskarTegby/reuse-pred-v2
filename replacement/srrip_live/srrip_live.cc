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

constexpr int maxRRPV = 3;

bool liveness_enabled_for(const CACHE& c)
{
  const char* target_env = std::getenv("SRRIP_LIVE_TARGET");
  if (!target_env || target_env[0] == '\0' || std::string(target_env) == "llc")
    return c.NAME == "LLC";
  if (std::string(target_env) == "none")
    return false;
  std::string want = target_env;
  for (auto& ch : want) ch = static_cast<char>(std::toupper(static_cast<unsigned char>(ch)));
  return c.NAME == want || c.NAME == ("cpu0_" + want);
}

std::unordered_map<CACHE*, std::vector<int>>      rrpv_values;
std::unordered_map<CACHE*, std::vector<int8_t>>   slot_class;
std::unordered_map<CACHE*, std::vector<uint64_t>> install_cycle;

struct Stats {
  uint64_t ins_unguided = 0, ins_doa = 0, ins_alive = 0;
  uint64_t hit_unguided = 0, hit_doa = 0, hit_alive = 0;
  std::array<uint64_t, 4> evict_rrpv_doa = {}, evict_rrpv_alive = {}, evict_rrpv_unguided = {};
  uint64_t aging_loops = 0;
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

int doa_ins_rrpv() { if (g_doa_ins_rrpv < 0) g_doa_ins_rrpv = parse_env_rrpv("SRRIP_DOA_INS_RRPV", 3); return g_doa_ins_rrpv; }
int doa_hit_rrpv() { if (g_doa_hit_rrpv < 0) g_doa_hit_rrpv = parse_env_rrpv("SRRIP_DOA_HIT_RRPV", 0); return g_doa_hit_rrpv; }

int rrpv_for_insert(liveness_class lc)
{
  if (lc != liveness_class::doa) return maxRRPV - 1;
  return doa_ins_rrpv();
}
int rrpv_for_hit(int8_t cls)
{
  if (cls != 1) return 0;
  return doa_hit_rrpv();
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

void handle_hit(int& rrpv, int8_t cls, uint32_t type, Stats& st)
{
  if (type != WRITE) rrpv = rrpv_for_hit(cls);
  record_hit(st, cls);
}

int8_t handle_fill(int& rrpv, liveness_class lc, Stats& st)
{
  rrpv = rrpv_for_insert(lc);
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
  ::rrpv_values[this]    = std::vector<int>(n, ::maxRRPV);
  ::slot_class[this]     = std::vector<int8_t>(n, 0);
  ::install_cycle[this]  = std::vector<uint64_t>(n, 0);
  ::stats[this]          = Stats{};
  (void)doa_ins_rrpv(); (void)doa_hit_rrpv();
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

  return static_cast<uint32_t>(std::distance(begin, victim));
}

void CACHE::update_replacement_state(uint32_t triggering_cpu, uint32_t set, uint32_t way, uint64_t full_addr, uint64_t ip, uint64_t victim_addr,
                                      uint32_t type, uint8_t hit)
{
  const std::size_t idx = set * NUM_WAY + way;
  auto& rrpv = ::rrpv_values[this][idx];
  auto& cls  = ::slot_class[this][idx];
  auto& inst = ::install_cycle[this][idx];
  auto& st   = ::stats[this];

  if (!::liveness_enabled_for(*this)) {
    if (!hit && inst != 0) {
      ::record_eviction(st, cls, rrpv);
      ::record_lifespan(st, cls, inst, current_cycle);
    }
    ::handle_unguided(rrpv, cls, hit, type, st);
    if (!hit) inst = current_cycle;
    return;
  }

  if (hit) {
    ::handle_hit(rrpv, cls, type, st);
    return;
  }

  if (inst != 0) {
    ::record_eviction(st, cls, rrpv);
    ::record_lifespan(st, cls, inst, current_cycle);
  }
  const liveness_class lc = classify_block_liveness(full_addr, ip);
  cls = ::handle_fill(rrpv, lc, st);
  inst = current_cycle;
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
  printf("  DoA ins RRPV     : %d  (SRRIP_DOA_INS_RRPV; default 3)\n", ::doa_ins_rrpv());
  printf("  DoA hit RRPV     : %d  (SRRIP_DOA_HIT_RRPV; default 0)\n", ::doa_hit_rrpv());
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
