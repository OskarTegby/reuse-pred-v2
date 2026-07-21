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

#include <algorithm>
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

constexpr int DUEL_BYPASS_PSEL_BITS = 10;
constexpr int DUEL_BYPASS_PSEL_MAX  = (1 << DUEL_BYPASS_PSEL_BITS) - 1;
constexpr int DUEL_BYPASS_PSEL_MID  = 1 << (DUEL_BYPASS_PSEL_BITS - 1);

struct DuelBypassRole { bool is_no, is_yes, dueling; };

DuelBypassRole duel_bypass_role(uint32_t set, uint32_t num_set, int n_samplers)
{
  const int step = n_samplers > 0 ? static_cast<int>(num_set) / n_samplers : 0;
  if (step <= 0) {
    return {false, false, false};
  }
  const int j = static_cast<int>(set) % step;
  return {j == 0, j == step / 2, true};
}

} // namespace

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

void CACHE::configure_duel_bypass()
{
  if (NAME != "LLC") {
    return;
  }
  if (const char* v = std::getenv("DUEL_BYPASS"); v && std::stoull(v)) {
    duel_bypass_enabled = true;
  }
  duel_bypass_n_samplers = static_cast<int>(getenv_uint64("DUEL_N_SAMPLERS", 0));
  duel_bypass_hyst = static_cast<int64_t>(getenv_uint64("DUEL_HYST", 0));
  if (const char* m = std::getenv("DUEL_METRIC"); m && std::string_view(m) == "latency") {
    duel_bypass_use_latency = true;
  }
}

void CACHE::load_predictor_settings()
{
  configure_guidance_thd();
  configure_repl_hist_table();
  configure_bypass_llc();
  configure_duel_bypass();
}

liveness_class CACHE::classify_block_liveness(uint64_t block_address, uint64_t pc) const
{
  const uint64_t key = use_addr_key ? (block_address >> OFFSET_BITS) : pc;
  return pc_counters[hash_pc(key)] >= guidance_thd ? liveness_class::doa : liveness_class::alive;
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

bool CACHE::duel_wants_bypass(uint32_t set) const
{
  if (!duel_bypass_enabled) {
    return false;
  }
  const DuelBypassRole role = duel_bypass_role(set, static_cast<uint32_t>(NUM_SET), duel_bypass_n_samplers);
  if (!role.dueling) {
    return false;
  }
  if (role.is_no) {
    return false;
  }
  if (role.is_yes) {
    return true;
  }
  return duel_bypass_use_latency
      ? (duel_bypass_lat_no - duel_bypass_lat_yes > duel_bypass_hyst)
      : (duel_bypass_psel > DUEL_BYPASS_PSEL_MID + static_cast<int>(duel_bypass_hyst));
}

void CACHE::update_duel_bypass_hit_signal(uint32_t set, uint32_t type)
{
  if (!duel_bypass_enabled || duel_bypass_use_latency || type == WRITE) {
    return;
  }
  const DuelBypassRole role = duel_bypass_role(set, static_cast<uint32_t>(NUM_SET), duel_bypass_n_samplers);
  if (role.is_no) {
    duel_bypass_psel = std::max(0, duel_bypass_psel - 1);
  }
  if (role.is_yes) {
    duel_bypass_psel = std::min(DUEL_BYPASS_PSEL_MAX, duel_bypass_psel + 1);
  }
}

void CACHE::update_duel_bypass_fill_signal(uint32_t set, uint32_t type, int64_t fill_latency)
{
  if (!duel_bypass_enabled || !duel_bypass_use_latency || type == WRITE) {
    return;
  }
  const DuelBypassRole role = duel_bypass_role(set, static_cast<uint32_t>(NUM_SET), duel_bypass_n_samplers);
  if (role.is_no) {
    duel_bypass_lat_no += fill_latency;
  }
  if (role.is_yes) {
    duel_bypass_lat_yes += fill_latency;
  }
}

bool CACHE::resolve_fill_bypass(const PACKET& fill_mshr, set_type::iterator& way, set_type::iterator set_end)
{
  if (way == set_end || !way->valid) {
    return false;
  }

  const uint64_t bypass_key = use_addr_key
      ? (fill_mshr.address >> OFFSET_BITS) : fill_mshr.ip;
  const uint32_t set = static_cast<uint32_t>(get_set_index(fill_mshr.address));
  const bool bypass_allowed = NAME == "LLC" && fill_mshr.type != TRANSLATION
      && (bypass_enabled || duel_wants_bypass(set));
  const bool bypassed = should_bypass(bypass_key, bypass_thd, bypass_allowed);

  if (bypassed) {
    way = set_end;
    return true;
  }
  const liveness_class evict_lv = way->accessed ? liveness_class::alive : liveness_class::doa;
  update_eviction_counters(*way, evict_lv);
  return false;
}
