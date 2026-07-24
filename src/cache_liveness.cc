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

#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <string_view>
#include <unordered_map>

namespace {

constexpr unsigned COUNTER_MAX = 1023;

// Populated by every cache on construction (via load_predictor_settings), so any
// cache can look up another level's CACHE* by NAME once the whole hierarchy exists.
std::unordered_map<std::string, CACHE*> cache_registry;

std::string to_upper(std::string s)
{
  for (auto& ch : s) ch = static_cast<char>(std::toupper(static_cast<unsigned char>(ch)));
  return s;
}

uint64_t getenv_uint64(const char* var, uint64_t fallback)
{
  const char* val = std::getenv(var);
  return val ? static_cast<uint64_t>(std::stoull(val)) : fallback;
}

uint64_t hash_pc(uint64_t pc)
{
  return (pc ^ (pc >> 2) ^ (pc >> 5)) % PRED_COUNTERS;
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

// Supplemental bypass signal: if enabled on this cache, a fill also gets bypassed
// when CROSS_LEVEL_SOURCE's (default L2C) own DoA counter for the same key says DoA,
// even if this cache's own counter hasn't crossed its threshold yet.
void CACHE::configure_cross_level_bypass()
{
  if (NAME != "LLC") {
    return;
  }
  if (const char* v = std::getenv("CROSS_LEVEL_BYPASS"); v && std::stoull(v)) {
    cross_level_bypass_enabled = true;
  }
  cross_level_bypass_thd = getenv_uint64("CROSS_LEVEL_THD", 3);
}

void CACHE::load_predictor_settings()
{
  cache_registry[NAME] = this;
  configure_guidance_thd();
  configure_repl_hist_table();
  configure_bypass_llc();
  configure_cross_level_bypass();
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

bool CACHE::cross_level_says_doa(uint64_t key)
{
  if (!cross_level_source_resolved) {
    cross_level_source_resolved = true;
    const char* src = std::getenv("CROSS_LEVEL_SOURCE");
    const std::string want = to_upper((src && *src) ? src : "L2C");
    auto it = cache_registry.find(want);
    if (it == cache_registry.end()) {
      it = cache_registry.find("cpu0_" + want);
    }
    cross_level_source_cache = (it != cache_registry.end()) ? it->second : nullptr;
  }
  if (!cross_level_source_cache || cross_level_source_cache == this) {
    return false;
  }
  return cross_level_source_cache->pc_counters[hash_pc(key)] >= cross_level_bypass_thd;
}

bool CACHE::resolve_fill_bypass(const PACKET& fill_mshr, set_type::iterator& way, set_type::iterator set_end)
{
  if (way == set_end || !way->valid) {
    return false;
  }

  const bool eligible = NAME == "LLC" && fill_mshr.type != TRANSLATION;
  const uint64_t bypass_key = use_addr_key
      ? (fill_mshr.address >> OFFSET_BITS) : fill_mshr.ip;
  bool bypassed = should_bypass(bypass_key, bypass_thd, bypass_enabled && eligible);
  if (!bypassed && cross_level_bypass_enabled && eligible && cross_level_says_doa(bypass_key)) {
    bypassed = true;
    sim_stats.back().cache_bypasses++;
  }

  if (bypassed) {
    way = set_end;
    return true;
  }
  const liveness_class evict_lv = way->accessed ? liveness_class::alive : liveness_class::doa;
  update_eviction_counters(*way, evict_lv);
  return false;
}
