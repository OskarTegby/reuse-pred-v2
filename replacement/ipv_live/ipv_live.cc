// ipv_live.cc — Insertion/Promotion Vector replacement (Jimenez, MICRO 2013),
// with per-block liveness guidance and optional 2-way set dueling.
//
// Each set is a strict permutation of positions 0..k-1 (0 = most protected).
// V[p] = promotion target on a hit at position p; V[k] = insertion position.
// Both hit and miss are the same move_to() shift (see US Patent 12,222,875 B1
// Fig. 3, which also confirms demotion, V[p] > p, is valid).
//
// Base vector (k=16) is Jimenez's WI-GIPPR (paper Sec 5.3): 3.68% over LRU.
// Other k falls back to the trivial (LRU-equivalent) vector.
//
// classify_block_liveness() picks DoA/mostly-dead/mostly-alive per block at
// insertion, each with its own IPV. Mostly-alive is the base vector as-is.
// DoA/mostly-dead clamp it to a floor (V_class[p] = max(base[p], floor),
// insert @ floor) — this project's PACIPV work found and enforced
// doa[k] >= mostly_dead[k] >= mostly_alive[k] (commit 9359d45606b4).
// Floors: DoA = floor(2k/3), mostly-dead = floor(k/2).
//
// Set dueling (DUEL_N_SAMPLERS=N, SRRIP-Live-style): sampler-A sets always use
// config A's vectors, sampler-B sets config B's; followers adopt the current
// winner. DUEL_METRIC=hits (PSEL on sampler demand hits) or latency (argmin of
// accumulated miss-fill latency). DUEL_HYST = lead required before followers
// switch to B. The config in force at insertion is stored per slot so later
// hits replay the same config.
//
// SRRIP_LIVE_TARGET=llc|stlb|both gates which cache uses guidance at all.
// Overrides (k+1 ints): config A = IPV_VECTOR (base), IPV_DOA,
// IPV_MOSTLY_DEAD, IPV_MOSTLY_ALIVE; config B = the same names with a _B
// suffix. IPV_VECTOR_B defaults to config A's base; each B class vector
// defaults to the standard derivation from B's base.

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

const std::vector<int> kDefaultIpv16 = {
    0, 0, 2, 8, 4, 1, 4, 1, 8, 0, 14, 8, 12, 13, 14, 9, 5
};

std::vector<int> trivial_ipv(std::size_t k)
{
  std::vector<int> v(k + 1, 0);
  v[k] = static_cast<int>(k) - 1;
  return v;
}

std::vector<int> default_ipv(std::size_t k)
{
  if (k == 16) return kDefaultIpv16;
  return trivial_ipv(k);
}

// Parses `var` for a k-way cache; falls back to `dflt` if unset, malformed,
// wrong length, or containing an out-of-range position.
std::vector<int> parse_ipv_env(const char* var, std::size_t k, const std::vector<int>& dflt)
{
  const char* s = std::getenv(var);
  if (!s || !*s) return dflt;
  std::string buf(s);
  std::vector<int> v;
  v.reserve(k + 1);
  char* tok = std::strtok(buf.data(), ",: ");
  while (tok) {
    v.push_back(std::atoi(tok));
    tok = std::strtok(nullptr, ",: ");
  }
  if (v.size() != k + 1) return dflt;
  for (int p : v) if (p < 0 || p >= static_cast<int>(k)) return dflt;
  return v;
}

// Clamps `base`'s promotion targets to `floor`, inserting at `floor`.
std::vector<int> clamp_ipv(const std::vector<int>& base, std::size_t k, int floor)
{
  std::vector<int> v(k + 1);
  for (std::size_t p = 0; p < k; ++p) v[p] = std::max(base[p], floor);
  v[k] = floor;
  return v;
}

bool is_targeted(const CACHE& c)
{
  const char* target_env = std::getenv("SRRIP_LIVE_TARGET");
  if (target_env && target_env[0] != '\0') {
    const std::string t(target_env);
    if (t == "llc")  return c.NAME == "LLC";
    if (t == "stlb") return c.NAME == "cpu0_STLB";
    if (t == "both") return c.NAME == "LLC" || c.NAME == "cpu0_STLB";
    return false;
  }
  return c.NAME == "LLC";
}

// Moves the block at position `from` to position `to`, shifting the blocks
// in between by one to close the gap. `order[p]` = way at position p;
// `rank[w]` = position of way w. Both are kept in sync.
void move_to(uint16_t* order, uint16_t* rank, int from, int to)
{
  if (from == to) return;
  const uint16_t way = order[from];
  if (to < from) {
    for (int p = from; p > to; --p) { order[p] = order[p - 1]; rank[order[p]] = static_cast<uint16_t>(p); }
  } else {
    for (int p = from; p < to; ++p) { order[p] = order[p + 1]; rank[order[p]] = static_cast<uint16_t>(p); }
  }
  order[to] = way;
  rank[way] = static_cast<uint16_t>(to);
}

struct ConfigVectors {
  std::vector<int> doa, md, ma;
};

struct Stats {
  uint64_t hits = 0, misses = 0;
  std::vector<uint64_t> hit_pos_hist;  // hist[p] = hits seen while block was at position p
  uint64_t ins_doa = 0, ins_md = 0, ins_ma = 0, ins_unguided = 0;
  uint64_t hit_doa = 0, hit_md = 0, hit_ma = 0, hit_unguided = 0;
  uint64_t sampler_a_hits = 0, sampler_b_hits = 0;
};

constexpr int PSEL_BITS = 10;
constexpr int PSEL_MAX  = (1 << PSEL_BITS) - 1;
constexpr int PSEL_MID  = 1 << (PSEL_BITS - 1);

// 0=unguided(trivial)  1=doa  2=mostly_dead  3=mostly_alive
std::unordered_map<CACHE*, ConfigVectors>          g_cfg_a;
std::unordered_map<CACHE*, ConfigVectors>          g_cfg_b;
std::unordered_map<CACHE*, std::vector<int>>       g_ipv_trivial;  // LRU-equivalent fallback for untargeted caches
std::unordered_map<CACHE*, std::vector<uint16_t>>  g_order;        // set*NUM_WAY + position -> way
std::unordered_map<CACHE*, std::vector<uint16_t>>  g_rank;         // set*NUM_WAY + way -> position
std::unordered_map<CACHE*, std::vector<int8_t>>    g_slot_class;   // set*NUM_WAY + way -> class at insertion
std::unordered_map<CACHE*, std::vector<uint8_t>>   g_slot_cfg_b;   // set*NUM_WAY + way -> config B at insertion
std::unordered_map<CACHE*, int>                    g_psel;
std::unordered_map<CACHE*, int64_t>                g_miss_lat_a;
std::unordered_map<CACHE*, int64_t>                g_miss_lat_b;
std::unordered_map<CACHE*, Stats>                  g_stats;

int g_n_samplers = -1;
int g_duel_metric = -1;  // 0=hits, 1=latency
int64_t g_hyst = -1;

int n_samplers()
{
  if (g_n_samplers < 0) {
    const char* e = std::getenv("DUEL_N_SAMPLERS");
    g_n_samplers = (e && *e) ? std::atoi(e) : 0;
  }
  return g_n_samplers;
}

int duel_metric()
{
  if (g_duel_metric < 0) {
    const char* e = std::getenv("DUEL_METRIC");
    g_duel_metric = (e && (std::string(e) == "latency" || std::string(e) == "1")) ? 1 : 0;
  }
  return g_duel_metric;
}

int64_t hyst()
{
  if (g_hyst < 0) {
    const char* e = std::getenv("DUEL_HYST");
    g_hyst = (e && *e) ? static_cast<int64_t>(std::atoll(e)) : 0;
  }
  return g_hyst;
}

} // namespace

void CACHE::initialize_replacement()
{
  const std::size_t k = NUM_WAY;

  const std::vector<int> base_a = ::parse_ipv_env("IPV_VECTOR", k, ::default_ipv(k));
  ConfigVectors a;
  a.doa = ::parse_ipv_env("IPV_DOA",          k, ::clamp_ipv(base_a, k, static_cast<int>(2 * k / 3)));
  a.md  = ::parse_ipv_env("IPV_MOSTLY_DEAD",  k, ::clamp_ipv(base_a, k, static_cast<int>(k / 2)));
  a.ma  = ::parse_ipv_env("IPV_MOSTLY_ALIVE", k, base_a);
  ::g_cfg_a[this] = a;

  const std::vector<int> base_b = ::parse_ipv_env("IPV_VECTOR_B", k, base_a);
  ConfigVectors b;
  b.doa = ::parse_ipv_env("IPV_DOA_B",          k, ::clamp_ipv(base_b, k, static_cast<int>(2 * k / 3)));
  b.md  = ::parse_ipv_env("IPV_MOSTLY_DEAD_B",  k, ::clamp_ipv(base_b, k, static_cast<int>(k / 2)));
  b.ma  = ::parse_ipv_env("IPV_MOSTLY_ALIVE_B", k, base_b);
  ::g_cfg_b[this] = b;

  ::g_ipv_trivial[this] = ::trivial_ipv(k);

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
  ::g_slot_cfg_b[this].assign(static_cast<std::size_t>(NUM_SET) * NUM_WAY, 0);
  ::g_psel[this]       = PSEL_MID;
  ::g_miss_lat_a[this] = 0;
  ::g_miss_lat_b[this] = 0;

  Stats st;
  st.hit_pos_hist.assign(k, 0);
  ::g_stats[this] = std::move(st);

  (void)::n_samplers(); (void)::duel_metric(); (void)::hyst();
}

uint32_t CACHE::find_victim(uint32_t triggering_cpu, uint64_t instr_id, uint32_t set,
                             const BLOCK* current_set, uint64_t ip, uint64_t full_addr,
                             uint32_t type)
{
  const auto& order = ::g_order[this];
  return order[static_cast<std::size_t>(set) * NUM_WAY + (NUM_WAY - 1)];
}

void CACHE::update_replacement_state(uint32_t triggering_cpu, uint32_t set, uint32_t way,
                                      uint64_t full_addr, uint64_t ip, uint64_t victim_addr,
                                      uint32_t type, uint8_t hit)
{
  const std::size_t base = static_cast<std::size_t>(set) * NUM_WAY;
  uint16_t* order = ::g_order[this].data() + base;
  uint16_t* rank  = ::g_rank[this].data() + base;
  int8_t&   cls   = ::g_slot_class[this][base + way];
  uint8_t&  slot_b = ::g_slot_cfg_b[this][base + way];
  auto& st = ::g_stats[this];
  const bool targeted = ::is_targeted(*this);

  // Sampler membership and duel bookkeeping (same scheme as srrip_live).
  const int ns   = ::n_samplers();
  const int step = (targeted && ns > 0) ? static_cast<int>(NUM_SET) / ns : 0;
  const bool is_a = step > 0 && static_cast<int>(set) % step == 0;
  const bool is_b = step > 0 && static_cast<int>(set) % step == step / 2;

  if (step > 0) {
    if (::duel_metric() == 1) {
      if (!hit && type != WRITE) {
        if (is_a) ::g_miss_lat_a[this] += static_cast<int64_t>(this->last_fill_latency);
        if (is_b) ::g_miss_lat_b[this] += static_cast<int64_t>(this->last_fill_latency);
      }
    } else {
      if (hit && type != WRITE) {
        if (is_a) { ::g_psel[this] = std::max(0,        ::g_psel[this] - 1); st.sampler_a_hits++; }
        if (is_b) { ::g_psel[this] = std::min(PSEL_MAX, ::g_psel[this] + 1); st.sampler_b_hits++; }
      }
    }
  }

  if (hit) {
    if (type == WRITE) return;  // store hits don't trigger promotion
    const ConfigVectors& cfg = slot_b ? ::g_cfg_b[this] : ::g_cfg_a[this];
    const std::vector<int>& ipv = !targeted   ? ::g_ipv_trivial[this] :
                                   (cls == 1)   ? cfg.doa :
                                   (cls == 2)   ? cfg.md :
                                                  cfg.ma;
    const int p_old = rank[way];
    st.hits++;
    st.hit_pos_hist[p_old]++;
    switch (cls) {
      case 1:  st.hit_doa++;      break;
      case 2:  st.hit_md++;       break;
      case 3:  st.hit_ma++;       break;
      default: st.hit_unguided++; break;
    }
    ::move_to(order, rank, p_old, ipv[p_old]);
  } else {
    st.misses++;
    if (targeted) {
      const bool b_wins = (::duel_metric() == 1)
          ? (::g_miss_lat_a[this] - ::g_miss_lat_b[this] > ::hyst())
          : (::g_psel[this] > PSEL_MID + static_cast<int>(::hyst()));
      const bool use_b = is_b || (!is_a && step > 0 && b_wins);
      slot_b = use_b;
      const ConfigVectors& cfg = use_b ? ::g_cfg_b[this] : ::g_cfg_a[this];

      const liveness_class lc = classify_block_liveness(full_addr, ip);
      const std::vector<int>& ipv = (lc == liveness_class::doa)         ? cfg.doa :
                                     (lc == liveness_class::mostly_dead)  ? cfg.md :
                                                                            cfg.ma;
      cls = (lc == liveness_class::doa) ? 1 : (lc == liveness_class::mostly_dead) ? 2 : 3;
      if      (cls == 1) st.ins_doa++;
      else if (cls == 2) st.ins_md++;
      else               st.ins_ma++;
      // find_victim() guarantees the evicted way sits at the tail position.
      ::move_to(order, rank, static_cast<int>(NUM_WAY) - 1, ipv[NUM_WAY]);
    } else {
      cls = 0;
      slot_b = 0;
      st.ins_unguided++;
      ::move_to(order, rank, static_cast<int>(NUM_WAY) - 1, ::g_ipv_trivial[this][NUM_WAY]);
    }
  }
}

void CACHE::replacement_final_stats()
{
  const auto& st = ::g_stats[this];
  const std::size_t k = NUM_WAY;
  const bool targeted = ::is_targeted(*this);

  auto print_vec = [](const std::vector<int>& v) {
    for (std::size_t i = 0; i < v.size(); ++i) printf("%d%s", v[i], i + 1 < v.size() ? "," : "");
  };
  auto pct = [](uint64_t n, uint64_t d) -> double { return d ? 100.0 * n / d : 0.0; };

  const uint64_t total_ins = st.ins_doa + st.ins_md + st.ins_ma + st.ins_unguided;
  const uint64_t guided_ins = st.ins_doa + st.ins_md + st.ins_ma;
  const ConfigVectors& a = ::g_cfg_a[this];
  const ConfigVectors& b = ::g_cfg_b[this];

  printf("%s IPV STATS:\n", NAME.c_str());
  printf("  targeted        : %s\n", targeted ? "yes" : "no (trivial/LRU vector)");
  if (::n_samplers() > 0) {
    const bool lat = (::duel_metric() == 1);
    const bool b_wins = lat ? (::g_miss_lat_b[this] < ::g_miss_lat_a[this])
                            : (::g_psel[this] > PSEL_MID);
    if (lat) {
      printf("  Set dueling     : metric=latency  winner=%s  lat_a=%ld  lat_b=%ld  hyst=%ld\n",
             b_wins ? "config_B" : "config_A", ::g_miss_lat_a[this], ::g_miss_lat_b[this], ::hyst());
    } else {
      printf("  Set dueling     : metric=hits  PSEL=%d/%d  winner=%s  a_hits=%lu  b_hits=%lu  hyst=%ld\n",
             ::g_psel[this], PSEL_MAX, b_wins ? "config_B" : "config_A",
             st.sampler_a_hits, st.sampler_b_hits, ::hyst());
    }
    printf("  A.doa: ["); print_vec(a.doa); printf("]\n");
    printf("  A.md : ["); print_vec(a.md);  printf("]\n");
    printf("  A.ma : ["); print_vec(a.ma);  printf("]\n");
    printf("  B.doa: ["); print_vec(b.doa); printf("]\n");
    printf("  B.md : ["); print_vec(b.md);  printf("]\n");
    printf("  B.ma : ["); print_vec(b.ma);  printf("]  (last entry = insertion position)\n");
  } else {
    printf("  IPV_doa         : ["); print_vec(a.doa); printf("]\n");
    printf("  IPV_mostly_dead : ["); print_vec(a.md);  printf("]\n");
    printf("  IPV_mostly_alive: ["); print_vec(a.ma);  printf("]  (last entry = insertion position)\n");
  }
  printf("  hits=%lu  misses=%lu  hit_rate=%.2f%%\n",
         st.hits, st.misses, pct(st.hits, st.hits + st.misses));
  printf("  Activation rate : %.1f%%  (%lu guided / %lu total insertions)\n",
         pct(guided_ins, total_ins), guided_ins, total_ins);
  printf("  Insert mix      : DoA=%.1f%%  Dead=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n",
         pct(st.ins_doa,total_ins), pct(st.ins_md,total_ins),
         pct(st.ins_ma,total_ins), pct(st.ins_unguided,total_ins));
  printf("  Hit rate/class  : DoA=%.1f%%  Dead=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n",
         pct(st.hit_doa,st.ins_doa), pct(st.hit_md,st.ins_md),
         pct(st.hit_ma,st.ins_ma), pct(st.hit_unguided,st.ins_unguided));
  printf("  hit position histogram (position at time of hit, 0=MRU-most):\n   ");
  for (std::size_t p = 0; p < k; ++p)
    printf(" [%zu]=%.1f%%", p, st.hits ? 100.0 * st.hit_pos_hist[p] / st.hits : 0.0);
  printf("\n");
  repl_hist_pc.print_stats(NAME.c_str(), thd_doa, thd_dead);
  printf("\n");
}
