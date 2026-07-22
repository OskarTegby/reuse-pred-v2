/*
 *    Copyright 2023 The ChampSim Contributors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include "cache.h"

#include <cstdio>
#include <cstdlib>
#include <string_view>

namespace {

constexpr unsigned COUNTER_MAX = 1023;

uint64_t getenv_uint64(const char* var, uint64_t fallback)
{
  const char* val = std::getenv(var);
  return val ? static_cast<uint64_t>(std::stoull(val)) : fallback;
}

uint64_t hash_pc(uint64_t pc)
{
  return (pc ^ (pc >> 2) ^ (pc >> 5)) % PRED_COUNTERS;
}

// Sampler-set assignment for DoA-threshold dueling: one set in every 64
// samples each of the three candidate thresholds; everything else is a
// follower that just runs doa_duel_cur.
int doa_duel_arm_for_set(uint32_t set)
{
  switch (set % 64) {
    case 0:  return 0; // guidance_thd - 1
    case 1:  return 1; // guidance_thd (unchanged)
    case 2:  return 2; // guidance_thd + 1
    default: return -1; // follower
  }
}

} // namespace

uint32_t CACHE::effective_guidance_thd(uint32_t set) const
{
  if (!doa_duel_enabled) {
    return static_cast<uint32_t>(guidance_thd);
  }
  switch (doa_duel_arm_for_set(set)) {
    case 0:  return doa_duel_cur > 0 ? doa_duel_cur - 1 : 0;
    case 2:  return doa_duel_cur + 1;
    default: return doa_duel_cur; // arm 1 (same) or a follower set
  }
}

void CACHE::configure_guidance_thd()
{
  const char* level_doa  = (NAME == "LLC") ? std::getenv("LLC_THD_DOA") : nullptr;
  guidance_thd  = (level_doa  && *level_doa)  ? std::stoull(level_doa)  : getenv_uint64("THD_DOA",  3);
}

void CACHE::configure_repl_hist_table()
{
  if (const char* v = std::getenv("REPL_HIST_MODE"); v && std::string_view(v) == "addr") {
    use_addr_key = true;
  }
}

void CACHE::configure_bypass_llc()
{
  if (NAME != "LLC") {
    return;
  }
  if (const char* v = std::getenv("LIVENESS_BYPASS"); v && std::stoull(v)) {
    bypass_enabled = true;
  }
  bypass_thd = getenv_uint64("BYPASS_THD", 6);
}

void CACHE::configure_doa_duel()
{
  if (const char* v = std::getenv("THD_DOA_DYNAMIC"); v && std::stoull(v)) {
    doa_duel_enabled = true;
  }
  if (!doa_duel_enabled) {
    return;
  }
  doa_duel_epoch_size = static_cast<uint32_t>(getenv_uint64("DOA_DUEL_EPOCH", 10000));
  doa_duel_cur         = static_cast<uint32_t>(getenv_uint64("DOA_DUEL_START", 2));
}

void CACHE::load_predictor_settings()
{
  configure_guidance_thd();
  configure_repl_hist_table();
  configure_bypass_llc();
  configure_doa_duel();
}

liveness_class CACHE::classify_block_liveness(uint64_t block_address, uint64_t pc, uint32_t set) const
{
  const uint64_t key = use_addr_key ? (block_address >> OFFSET_BITS) : pc;
  return pc_counters[hash_pc(key)] >= effective_guidance_thd(set) ? liveness_class::doa : liveness_class::alive;
}

void CACHE::doa_duel_record_access(uint32_t set, bool hit)
{
  if (!doa_duel_enabled) {
    return;
  }
  const int arm = doa_duel_arm_for_set(set);
  if (arm < 0) {
    return;
  }
  ++doa_duel_accesses[arm];
  if (hit) {
    ++doa_duel_hits[arm];
  }
}

void CACHE::doa_duel_on_doa_eviction()
{
  if (!doa_duel_enabled) {
    return;
  }
  if (++doa_duel_epoch_evictions < doa_duel_epoch_size) {
    return;
  }

  auto hit_rate = [this](int arm) {
    return doa_duel_accesses[arm] ? static_cast<double>(doa_duel_hits[arm]) / static_cast<double>(doa_duel_accesses[arm]) : 0.0;
  };
  const double hr_decrease = hit_rate(0), hr_same = hit_rate(1), hr_increase = hit_rate(2);

  if (hr_decrease > hr_same && hr_decrease > hr_increase) {
    if (doa_duel_cur > 0) {
      --doa_duel_cur;
    }
  } else if (hr_increase > hr_same && hr_increase > hr_decrease) {
    ++doa_duel_cur;
  }
  // else: "same" wins (or a tie) -- leave doa_duel_cur unchanged.

  doa_duel_epoch_evictions = 0;
  for (auto& h : doa_duel_hits) h = 0;
  for (auto& a : doa_duel_accesses) a = 0;
}

bool CACHE::should_bypass(uint64_t key, uint64_t bypass_threshold, bool bypass_allowed)
{
  if (!bypass_allowed) {
    return false;
  }

  const bool bypass = pc_counters[hash_pc(key)] >= bypass_threshold;
  if (bypass) {
    sim_stats.back().cache_bypasses++;
  }
  return bypass;
}

void CACHE::update_eviction_counters(const BLOCK& victim, liveness_class evict_lv)
{
  if (NAME != "LLC") {
    return;
  }

  const uint64_t block_addr = victim.address >> OFFSET_BITS;
  const uint64_t key = use_addr_key ? block_addr : victim.ip;

  unsigned& ctr = pc_counters[hash_pc(key)];
  if (evict_lv == liveness_class::doa) {
    if (ctr < COUNTER_MAX) {
      ++ctr;
    }
    doa_duel_on_doa_eviction();
  } else {
    ctr = 0;
  }
}

void CACHE::print_pc_counter_stats(const char* prefix) const
{
  unsigned nonzero = 0;
  for (unsigned i = 0; i < PRED_COUNTERS; ++i) {
    if (pc_counters[i] > 0) {
      ++nonzero;
    }
  }
  printf("%s repl_hist occupancy : main %u/%u (%.0f%%)\n",
         prefix, nonzero, PRED_COUNTERS,
         100.0 * nonzero / PRED_COUNTERS);
}

bool CACHE::resolve_fill_bypass(const PACKET& fill_mshr, set_type::iterator& way, set_type::iterator set_end)
{
  if (way == set_end || !way->valid) {
    return false;
  }

  const uint64_t bypass_key = use_addr_key
      ? (fill_mshr.address >> OFFSET_BITS) : fill_mshr.ip;
  const bool bypassed = should_bypass(bypass_key, bypass_thd,
      bypass_enabled && NAME == "LLC" && fill_mshr.type != TRANSLATION);

  if (bypassed) {
    way = set_end;
    return true;
  }
  const liveness_class evict_lv = way->accessed ? liveness_class::alive : liveness_class::doa;
  update_eviction_counters(*way, evict_lv);
  return false;
}
