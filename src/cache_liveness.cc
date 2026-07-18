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

extern "C" void lru_live_reset_phase_stats(CACHE*) __attribute__((weak));
extern "C" void srrip_live_reset_phase_stats(CACHE*) __attribute__((weak));
extern "C" void ipv_live_reset_phase_stats(CACHE*) __attribute__((weak));

namespace {

uint64_t getenv_uint64(const char* var, uint64_t fallback)
{
  const char* val = std::getenv(var);
  return val ? static_cast<uint64_t>(std::stoull(val)) : fallback;
}

} // namespace

void CACHE::reset_phase_liveness_stats()
{
  repl_hist_pc.reset_stats();

  if (lru_live_reset_phase_stats)
    lru_live_reset_phase_stats(this);
  if (srrip_live_reset_phase_stats)
    srrip_live_reset_phase_stats(this);
  if (ipv_live_reset_phase_stats)
    ipv_live_reset_phase_stats(this);
}

void CACHE::shadow_record_bypass(uint64_t block_addr, uint64_t pc, uint64_t data)
{
  if (bypass_shadow_cap_ == 0) return;
  if (bypass_shadow_.count(block_addr)) return;
  while (bypass_shadow_fifo_.size() >= bypass_shadow_cap_) {
    bypass_shadow_.erase(bypass_shadow_fifo_.front());
    bypass_shadow_fifo_.pop_front();
  }
  bypass_shadow_[block_addr] = {pc, data};
  bypass_shadow_fifo_.push_back(block_addr);
}

bool CACHE::liveness_bypass_shadow_hit(const PACKET& handle_pkt)
{
  if (bypass_shadow_cap_ == 0) return false;
  const uint64_t addr = handle_pkt.address >> OFFSET_BITS;
  auto it = bypass_shadow_.find(addr);
  if (it == bypass_shadow_.end()) return false;
  const uint64_t pc = it->second.first, data = it->second.second;
  bypass_shadow_.erase(it);
  repl_hist_pc.erase_key(pc);
  sim_stats.back().liveness_bypass_shadow_hits++;
  if (NAME == "cpu0_STLB") {
    auto copy{handle_pkt};
    copy.data = data;
    for (auto ret : copy.to_return)
      ret->return_data(copy);
    PACKET fill_pkt = handle_pkt;
    fill_pkt.data = data;
    fill_pkt.to_return = {};
    handle_fill(fill_pkt);
    return true;
  }
  return false;
}

void CACHE::update_eviction_counters(const BLOCK& victim, liveness_class evict_lv)
{
  if (NAME == "LLC") {
    const uint64_t repl_key = repl_hist_use_addr ? (victim.address >> OFFSET_BITS) : victim.ip;
    const int64_t old_score = (doa_trace_enable_ && !warmup) ? repl_hist_pc.get_score(repl_key) : 0;
    repl_hist_pc.update(repl_key, evict_lv, thd_doa);
    if (doa_trace_enable_ && !warmup) {
      const int64_t new_score = repl_hist_pc.get_score(repl_key);
      doa_trace_file_ << current_cycle << ',' << victim.ip << ',' << (victim.address >> OFFSET_BITS) << ','
                       << (evict_lv == liveness_class::doa ? 1 : 0) << ',' << old_score << ',' << new_score << '\n';
    }
    if (doa_addr_summary_enable_ && !warmup)
      record_doa_addr_summary(victim.ip, victim.address >> OFFSET_BITS, evict_lv);
  }
}

void CACHE::record_fill_eviction_stats(const BLOCK& victim)
{
  if (!victim.valid) return;
  sim_stats.back().evictions++;
  if (!victim.accessed)
    sim_stats.back().doa++;
}

void CACHE::configure_thd_doa()
{
  const char* level_doa  = (NAME == "LLC") ? std::getenv("LLC_THD_DOA") : nullptr;
  thd_doa  = (level_doa  && *level_doa)  ? std::stoull(level_doa)  : getenv_uint64("THD_DOA",  1);
}

void CACHE::configure_repl_hist_table()
{
  const uint64_t rh_cap = (NAME == "LLC") ? getenv_uint64("REPL_HIST_LLC_CAP", 0) : 0;
  if (rh_cap > 0) {
    const uint64_t rh_buf = getenv_uint64("REPL_HIST_BUF_CAP", 0);
    repl_hist_pc = HistTable(rh_cap, HistTable::Policy::LFU_DOA, rh_buf);
    const uint64_t rh_hash = getenv_uint64("REPL_HIST_HASH_BITS", 0);
    if (rh_hash > 0)
      repl_hist_pc.set_hash(static_cast<unsigned>(rh_hash));
  } else if (NAME == "LLC" && std::getenv("REPL_HIST_LLC_CAP")) {
    repl_hist_pc = HistTable(0, HistTable::Policy::LFU_DOA, 0, 0);
  }

  if (const char* v = std::getenv("REPL_HIST_MODE"); v && std::string_view(v) == "addr")
    repl_hist_use_addr = true;
}

void CACHE::configure_doa_diagnostics()
{
  if (const char* v = std::getenv("DOA_COUNTER_TRACE"); v && std::stoull(v) && NAME == "LLC") {
    doa_trace_enable_ = true;
    doa_trace_file_.open("doa_counter_trace_" + NAME + ".csv");
    doa_trace_file_ << "cycle,pc,addr,evict_class,old_score,new_score\n";
  }
  if (const char* v = std::getenv("DOA_ADDR_SUMMARY"); v && std::stoull(v) && NAME == "LLC")
    doa_addr_summary_enable_ = true;
}

void CACHE::apply_bypass_recheck(HistTable& tbl)
{
  const char* m = std::getenv("BYPASS_RECHECK_MODE");
  if (!m) return;
  const std::string_view sv(m);
  HistTable::RecheckMode mode = HistTable::RecheckMode::Off;
  if      (sv == "fixed")   mode = HistTable::RecheckMode::Fixed;
  else if (sv == "backoff") mode = HistTable::RecheckMode::Backoff;
  else return;
  const uint64_t base = getenv_uint64("BYPASS_RECHECK_INTERVAL", 32);
  const uint64_t cap  = getenv_uint64("BYPASS_RECHECK_CAP",     256);
  tbl.set_recheck(mode, base, cap);
}

void CACHE::configure_bypass_llc()
{
  if (NAME != "LLC") return;
  if (const char* v = std::getenv("LIVENESS_BYPASS"); v && std::stoull(v))
    liveness_bypass = true;
  bypass_thd = getenv_uint64("BYPASS_THD", thd_doa);
  if (const uint64_t rp = getenv_uint64("BYPASS_RESET_PERIOD", 0); rp > 0)
    repl_hist_pc.set_reset_period(rp);
  if (const uint64_t rp = getenv_uint64("BYPASS_PC_RESET_PERIOD", 0); rp > 0)
    repl_hist_pc.set_bypass_pc_reset(rp);
  apply_bypass_recheck(repl_hist_pc);
  bypass_shadow_cap_ = getenv_uint64("LLC_BYPASS_SHADOW_SIZE", getenv_uint64("BYPASS_SHADOW_SIZE", 0));
}

void CACHE::load_predictor_settings()
{
  configure_thd_doa();
  configure_repl_hist_table();
  configure_doa_diagnostics();
  configure_bypass_llc();
}

liveness_class CACHE::classify_block_liveness(uint64_t block_address, uint64_t pc) const
{
  const uint64_t key = repl_hist_use_addr ? (block_address >> OFFSET_BITS) : pc;
  return repl_hist_pc.classify(key, thd_doa);
}

void CACHE::mark_accessed_on_hit(BLOCK& blk, uint8_t type)
{
  if (type != WRITE && (NAME == "cpu0_STLB" || NAME == "LLC"))
    blk.accessed = true;
}

void CACHE::record_doa_addr_summary(uint64_t pc, uint64_t addr, liveness_class evict_lv)
{
  auto& e = doa_addr_table_[pc][addr];
  if (evict_lv == liveness_class::doa) {
    e.score++;
    doa_addr_pc_doa_total_[pc]++;
  } else {
    if (e.score > 0) e.ever_reset = true;
    e.score = 0;
  }
}

void CACHE::print_doa_addr_summary() const
{
  if (!doa_addr_summary_enable_ || doa_addr_table_.empty())
    return;

  printf("%s DOA_ADDR_SUMMARY BEGIN\n", NAME.c_str());
  for (const auto& [pc, addrs] : doa_addr_table_) {
    uint64_t n_always_doa = 0, n_has_reset = 0;
    for (const auto& [addr, e] : addrs)
      (e.ever_reset ? n_has_reset : n_always_doa)++;
    const auto it = doa_addr_pc_doa_total_.find(pc);
    const uint64_t pc_doa_total = (it != doa_addr_pc_doa_total_.end()) ? it->second : 0;
    printf("  PC=0x%016lx n_addr=%lu always_doa=%lu has_reset=%lu doa_total=%lu\n",
           pc, addrs.size(), n_always_doa, n_has_reset, pc_doa_total);
  }
  printf("%s DOA_ADDR_SUMMARY END\n", NAME.c_str());
}

bool CACHE::evaluate_liveness_bypass(uint64_t key, uint64_t level_thd, bool enabled)
{
  const bool lv_doa = enabled && repl_hist_pc.classify(key, level_thd) == liveness_class::doa;
  const bool lv_probe = lv_doa && repl_hist_pc.should_probe(key);
  if (lv_probe) sim_stats.back().liveness_probes++;
  const bool lv_bypass = lv_doa && !lv_probe;
  if (lv_bypass) {
    sim_stats.back().liveness_bypasses++;
    repl_hist_pc.record_bypass(key);
  }
  return lv_bypass;
}

bool CACHE::evaluate_fill_bypass(const PACKET& fill_mshr, set_type::iterator& way, set_type::iterator set_end)
{
  if (way == set_end || !way->valid) return false;

  const uint64_t bypass_key = repl_hist_use_addr
      ? (fill_mshr.address >> OFFSET_BITS) : fill_mshr.ip;
  const bool bypassed = evaluate_liveness_bypass(bypass_key, bypass_thd,
      liveness_bypass && NAME == "LLC" && fill_mshr.type != TRANSLATION);

  if (bypassed) {
    shadow_record_bypass(fill_mshr.address >> OFFSET_BITS, fill_mshr.ip, fill_mshr.data);
    way = set_end;
    return true;
  }
  const liveness_class evict_lv = way->accessed ? liveness_class::alive : liveness_class::doa;
  update_eviction_counters(*way, evict_lv);
  return false;
}
