#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>

#include "cache.h"

namespace
{
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
std::unordered_map<CACHE*, std::vector<int>>      g_ipv_doa;
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

void init_ipv_vectors(CACHE* c, std::size_t k)
{
  const std::vector<int> alive = parse_ipv_env("IPV_ALIVE", k, default_ipv(k));
  g_ipv_alive[c] = alive;

  // Floor-clamped at N-1 (locked at the tail regardless of hits): the
  // aggressive configuration won outright against a floor(2N/3) conservative
  // alternative on every suite tested, and set dueling between them only
  // ever won by a small margin overall -- so this is now the sole default,
  // still overridable via IPV_DOA for experimentation.
  const int floor = static_cast<int>(k) - 1;
  g_ipv_doa[c] = parse_ipv_env("IPV_DOA", k, clamp_ipv(alive, k, floor));
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
};

SlotContext make_slot_context(CACHE* c, uint32_t set, uint32_t num_way)
{
  const std::size_t base = static_cast<std::size_t>(set) * num_way;
  SlotContext ctx;
  ctx.order    = g_order[c].data() + base;
  ctx.rank     = g_rank[c].data() + base;
  ctx.targeted = is_targeted(*c);
  return ctx;
}

void handle_hit(CACHE* c, const SlotContext& ctx, uint32_t way, int8_t cls, Stats& st)
{
  const std::vector<int>& ipv = ipv_for_hit(cls, g_ipv_alive[c], g_ipv_doa[c]);
  record_hit(st, cls);
  move_to(ctx.order, ctx.rank, ctx.rank[way], ipv[ctx.rank[way]]);
}

int8_t handle_targeted_fill(CACHE* c, const SlotContext& ctx, uint32_t num_way, liveness_class lc, Stats& st)
{
  const std::vector<int>& ipv = ipv_for_insert(lc, g_ipv_alive[c], g_ipv_doa[c]);
  const int8_t cls = record_insertion(st, lc);
  move_to(ctx.order, ctx.rank, static_cast<int>(num_way) - 1, ipv[num_way]);
  return cls;
}

int8_t handle_unguided_fill(CACHE* c, const SlotContext& ctx, uint32_t num_way, Stats& st)
{
  st.ins_unguided++;
  move_to(ctx.order, ctx.rank, static_cast<int>(num_way) - 1, g_ipv_alive[c][num_way]);
  return 0;
}
} // namespace

void CACHE::initialize_replacement()
{
  ::init_ipv_vectors(this, NUM_WAY);
  ::init_ipv_stack(this, NUM_SET, NUM_WAY);
  ::g_slot_class[this].assign(static_cast<std::size_t>(NUM_SET) * NUM_WAY, 0);
  ::g_stats[this] = Stats{};
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
  int8_t& cls = ::g_slot_class[this][base + way];
  auto& st = ::g_stats[this];
  const ::SlotContext ctx = ::make_slot_context(this, set, NUM_WAY);

  if (hit) {
    if (type == WRITE) return; // store hits don't trigger promotion
    ::handle_hit(this, ctx, way, cls, st);
    return;
  }

  cls = ctx.targeted
      ? ::handle_targeted_fill(this, ctx, NUM_WAY, classify_block_liveness(full_addr, ip, set), st)
      : ::handle_unguided_fill(this, ctx, NUM_WAY, st);
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
  printf("  IPV_doa   : ["); print_vec(::g_ipv_doa[this]);   printf("]\n");
  printf("  IPV_alive : ["); print_vec(::g_ipv_alive[this]); printf("]\n");

  printf("  Activation rate : %.1f%%  (%lu guided / %lu total insertions)\n", pct(guided_ins, total_ins), guided_ins, total_ins);
  printf("  guided_insertions=%lu\n", guided_ins);
  printf("  Insert mix      : DoA=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n", pct(st.ins_doa, total_ins), pct(st.ins_alive, total_ins),
         pct(st.ins_unguided, total_ins));
  printf("  Hit rate/class  : DoA=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n", pct(st.hit_doa, st.ins_doa), pct(st.hit_alive, st.ins_alive),
         pct(st.hit_unguided, st.ins_unguided));
  print_pc_counter_stats(NAME.c_str());
  printf("\n");
}
