// Shared set-dueling machinery used by lru_live.cc, srrip_live.cc, and
// ipv_live.cc.
//
// Two genuinely different mechanisms live here, not one, because they
// don't reduce to the same thing:
//   - lru_live.cc and srrip_live.cc only ever duel between exactly two
//     configs (A/B), using a classic saturating "PSEL" counter (hit-count
//     mode) or two latency accumulators (latency mode). A PSEL counter
//     forgets old history once it saturates -- it takes many consecutive
//     opposite results to move back across the midpoint.
//   - ipv_live.cc can duel over more than two configs. PSEL doesn't
//     generalize past two arms, so it instead keeps one independent,
//     unbounded counter per config and picks the argmax, falling back to
//     config 0 if the margin doesn't clear a hysteresis threshold.
// Forcing these into one shape would change one policy's actual behavior,
// so both stay separate and clearly labeled below. What genuinely is the
// same across all three is the sampler/follower set-partitioning math.
//
// Included inside each file's own anonymous namespace (like ipv_common.h),
// so everything here gets internal linkage independently per translation
// unit.

#pragma once

#include <algorithm>
#include <array>
#include <cstdint>

// --- Sampler/follower set partitioning (shared by both mechanisms below) ---

struct SamplerRole { bool is_a, is_b, dueling; };

// `n_samplers` is DUEL_N_SAMPLERS (0 = dueling inactive); `num_set` is the
// cache's NUM_SET. When step <= 0 (dueling inactive, or too many samplers
// requested for this cache's set count), every set is a plain follower.
SamplerRole sampler_role(uint32_t set, uint32_t num_set, int n_samplers)
{
  const int step = n_samplers > 0 ? static_cast<int>(num_set) / n_samplers : 0;
  if (step <= 0) return {false, false, false};
  const int j = static_cast<int>(set) % step;
  return {j == 0, j == step / 2, true};
}

// N-config generalization of the same partitioning: which config's sampler
// group `set` belongs to (0..n_configs-1), or -1 for a follower set (or
// when dueling is inactive, i.e. step <= 0). For n_configs == 2 this
// assigns exactly the same sets as sampler_role() does to is_a/is_b.
int sampler_config_of(int set, int step, int n_configs)
{
  if (step <= 0) return -1;
  const int j = set % step;
  for (int i = 0; i < n_configs; ++i)
    if (j == (i * step) / n_configs) return i;
  return -1;
}

// --- 2-config PSEL duel (lru_live.cc, srrip_live.cc) ------------------------

constexpr int PSEL_BITS = 10;
constexpr int PSEL_MAX  = (1 << PSEL_BITS) - 1;
constexpr int PSEL_MID  = 1 << (PSEL_BITS - 1);

struct PselState {
  int psel = PSEL_MID;
  int64_t miss_lat_a = 0, miss_lat_b = 0;
};

// Feeds this event into the duel signal: hit-count mode reacts to demand
// hits (PSEL nudges toward whichever side just hit), latency mode reacts
// to fills (each side accumulates its own total fill latency). No-op for
// writes, and for the mode not currently selected.
void psel_update(PselState& st, SamplerRole role, bool use_latency, bool hit, uint32_t type, int64_t fill_latency)
{
  if (type == WRITE) return;
  if (use_latency) {
    if (!hit) {
      if (role.is_a) st.miss_lat_a += fill_latency;
      if (role.is_b) st.miss_lat_b += fill_latency;
    }
  } else if (hit) {
    if (role.is_a) st.psel = std::max(0,        st.psel - 1);
    if (role.is_b) st.psel = std::min(PSEL_MAX, st.psel + 1);
  }
}

// Whether config B is currently winning, for follower sets to adopt.
bool psel_b_wins(const PselState& st, bool use_latency, int64_t hyst)
{
  return use_latency ? (st.miss_lat_a - st.miss_lat_b > hyst)
                      : (st.psel > PSEL_MID + static_cast<int>(hyst));
}

// --- N-config argmax duel (ipv_live.cc) -------------------------------------

constexpr int MAX_DUEL_CFGS = 8;

// Index of the currently-better config by raw margin (highest hit count,
// or lowest miss latency in latency mode) -- no hysteresis applied.
int best_config_by_metric(const std::array<int64_t, MAX_DUEL_CFGS>& m, int n_configs, bool use_latency)
{
  int best = 0;
  for (int i = 1; i < n_configs; ++i) {
    const bool better = use_latency ? (m[i] < m[best]) : (m[i] > m[best]);
    if (better) best = i;
  }
  return best;
}

// Whether `best`'s margin over every other config exceeds hyst -- if not,
// the winner should revert to config 0 (the conservative default) rather
// than switch on a narrow lead.
bool clears_hysteresis(const std::array<int64_t, MAX_DUEL_CFGS>& m, int n_configs, bool use_latency, int best, int64_t hyst)
{
  for (int i = 0; i < n_configs; ++i) {
    if (i == best) continue;
    const int64_t margin = use_latency ? (m[i] - m[best]) : (m[best] - m[i]);
    if (margin <= hyst) return false;
  }
  return true;
}
