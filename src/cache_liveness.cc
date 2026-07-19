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
  guidance_thd  = (level_doa  && *level_doa)  ? std::stoull(level_doa)  : getenv_uint64("THD_DOA",  1);
}

void CACHE::configure_repl_hist_table()
{
  const uint64_t rh_cap = (NAME == "LLC") ? getenv_uint64("REPL_HIST_LLC_CAP", 0) : 0;
  if (rh_cap > 0) {
    const uint64_t rh_buf = getenv_uint64("REPL_HIST_BUF_CAP", 0);
    liveness_hist = HistTable(rh_cap, HistTable::Policy::LFU_DOA, rh_buf);
    const uint64_t rh_hash = getenv_uint64("REPL_HIST_HASH_BITS", 0);
    if (rh_hash > 0) {
      liveness_hist.set_hash(static_cast<unsigned>(rh_hash));
    }
  } else if (NAME == "LLC" && std::getenv("REPL_HIST_LLC_CAP")) {
    liveness_hist = HistTable(0, HistTable::Policy::LFU_DOA, 0, 0);
  }

  if (const char* v = std::getenv("REPL_HIST_MODE"); v && std::string_view(v) == "addr") {
    use_addr_key = true;
  }
}

void CACHE::apply_bypass_recheck(HistTable& tbl)
{
  const char* m = std::getenv("BYPASS_RECHECK_MODE");
  if (!m) {
    return;
  }
  const std::string_view sv(m);
  HistTable::RecheckMode mode = HistTable::RecheckMode::Off;
  if (sv == "fixed") {
    mode = HistTable::RecheckMode::Fixed;
  } else if (sv == "backoff") {
    mode = HistTable::RecheckMode::Backoff;
  } else {
    return;
  }
  const uint64_t base = getenv_uint64("BYPASS_RECHECK_INTERVAL", 32);
  const uint64_t cap  = getenv_uint64("BYPASS_RECHECK_CAP",     256);
  tbl.set_recheck(mode, base, cap);
}

void CACHE::configure_bypass_llc()
{
  if (NAME != "LLC") {
    return;
  }
  if (const char* v = std::getenv("LIVENESS_BYPASS"); v && std::stoull(v)) {
    bypass_enabled = true;
  }
  bypass_thd = getenv_uint64("BYPASS_THD", guidance_thd);
  if (const uint64_t rp = getenv_uint64("BYPASS_RESET_PERIOD", 0); rp > 0) {
    liveness_hist.set_reset_period(rp);
  }
  if (const uint64_t rp = getenv_uint64("BYPASS_PC_RESET_PERIOD", 0); rp > 0) {
    liveness_hist.set_bypass_pc_reset(rp);
  }
  apply_bypass_recheck(liveness_hist);
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
  return liveness_hist.classify(key, guidance_thd);
}

bool CACHE::should_bypass(uint64_t key, uint64_t bypass_threshold, bool bypass_allowed)
{
  if (!bypass_allowed) {
    return false;
  }

  const bool predicted_doa = liveness_hist.classify(key, bypass_threshold) == liveness_class::doa;
  const bool is_probe = predicted_doa && liveness_hist.should_probe(key);
  if (is_probe) {
    sim_stats.back().bypass_probes++;
  }
  const bool bypass = predicted_doa && !is_probe;
  if (bypass) {
    sim_stats.back().cache_bypasses++;
    liveness_hist.record_bypass(key);
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

  liveness_hist.update(key, evict_lv, guidance_thd);
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
