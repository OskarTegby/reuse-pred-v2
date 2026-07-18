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
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <numeric>
#include <unordered_set>

#include "champsim.h"
#include "champsim_constants.h"
#include "instruction.h"
#include "util.h"

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

  const uint64_t ddp = getenv_uint64("DOA_DEFAULT_PCT", 0);
  if (ddp > 0)
    repl_hist_pc.set_doa_default_pct(static_cast<int>(ddp));
  const uint64_t dfp = getenv_uint64("DOA_FORCE_PCT", 0);
  if (dfp > 0)
    repl_hist_pc.set_doa_force_pct(static_cast<int>(dfp));
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

bool CACHE::handle_fill(const PACKET& fill_mshr)
{
  cpu = fill_mshr.cpu;

  last_fill_latency = current_cycle - (fill_mshr.cycle_enqueued + 1);

  // find victim
  auto [set_begin, set_end] = get_set_span(fill_mshr.address);
  auto way = std::find_if_not(set_begin, set_end, [](auto x) { return x.valid; });
  if (way == set_end) {
    way = std::next(set_begin, impl_find_victim(fill_mshr.cpu, fill_mshr.instr_id, get_set_index(fill_mshr.address), &*set_begin, fill_mshr.ip,
                                                fill_mshr.address, fill_mshr.type));
  }

  bool predictor_bypassed = false;
  if (way != set_end && way->valid) {
    const uint64_t bypass_key = repl_hist_use_addr
        ? (fill_mshr.address >> OFFSET_BITS) : fill_mshr.ip;
    const bool bypassed = evaluate_liveness_bypass(bypass_key, bypass_thd,
        liveness_bypass && NAME == "LLC" && fill_mshr.type != TRANSLATION);

    if (bypassed) {
      shadow_record_bypass(fill_mshr.address >> OFFSET_BITS, fill_mshr.ip, fill_mshr.data);
      predictor_bypassed = true;
      way = set_end;
    } else {
      const liveness_class evict_lv = way->accessed ? liveness_class::alive : liveness_class::doa;
      update_eviction_counters(*way, evict_lv);
    }
  }

  assert(set_begin <= way);
  assert(way <= set_end);
  const auto way_idx = static_cast<std::size_t>(std::distance(set_begin, way)); // cast protected by earlier assertion

  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "] " << __func__;
    std::cout << " instr_id: " << fill_mshr.instr_id << " address: " << std::hex << (fill_mshr.address >> OFFSET_BITS);
    std::cout << " full_addr: " << fill_mshr.address;
    std::cout << " full_v_addr: " << fill_mshr.v_address << std::dec;
    std::cout << " set: " << get_set_index(fill_mshr.address);
    std::cout << " way: " << way_idx;
    std::cout << " type: " << +fill_mshr.type;
    std::cout << " cycle_enqueued: " << fill_mshr.cycle_enqueued;
    std::cout << " cycle: " << current_cycle << std::endl;
  }

  bool success = true;
  auto metadata_thru = fill_mshr.pf_metadata;
  auto pkt_address = (virtual_prefetch ? fill_mshr.v_address : fill_mshr.address) & ~champsim::bitmask(match_offset_bits ? 0 : OFFSET_BITS);
  if (way != set_end) {
    if (way->valid && way->dirty) {
      PACKET writeback_packet;

      writeback_packet.cpu = fill_mshr.cpu;
      writeback_packet.address = way->address;
      writeback_packet.data = way->data;
      writeback_packet.instr_id = fill_mshr.instr_id;
      writeback_packet.ip = 0;
      writeback_packet.type = WRITE;
      writeback_packet.pf_metadata = way->pf_metadata;

      success = lower_level->add_wq(writeback_packet);
    }

    if (success) {
      auto evicting_address = (ever_seen_data ? way->address : way->v_address) & ~champsim::bitmask(match_offset_bits ? 0 : OFFSET_BITS);

      if (way->prefetch)
        sim_stats.back().pf_useless++;

      if (fill_mshr.type == PREFETCH)
        sim_stats.back().pf_fill++;

      if (way->valid) {
        sim_stats.back().evictions++;
        if (!way->accessed)
          sim_stats.back().doa++;
      }

      way->valid = true;
      way->prefetch = fill_mshr.prefetch_from_this;
      way->dirty = (fill_mshr.type == WRITE);
      way->accessed = false;
      way->address = fill_mshr.address;
      way->v_address = fill_mshr.v_address;
      way->data = fill_mshr.data;
      way->ip = fill_mshr.ip;
      way->install_cycle  = current_cycle;
      {
        const uint64_t force_key = repl_hist_use_addr
            ? (fill_mshr.address >> OFFSET_BITS) : fill_mshr.ip;
        repl_hist_pc.maybe_force_doa(force_key, static_cast<int64_t>(thd_doa));
      }

      metadata_thru =
          impl_prefetcher_cache_fill(pkt_address, get_set_index(fill_mshr.address), way_idx, fill_mshr.type == PREFETCH, evicting_address, metadata_thru);
      impl_update_replacement_state(fill_mshr.cpu, get_set_index(fill_mshr.address), way_idx, fill_mshr.address, fill_mshr.ip, evicting_address, fill_mshr.type,
                                    false);

      way->pf_metadata = metadata_thru;
    }
  } else if (!predictor_bypassed) {
    assert(fill_mshr.type != WRITE);

    metadata_thru = impl_prefetcher_cache_fill(pkt_address, get_set_index(fill_mshr.address), way_idx, fill_mshr.type == PREFETCH, 0, metadata_thru);
    impl_update_replacement_state(fill_mshr.cpu, get_set_index(fill_mshr.address), way_idx, fill_mshr.address, fill_mshr.ip, 0, fill_mshr.type, false);
  }

  if (success) {
    // COLLECT STATS
    sim_stats.back().total_miss_latency += current_cycle - (fill_mshr.cycle_enqueued + 1);

    auto copy{fill_mshr};
    copy.pf_metadata = metadata_thru;
    for (auto ret : copy.to_return)
      ret->return_data(copy);
  }

  return success;
}

bool CACHE::try_hit(const PACKET& handle_pkt)
{
  cpu = handle_pkt.cpu;

  // access cache
  auto [set_begin, set_end] = get_set_span(handle_pkt.address);
  auto way = std::find_if(set_begin, set_end, eq_addr<BLOCK>(handle_pkt.address, OFFSET_BITS));
  const auto hit = (way != set_end);

  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "] " << __func__;
    std::cout << " instr_id: " << handle_pkt.instr_id << " address: " << std::hex << (handle_pkt.address >> OFFSET_BITS);
    std::cout << " full_addr: " << handle_pkt.address;
    std::cout << " full_v_addr: " << handle_pkt.v_address << std::dec;
    std::cout << " set: " << get_set_index(handle_pkt.address);
    std::cout << " way: " << std::distance(set_begin, way) << " (" << (hit ? "HIT" : "MISS") << ")";
    std::cout << " type: " << +handle_pkt.type;
    std::cout << " cycle: " << current_cycle << std::endl;
  }

  // update prefetcher on load instructions and prefetches from upper levels
  auto metadata_thru = handle_pkt.pf_metadata;
  if (should_activate_prefetcher(handle_pkt)) {
    uint64_t pf_base_addr = (virtual_prefetch ? handle_pkt.v_address : handle_pkt.address) & ~champsim::bitmask(match_offset_bits ? 0 : OFFSET_BITS);
    metadata_thru = impl_prefetcher_cache_operate(pf_base_addr, handle_pkt.ip, hit, handle_pkt.type, metadata_thru);
  }

  if (hit) {
    sim_stats.back().hits[handle_pkt.type][handle_pkt.cpu]++;

    // update replacement policy
    const auto way_idx = static_cast<std::size_t>(std::distance(set_begin, way)); // cast protected by earlier assertion
    impl_update_replacement_state(handle_pkt.cpu, get_set_index(handle_pkt.address), way_idx, way->address, handle_pkt.ip, 0, handle_pkt.type, true);

    auto copy{handle_pkt};
    copy.data = way->data;
    copy.pf_metadata = metadata_thru;
    for (auto ret : copy.to_return)
      ret->return_data(copy);

    way->dirty = (handle_pkt.type == WRITE);
    if (handle_pkt.type != WRITE) {
      if (NAME == "cpu0_STLB" || NAME == "LLC")
        way->accessed = true;
    }

    // update prefetch stats and reset prefetch bit
    if (way->prefetch && !handle_pkt.prefetch_from_this) {
      sim_stats.back().pf_useful++;
      way->prefetch = false;
    }
  } else {
    sim_stats.back().misses[handle_pkt.type][handle_pkt.cpu]++;
  }

  return hit;
}

bool CACHE::handle_miss(const PACKET& handle_pkt)
{
  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "] " << __func__;
    std::cout << " instr_id: " << handle_pkt.instr_id << " address: " << std::hex << (handle_pkt.address >> OFFSET_BITS);
    std::cout << " full_addr: " << handle_pkt.address;
    std::cout << " full_v_addr: " << handle_pkt.v_address << std::dec;
    std::cout << " type: " << +handle_pkt.type;
    std::cout << " local_prefetch: " << std::boolalpha << handle_pkt.prefetch_from_this << std::noboolalpha;
    std::cout << " cycle: " << current_cycle << std::endl;
  }

  cpu = handle_pkt.cpu;

  // check mshr
  auto mshr_entry = std::find_if(MSHR.begin(), MSHR.end(), eq_addr<PACKET>(handle_pkt.address, OFFSET_BITS));
  bool mshr_full = (MSHR.size() == MSHR_SIZE);

  if (mshr_entry != MSHR.end()) // miss already inflight
  {
    auto instr_copy = std::move(mshr_entry->instr_depend_on_me);
    auto ret_copy = std::move(mshr_entry->to_return);

    std::set_union(std::begin(instr_copy), std::end(instr_copy), std::begin(handle_pkt.instr_depend_on_me), std::end(handle_pkt.instr_depend_on_me),
                   std::back_inserter(mshr_entry->instr_depend_on_me), ooo_model_instr::program_order);
    std::set_union(std::begin(ret_copy), std::end(ret_copy), std::begin(handle_pkt.to_return), std::end(handle_pkt.to_return),
                   std::back_inserter(mshr_entry->to_return));

    if (mshr_entry->type == PREFETCH && handle_pkt.type != PREFETCH) {
      // Mark the prefetch as useful
      if (mshr_entry->prefetch_from_this)
        sim_stats.back().pf_useful++;

      uint64_t prior_event_cycle = mshr_entry->event_cycle;
      auto to_return = std::move(mshr_entry->to_return);
      *mshr_entry = handle_pkt;

      // in case request is already returned, we should keep event_cycle
      mshr_entry->event_cycle = prior_event_cycle;
      mshr_entry->cycle_enqueued = current_cycle;
      mshr_entry->to_return = std::move(to_return);
    }
  } else {
    if (liveness_bypass_shadow_hit(handle_pkt))
      return true;

    if (mshr_full)  // not enough MSHR resource
      return false; // TODO should we allow prefetches anyway if they will not be filled to this level?

    auto fwd_pkt = handle_pkt;

    if (fwd_pkt.type == WRITE)
      fwd_pkt.type = RFO;

    if (handle_pkt.fill_this_level)
      fwd_pkt.to_return = {this};
    else
      fwd_pkt.to_return.clear();

    fwd_pkt.fill_this_level = true; // We will always fill the lower level
    fwd_pkt.prefetch_from_this = false;

    bool success;
    if (prefetch_as_load || handle_pkt.type != PREFETCH)
      success = lower_level->add_rq(fwd_pkt);
    else
      success = lower_level->add_pq(fwd_pkt);

    if (!success)
      return false;

    // Allocate an MSHR
    if (!std::empty(fwd_pkt.to_return)) {
      mshr_entry = MSHR.insert(std::end(MSHR), handle_pkt);
      mshr_entry->pf_metadata = fwd_pkt.pf_metadata;
      mshr_entry->cycle_enqueued = current_cycle;
      mshr_entry->event_cycle = std::numeric_limits<uint64_t>::max();
    }
  }

  return true;
}

bool CACHE::handle_write(const PACKET& handle_pkt)
{
  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "] " << __func__;
    std::cout << " instr_id: " << handle_pkt.instr_id;
    std::cout << " full_addr: " << std::hex << handle_pkt.address;
    std::cout << " full_v_addr: " << handle_pkt.v_address << std::dec;
    std::cout << " type: " << +handle_pkt.type;
    std::cout << " local_prefetch: " << std::boolalpha << handle_pkt.prefetch_from_this << std::noboolalpha;
    std::cout << " cycle: " << current_cycle << std::endl;
  }

  inflight_writes.push_back(handle_pkt);
  inflight_writes.back().event_cycle = current_cycle + (warmup ? 0 : FILL_LATENCY);
  inflight_writes.back().cycle_enqueued = current_cycle;

  return true;
}

template <typename R, typename F>
long int operate_queue(R& queue, long int sz, F&& func)
{
  auto [begin, end] = champsim::get_span_p(std::cbegin(queue), std::cend(queue), sz, std::forward<F>(func));
  auto retval = std::distance(begin, end);
  queue.erase(begin, end);
  return retval;
}

void CACHE::operate()
{
  auto tag_bw = MAX_TAG;
  auto fill_bw = MAX_FILL;

  auto do_fill = [cycle = current_cycle, this](const auto& x) {
    return x.event_cycle <= cycle && this->handle_fill(x);
  };

  auto operate_readlike = [&, this](const auto& pkt) {
    return queues.is_ready(pkt) && (this->try_hit(pkt) || this->handle_miss(pkt));
  };

  auto operate_writelike = [&, this](const auto& pkt) {
    return queues.is_ready(pkt) && (this->try_hit(pkt) || this->handle_write(pkt));
  };

  for (auto q : {std::ref(MSHR), std::ref(inflight_writes)})
    fill_bw -= operate_queue(q.get(), fill_bw, do_fill);

  if (match_offset_bits) {
    // Treat writes (that is, stores) like reads
    for (auto q : {std::ref(queues.WQ), std::ref(queues.PTWQ), std::ref(queues.RQ), std::ref(queues.PQ)})
      tag_bw -= operate_queue(q.get(), tag_bw, operate_readlike);
  } else {
    // Treat writes (that is, writebacks) like fills
    tag_bw -= operate_queue(queues.WQ, tag_bw, operate_writelike);

    for (auto q : {std::ref(queues.PTWQ), std::ref(queues.RQ), std::ref(queues.PQ)})
      tag_bw -= operate_queue(q.get(), tag_bw, operate_readlike);
  }

  impl_prefetcher_cycle_operate();
}

uint64_t CACHE::get_set(uint64_t address) const { return get_set_index(address); }

std::size_t CACHE::get_set_index(uint64_t address) const { return (address >> OFFSET_BITS) & champsim::bitmask(champsim::lg2(NUM_SET)); }

template <typename It>
std::pair<It, It> get_span(It anchor, typename std::iterator_traits<It>::difference_type set_idx, typename std::iterator_traits<It>::difference_type num_way)
{
  auto begin = std::next(anchor, set_idx * num_way);
  return {std::move(begin), std::next(begin, num_way)};
}

auto CACHE::get_set_span(uint64_t address) -> std::pair<std::vector<BLOCK>::iterator, std::vector<BLOCK>::iterator>
{
  const auto set_idx = get_set_index(address);
  assert(set_idx < NUM_SET);
  return get_span(std::begin(block), static_cast<std::vector<BLOCK>::difference_type>(set_idx), NUM_WAY); // safe cast because of prior assert
}

auto CACHE::get_set_span(uint64_t address) const -> std::pair<std::vector<BLOCK>::const_iterator, std::vector<BLOCK>::const_iterator>
{
  const auto set_idx = get_set_index(address);
  assert(set_idx < NUM_SET);
  return get_span(std::cbegin(block), static_cast<std::vector<BLOCK>::difference_type>(set_idx), NUM_WAY); // safe cast because of prior assert
}

uint64_t CACHE::get_way(uint64_t address, uint64_t) const
{
  auto [begin, end] = get_set_span(address);
  return std::distance(begin, std::find_if(begin, end, eq_addr<BLOCK>(address, OFFSET_BITS)));
}

uint64_t CACHE::invalidate_entry(uint64_t inval_addr)
{
  auto [begin, end] = get_set_span(inval_addr);
  auto inv_way = std::find_if(begin, end, eq_addr<BLOCK>(inval_addr, OFFSET_BITS));

  if (inv_way != end)
    inv_way->valid = 0;

  return std::distance(begin, inv_way);
}

bool CACHE::add_rq(const PACKET& packet)
{
  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "_RQ] " << __func__ << " instr_id: " << packet.instr_id << " address: " << std::hex << (packet.address >> OFFSET_BITS);
    std::cout << " full_addr: " << packet.address << " v_address: " << packet.v_address << std::dec << " type: " << +packet.type
              << " occupancy: " << std::size(queues.RQ) << " current_cycle: " << current_cycle << std::endl;
  }

  return queues.add_rq(packet);
}

bool CACHE::add_wq(const PACKET& packet)
{
  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "_WQ] " << __func__ << " instr_id: " << packet.instr_id << " address: " << std::hex << (packet.address >> OFFSET_BITS);
    std::cout << " full_addr: " << packet.address << " v_address: " << packet.v_address << std::dec << " type: " << +packet.type
              << " occupancy: " << std::size(queues.WQ) << " current_cycle: " << current_cycle << std::endl;
  }

  return queues.add_wq(packet);
}

bool CACHE::add_ptwq(const PACKET& packet)
{
  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "_PTWQ] " << __func__ << " instr_id: " << packet.instr_id << " address: " << std::hex << (packet.address >> OFFSET_BITS);
    std::cout << " full_addr: " << packet.address << " v_address: " << packet.v_address << std::dec << " type: " << +packet.type
              << " occupancy: " << std::size(queues.PTWQ) << " current_cycle: " << current_cycle;
  }

  return queues.add_ptwq(packet);
}

int CACHE::prefetch_line(uint64_t pf_addr, bool fill_this_level, uint32_t prefetch_metadata)
{
  sim_stats.back().pf_requested++;

  PACKET pf_packet;
  pf_packet.type = PREFETCH;
  pf_packet.prefetch_from_this = true;
  pf_packet.fill_this_level = fill_this_level;
  pf_packet.pf_metadata = prefetch_metadata;
  pf_packet.cpu = cpu;
  pf_packet.address = pf_addr;
  pf_packet.v_address = virtual_prefetch ? pf_addr : 0;

  auto success = this->add_pq(pf_packet);
  if (success)
    ++sim_stats.back().pf_issued;
  return success;
}

int CACHE::prefetch_line(uint64_t, uint64_t, uint64_t pf_addr, bool fill_this_level, uint32_t prefetch_metadata)
{
  return prefetch_line(pf_addr, fill_this_level, prefetch_metadata);
}

bool CACHE::add_pq(const PACKET& packet)
{
  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "_PQ] " << __func__ << " instr_id: " << packet.instr_id << " address: " << std::hex << (packet.address >> OFFSET_BITS);
    std::cout << " full_addr: " << packet.address << " v_address: " << packet.v_address << std::dec << " type: " << +packet.type
              << " from this: " << std::boolalpha << packet.prefetch_from_this << std::noboolalpha << " occupancy: " << std::size(queues.PQ)
              << " current_cycle: " << current_cycle;
  }

  return queues.add_pq(packet);
}

void CACHE::return_data(const PACKET& packet)
{
  // check MSHR information
  auto mshr_entry = std::find_if(MSHR.begin(), MSHR.end(), eq_addr<PACKET>(packet.address, OFFSET_BITS));
  auto first_unreturned = std::find_if(MSHR.begin(), MSHR.end(), [](auto x) { return x.event_cycle == std::numeric_limits<uint64_t>::max(); });

  // sanity check
  if (mshr_entry == MSHR.end()) {
    std::cerr << "[" << NAME << "_MSHR] " << __func__ << " instr_id: " << packet.instr_id << " cannot find a matching entry!";
    std::cerr << " address: " << std::hex << packet.address;
    std::cerr << " v_address: " << packet.v_address;
    std::cerr << " address: " << (packet.address >> OFFSET_BITS) << std::dec;
    std::cerr << " event: " << packet.event_cycle << " current: " << current_cycle << std::endl;
    assert(0);
  }

  // MSHR holds the most updated information about this request
  mshr_entry->data = packet.data;
  mshr_entry->pf_metadata = packet.pf_metadata;
  mshr_entry->event_cycle = current_cycle + (warmup ? 0 : FILL_LATENCY);

  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "_MSHR] " << __func__ << " instr_id: " << mshr_entry->instr_id;
    std::cout << " address: " << std::hex << mshr_entry->address;
    std::cout << " data: " << mshr_entry->data << std::dec;
    std::cout << " event: " << mshr_entry->event_cycle << " current: " << current_cycle << std::endl;
  }

  // Order this entry after previously-returned entries, but before non-returned
  // entries
  std::iter_swap(mshr_entry, first_unreturned);
}

std::size_t CACHE::get_occupancy(uint8_t queue_type, uint64_t)
{
  if (queue_type == 0)
    return std::size(MSHR);
  else if (queue_type == 1)
    return std::size(queues.RQ);
  else if (queue_type == 2)
    return std::size(queues.WQ);
  else if (queue_type == 3)
    return std::size(queues.PQ);

  return 0;
}

std::size_t CACHE::get_size(uint8_t queue_type, uint64_t)
{
  if (queue_type == 0)
    return MSHR_SIZE;
  else if (queue_type == 1)
    return queues.RQ_SIZE;
  else if (queue_type == 2)
    return queues.WQ_SIZE;
  else if (queue_type == 3)
    return queues.PQ_SIZE;
  else if (queue_type == 4)
    return queues.PTWQ_SIZE;

  return 0;
}

void CACHE::initialize()
{
  impl_prefetcher_initialize();
  impl_initialize_replacement();
}

void CACHE::begin_phase()
{
  roi_stats.emplace_back();
  sim_stats.emplace_back();

  roi_stats.back().name = NAME;
  sim_stats.back().name = NAME;

  repl_hist_pc.reset_stats();

  if (lru_live_reset_phase_stats)
    lru_live_reset_phase_stats(this);
  if (srrip_live_reset_phase_stats)
    srrip_live_reset_phase_stats(this);
  if (ipv_live_reset_phase_stats)
    ipv_live_reset_phase_stats(this);
}

void CACHE::end_phase(unsigned finished_cpu)
{
  for (auto type : {LOAD, RFO, PREFETCH, WRITE, TRANSLATION}) {
    roi_stats.back().hits.at(type).at(finished_cpu) = sim_stats.back().hits.at(type).at(finished_cpu);
    roi_stats.back().misses.at(type).at(finished_cpu) = sim_stats.back().misses.at(type).at(finished_cpu);
  }

  roi_stats.back().pf_requested = sim_stats.back().pf_requested;
  roi_stats.back().pf_issued = sim_stats.back().pf_issued;
  roi_stats.back().pf_useful = sim_stats.back().pf_useful;
  roi_stats.back().pf_useless = sim_stats.back().pf_useless;
  roi_stats.back().pf_fill = sim_stats.back().pf_fill;

  roi_stats.back().total_miss_latency = sim_stats.back().total_miss_latency;

  roi_stats.back().liveness_bypasses       = sim_stats.back().liveness_bypasses;
  roi_stats.back().liveness_probes         = sim_stats.back().liveness_probes;
  roi_stats.back().liveness_bypass_shadow_hits = sim_stats.back().liveness_bypass_shadow_hits;

  roi_stats.back().evictions    = sim_stats.back().evictions;
  roi_stats.back().doa          = sim_stats.back().doa;

  print_doa_addr_summary();
}

bool CACHE::should_activate_prefetcher(const PACKET& pkt) const { return ((1 << pkt.type) & pref_activate_mask) && !pkt.prefetch_from_this; }

void CACHE::print_deadlock()
{
  if (!std::empty(MSHR)) {
    std::cout << NAME << " MSHR Entry" << std::endl;
    std::size_t j = 0;
    for (PACKET entry : MSHR) {
      std::cout << "[" << NAME << " MSHR] entry: " << j++ << " instr_id: " << entry.instr_id;
      std::cout << " address: " << std::hex << entry.address << " v_addr: " << entry.v_address << std::dec << " type: " << +entry.type;
      std::cout << " event_cycle: " << entry.event_cycle << std::endl;
    }
  } else {
    std::cout << NAME << " MSHR empty" << std::endl;
  }

  if (!std::empty(queues.RQ)) {
    for (const auto& entry : queues.RQ) {
      std::cout << "[" << NAME << " RQ] "
                << " instr_id: " << entry.instr_id;
      std::cout << " address: " << std::hex << entry.address << " v_addr: " << entry.v_address << std::dec << " type: " << +entry.type;
      std::cout << " event_cycle: " << entry.event_cycle << std::endl;
    }
  } else {
    std::cout << NAME << " RQ empty" << std::endl;
  }

  if (!std::empty(queues.WQ)) {
    for (const auto& entry : queues.WQ) {
      std::cout << "[" << NAME << " WQ] "
                << " instr_id: " << entry.instr_id;
      std::cout << " address: " << std::hex << entry.address << " v_addr: " << entry.v_address << std::dec << " type: " << +entry.type;
      std::cout << " event_cycle: " << entry.event_cycle << std::endl;
    }
  } else {
    std::cout << NAME << " WQ empty" << std::endl;
  }

  if (!std::empty(queues.PQ)) {
    for (const auto& entry : queues.PQ) {
      std::cout << "[" << NAME << " PQ] "
                << " instr_id: " << entry.instr_id;
      std::cout << " address: " << std::hex << entry.address << " v_addr: " << entry.v_address << std::dec << " type: " << +entry.type;
      std::cout << " event_cycle: " << entry.event_cycle << std::endl;
    }
  } else {
    std::cout << NAME << " PQ empty" << std::endl;
  }
}
