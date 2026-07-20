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

uint64_t getenv_uint64(const char* var, uint64_t fallback)
{
  const char* val = std::getenv(var);
  return val ? static_cast<uint64_t>(std::stoull(val)) : fallback;
}

} // namespace

void CACHE::configure_guidance_thd()
{
  const char* level_doa  = (NAME == "LLC") ? std::getenv("LLC_THD_DOA") : nullptr;
  guidance_thd  = (level_doa  && *level_doa)  ? std::stoull(level_doa)  : getenv_uint64("THD_DOA",  3);
}

void CACHE::configure_repl_hist_table()
{
  // pc_counters is now a fixed-size hashed counter table (see HistTable) --
  // nothing to size at runtime, so REPL_HIST_LLC_CAP is no longer read.
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

void CACHE::load_predictor_settings()
{
  configure_guidance_thd();
  configure_repl_hist_table();
  configure_bypass_llc();
}

liveness_class CACHE::classify_block_liveness(uint64_t block_address, uint64_t pc) const
{
  const uint64_t key = use_addr_key ? (block_address >> OFFSET_BITS) : pc;
  return pc_counters.classify(key, guidance_thd);
}

bool CACHE::should_bypass(uint64_t key, uint64_t bypass_threshold, bool bypass_allowed)
{
  if (!bypass_allowed) {
    return false;
  }

  const bool bypass = pc_counters.classify(key, bypass_threshold) == liveness_class::doa;
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

  pc_counters.update(key, evict_lv);
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
