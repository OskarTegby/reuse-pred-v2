// Shared A/B set-dueling role assignment used by srrip_live.cc (and intended
// for lru_live.cc, which duplicates this same logic but hasn't been switched
// over yet): partitions LLC sets into sampler-A, sampler-B, and follower
// sets. Sampler A always uses config A; sampler B always uses config B;
// followers adopt whichever config is currently winning (via a caller-owned
// PSEL counter or latency accumulator -- winner determination differs
// slightly between policies, so it stays in each file, not here).
//
// Included inside each file's own anonymous namespace (like ipv_common.h),
// so it gets internal linkage independently per translation unit.

#pragma once

#include <cstdint>

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
