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

unsigned counter_max()
{
  static const unsigned m = [] {
    const char* v = std::getenv("DOA_COUNTER_MAX");
    return v && v[0] != '\0' ? static_cast<unsigned>(std::stoul(v)) : 1023u;
  }();
  return m;
}

static bool doa_streak_probe_enabled_lv()
{
  static const bool e = [] {
    const char* v = std::getenv("DOA_STREAK_PROBE");
    return v && v[0] != '\0' && v[0] != '0';
  }();
  return e;
}

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

bool cache_matches_target(const std::string& name, const char* env_var)
{
  const char* target_env = std::getenv(env_var);
  if (!target_env || target_env[0] == '\0' || std::string_view(target_env) == "llc")
    return name == "LLC";
  if (std::string_view(target_env) == "none")
    return false;
  // Accepts a comma-separated list, so one run can act at several levels.
  std::string list(target_env);
  for (auto& ch : list) ch = static_cast<char>(std::toupper(static_cast<unsigned char>(ch)));
  std::size_t pos = 0;
  while (pos <= list.size()) {
    const std::size_t next = list.find(',', pos);
    const std::string want = list.substr(pos, next == std::string::npos ? std::string::npos : next - pos);
    if (!want.empty() && (name == want || name == ("cpu0_" + want)))
      return true;
    if (next == std::string::npos) break;
    pos = next + 1;
  }
  return false;
}

} // namespace

bool write_hit_counts_as_access()
{
  static const bool e = [] {
    const char* v = std::getenv("DOA_WRITE_COUNTS");
    return v && v[0] != '\0' && v[0] != '0';
  }();
  return e;
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
  if (!cache_matches_target(NAME, "BYPASS_TARGET")) {
    return;
  }
  if (const char* v = std::getenv("LIVENESS_BYPASS"); v && std::stoull(v)) {
    bypass_enabled = true;
  }
  if (const char* v = std::getenv("BYPASS_HARDCODED"); v && std::stoull(v)) {
    bypass_hardcoded = true;
  }
  {
    std::string lvl = NAME;
    if (lvl.rfind("cpu0_", 0) == 0) lvl = lvl.substr(5);
    const std::string var = to_upper(lvl) + "_BYPASS_THD";
    const char* per = std::getenv(var.c_str());
    bypass_thd = (per && *per) ? std::stoull(per) : getenv_uint64("BYPASS_THD", 6);
  }
}

// Supplemental bypass signal: if enabled on this cache, a fill also gets bypassed
// when CROSS_LEVEL_SOURCE's (default L2C) own DoA counter for the same key says DoA,
// even if this cache's own counter hasn't crossed its threshold yet.
void CACHE::configure_cross_level_bypass()
{
  if (!cache_matches_target(NAME, "CROSS_LEVEL_TARGET")) {
    return;
  }
  if (const char* v = std::getenv("CROSS_LEVEL_BYPASS"); v && std::stoull(v)) {
    cross_level_bypass_enabled = true;
  }
  if (const char* v = std::getenv("CROSS_LEVEL_GUIDANCE"); v && std::stoull(v)) {
    cross_level_guidance_enabled = true;
  }
  cross_level_bypass_thd = getenv_uint64("CROSS_LEVEL_THD", 3);
}

// The counter's initial value sets the prior for a PC we have never seen.
// Zero (the historical default) classifies unseen PCs as alive and hands them
// MRU insertion. At levels where most blocks die unused - L2C evicts 82% of
// blocks without reuse - a dead prior is the better guess, and a live eviction
// still resets the counter to zero, so blocks that prove themselves alive keep
// their protection.
void CACHE::configure_counter_init()
{
  const uint64_t init = getenv_uint64("PC_COUNTER_INIT", 0);
  if (init == 0)
    return;
  for (unsigned i = 0; i < PRED_COUNTERS; ++i)
    pc_counters[i] = static_cast<unsigned>(init);
}

void CACHE::load_predictor_settings()
{
  configure_counter_init();
  cache_registry[NAME] = this;
  configure_guidance_thd();
  configure_repl_hist_table();
  configure_bypass_llc();
  configure_cross_level_bypass();
}

liveness_class CACHE::classify_block_liveness(uint64_t block_address, uint64_t pc) const
{
  const uint64_t key = use_addr_key ? (block_address >> OFFSET_BITS) : pc;
  if (pc_counters[hash_pc(key)] >= guidance_thd)
    return liveness_class::doa;
  // A DoA verdict from the source level is sufficient on its own.
  if (cross_level_guidance_enabled && cross_level_says_doa(key))
    return liveness_class::doa;
  return liveness_class::alive;
}

uint64_t CACHE::counter_for_fill(uint64_t block_address, uint64_t pc) const
{
  return pc_counters[hash_pc(use_addr_key ? (block_address >> OFFSET_BITS) : pc)];
}

// Reads the DoA counter of another level for the same key, so an eviction here can be
// binned against what a different structure already believed about this PC.
uint64_t CACHE::counter_from_source(uint64_t block_address, uint64_t pc)
{
  if (!xacc_resolved) {
    xacc_resolved = true;
    const char* src = std::getenv("XACC_SOURCE");
    if (src && *src) {
      const std::string want = to_upper(src);
      auto it = cache_registry.find(want);
      if (it == cache_registry.end())
        it = cache_registry.find("cpu0_" + want);
      if (it != cache_registry.end() && it->second != this)
        xacc_source = it->second;
    }
  }
  if (!xacc_source)
    return 0;
  return xacc_source->pc_counters[hash_pc(use_addr_key ? (block_address >> OFFSET_BITS) : pc)];
}

// One bit per candidate source structure, set when that level's counter for this PC
// has reached XMASK_THD. Binning evictions by the mask gives the joint agreement
// pattern across the hierarchy rather than four independent marginals.
CACHE* CACHE::lookup_cache(const char* name)
{
  auto it = cache_registry.find(name);
  return it != cache_registry.end() ? it->second : nullptr;
}

unsigned CACHE::source_agreement_mask(uint64_t block_address, uint64_t pc)
{
  static const char* kSources[4] = {"cpu0_L1D", "cpu0_L2C", "cpu0_DTLB", "cpu0_STLB"};
  static const uint64_t thd = getenv_uint64("XMASK_THD", 1);
  const uint64_t key = use_addr_key ? (block_address >> OFFSET_BITS) : pc;
  unsigned mask = 0;
  for (unsigned i = 0; i < 4; ++i) {
    auto it = cache_registry.find(kSources[i]);
    if (it == cache_registry.end() || it->second == this)
      continue;
    if (it->second->pc_counters[hash_pc(key)] >= thd)
      mask |= (1u << i);
  }
  return mask;
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
    if (ctr < counter_max()) {
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

bool CACHE::cross_level_says_doa(uint64_t key) const
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
  if (doa_streak_probe_enabled_lv()) {
    const uint64_t k = use_addr_key ? (fill_mshr.address >> OFFSET_BITS) : fill_mshr.ip;
    unsigned b = 0;
    for (unsigned v = pc_counters[hash_pc(k)]; v > 1; v >>= 1) ++b;
    insert_hist[std::min<unsigned>(b, 23)]++;
  }

  if (way == set_end || !way->valid) {
    return false;
  }

  const bool eligible = fill_mshr.type != TRANSLATION;
  bool bypassed;
  if (bypass_hardcoded) {
    bypassed = bypass_enabled && eligible;
  } else {
    const uint64_t bypass_key = use_addr_key
        ? (fill_mshr.address >> OFFSET_BITS) : fill_mshr.ip;
    bypassed = should_bypass(bypass_key, bypass_thd, bypass_enabled && eligible);
    if (!bypassed && cross_level_bypass_enabled && eligible && cross_level_says_doa(bypass_key)) {
      bypassed = true;
      sim_stats.back().cache_bypasses++;
    }
  }

  if (bypassed) {
    way = set_end;
    return true;
  }
  const liveness_class evict_lv = way->accessed ? liveness_class::alive : liveness_class::doa;
  update_eviction_counters(*way, evict_lv);
  return false;
}
