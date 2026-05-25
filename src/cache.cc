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
#include "hist_lru.h"

#include <algorithm>
#include <cassert>
#include <climits>
#include <cstring>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <numeric>

#include "champsim.h"
#include "champsim_constants.h"
#include "instruction.h"
#include "util.h"

// ── Liveness classification ───────────────────────────────────────────────────
//
// Definitions (all in simulation cycles):
//   residence  = eviction_cycle − insert_cycle
//   dead_tail  = eviction_cycle − last_hit_cycle
//   DoA        : hit_count == 0  (never referenced after insertion)
//   Mostly-dead: hit_count > 0 AND dead_tail > residence / 2
//   Mostly-alive: otherwise (dead_tail ≤ residence / 2)
//
// Invariants asserted (violations indicate a simulator bug):
//   (A) last_hit_cycle >= insert_cycle      (last hit cannot predate insertion)
//   (B) current_cycle  >= insert_cycle      (time is monotonically increasing)
//   (C) current_cycle  >= last_hit_cycle    (same)
//   (D) dead_tail      <= residence         (arithmetic consequence of A-C;
//                                            also guards against unsigned underflow)
CACHE::liveness_class CACHE::classify_liveness(const BLOCK& victim) const
{
  assert(victim.last_hit_cycle >= victim.insert_cycle); // (A)
  assert(current_cycle >= victim.insert_cycle);         // (B)
  assert(current_cycle >= victim.last_hit_cycle);       // (C)

  const uint64_t residence = current_cycle - victim.insert_cycle;
  const uint64_t dead_tail = current_cycle - victim.last_hit_cycle;

  assert(dead_tail <= residence); // (D): unsigned underflow guard

  if (victim.hit_count == 0)
    return liveness_class::doa;

  // Use dead_tail > residence/2 rather than 2*dead_tail > residence to avoid
  // any theoretical uint64_t overflow on extraordinarily long-lived blocks.
  return (dead_tail > residence / 2) ? liveness_class::mostly_dead
                                     : liveness_class::mostly_alive;
}

// Records liveness stats for the evicted block.  No-op for caches other than
// the LLC and STLB.  Suspicious-condition (zero residence) is counted here.
void CACHE::record_eviction_liveness(const BLOCK& victim, liveness_class lv)
{
  if (NAME != "cpu0_STLB" && NAME != "LLC")
    return;

  auto& s = sim_stats.back();
  s.evict_total++;

  if (current_cycle == victim.insert_cycle)
    s.evict_zero_residence++;

  const std::size_t bin = std::min(static_cast<std::size_t>(victim.hit_count),
                                   cache_stats::HIT_HIST_BINS - 1);
  s.evict_hit_hist[bin]++;

  switch (lv) {
    case liveness_class::doa:          s.evict_doa++;          break;
    case liveness_class::mostly_dead:  s.evict_mostly_dead++;  break;
    case liveness_class::mostly_alive: s.evict_mostly_alive++; break;
  }

  // STLB: record this page's DoA status in the evict log so the LLC can
  // cross-reference it even after it leaves the STLB.  FIFO-capped.
  if (NAME == "cpu0_STLB") {
    const uint64_t pfn = victim.data >> LOG2_PAGE_SIZE;
    if (!stlb_evict_log.count(pfn)) {
      while (stlb_evict_log.size() >= stlb_evict_log_cap && !stlb_evict_log_order.empty()) {
        stlb_evict_log.erase(stlb_evict_log_order.front());
        stlb_evict_log_order.pop_front();
      }
      stlb_evict_log_order.push_back(pfn);
    }
    stlb_evict_log[pfn] = (lv == liveness_class::doa);
  }

  // For LLC DoA blocks: check whether the evicted block's PFN has STLB info.
  // Coverage breakdown:
  //   live STLB, DoA    → evict_doa_on_doa_stlb_page    (true-positive)
  //   live STLB, alive  → evict_doa_stlb_resident_alive (true-negative)
  //   evict log, DoA    → evict_doa_stlb_evicted_doa    (extended true-positive)
  //   evict log, alive  → evict_doa_stlb_evicted_alive  (extended true-negative)
  //   not found         → uncovered (derived: evict_doa − the four above)
  //
  // Live-STLB check uses any_of over ALL entries for the PFN: a page is DoA
  // if any translation for it is DoA, which matches the upper-bound semantics
  // of "what could hardware learn from the STLB about this physical page?"
  // (find_if would stop at the first matching entry, giving arbitrary results
  // when multiple virtual aliases of the same PFN are resident simultaneously.)
  if (NAME == "LLC" && lv == liveness_class::doa && stlb_ptr != nullptr) {
    const uint64_t pfn = victim.address >> LOG2_PAGE_SIZE;

    const bool stlb_resident = std::any_of(
        stlb_ptr->block.begin(), stlb_ptr->block.end(),
        [pfn](const BLOCK& b) { return b.valid && (b.data >> LOG2_PAGE_SIZE) == pfn; });

    if (stlb_resident) {
      const bool stlb_doa = std::any_of(
          stlb_ptr->block.begin(), stlb_ptr->block.end(),
          [pfn](const BLOCK& b) {
            return b.valid && (b.data >> LOG2_PAGE_SIZE) == pfn && b.hit_count == 0;
          });
      if (stlb_doa) s.evict_doa_on_doa_stlb_page++;
      else          s.evict_doa_stlb_resident_alive++;
    } else {
      const auto it_log = stlb_evict_log.find(pfn);
      if (it_log != stlb_evict_log.end()) {
        if (it_log->second) s.evict_doa_stlb_evicted_doa++;
        else                s.evict_doa_stlb_evicted_alive++;
      }
      // else: uncovered — no STLB information available for this PFN
    }
  }
}

// Accumulates per-PC liveness event counts.  No-op for caches other than
// the LLC and STLB.  Unlike the history-table confidence counters in
// update_eviction_counters, these counters only ever increment — they are
// never reset — so they record total event frequencies across the whole run.
void CACHE::record_pc_liveness(const BLOCK& victim, liveness_class lv)
{
  if (NAME != "cpu0_STLB" && NAME != "LLC")
    return;

  auto& entry = (NAME == "cpu0_STLB") ? sim_stats.back().llt_pc_stats[victim.ip]
                                       : sim_stats.back().llc_pc_stats[victim.ip];
  switch (lv) {
    case liveness_class::doa:          entry.doa++;          break;
    case liveness_class::mostly_dead:  entry.mostly_dead++;  break;
    case liveness_class::mostly_alive: entry.mostly_alive++; break;
  }
}

// Updates the mid-insertion history tables when a valid entry is evicted.
// All updates happen at eviction time so hits during the current residence
// do not affect insertion decisions for the next miss of the same address.
void CACHE::update_eviction_counters(const BLOCK& victim, liveness_class lv)
{
  auto update = [lv](hist_entry& e) {
    switch (lv) {
      case liveness_class::doa:
        e.doa++;
        break;
      case liveness_class::mostly_dead:
        e.mostly_dead++;
        e.doa = 0;
        break;
      case liveness_class::mostly_alive:
        e.doa         = 0;
        e.mostly_dead = 0;
        break;
    }
  };

  if (NAME == "LLC") {
    update((repl_pol == repl_pol_t::lfu)
             ? lfu_access(llc_mid_hist_addr, victim.address >> OFFSET_BITS, mid_hist_cap, lru_clock)
             : lru_access(llc_mid_hist_addr, victim.address >> OFFSET_BITS, mid_hist_cap, lru_clock));
    update((repl_pol == repl_pol_t::lfu)
             ? lfu_access(llc_mid_hist_pc,   victim.ip,                     mid_hist_cap, lru_clock)
             : lru_access(llc_mid_hist_pc,   victim.ip,                     mid_hist_cap, lru_clock));
  } else if (NAME == "cpu0_STLB") {
    update((repl_pol == repl_pol_t::lfu)
             ? lfu_access(stlb_mid_hist_addr, victim.address >> OFFSET_BITS, mid_hist_cap, lru_clock)
             : lru_access(stlb_mid_hist_addr, victim.address >> OFFSET_BITS, mid_hist_cap, lru_clock));
    update((repl_pol == repl_pol_t::lfu)
             ? lfu_access(stlb_mid_hist_pc,   victim.ip,                     mid_hist_cap, lru_clock)
             : lru_access(stlb_mid_hist_pc,   victim.ip,                     mid_hist_cap, lru_clock));
  }
}

// Returns true when the entry's history shows its last eviction was DoA or
// mostly-dead, meaning it should be inserted at the set midpoint in lru_mid.
bool CACHE::needs_mid_insertion(uint64_t full_addr, uint64_t ip) const
{
  auto check = [this](const std::map<uint64_t, hist_entry>& tbl, uint64_t key) {
    const auto it = tbl.find(key);
    return it != tbl.end() && (it->second.doa >= mid_thd || it->second.mostly_dead >= mid_thd);
  };
  if (NAME == "LLC") {
    return (mid_key == mid_key_t::pc) ? check(llc_mid_hist_pc,    ip)
                                      : check(llc_mid_hist_addr,   full_addr >> OFFSET_BITS);
  } else if (NAME == "cpu0_STLB") {
    return (mid_key == mid_key_t::pc) ? check(stlb_mid_hist_pc,   ip)
                                      : check(stlb_mid_hist_addr,  full_addr >> OFFSET_BITS);
  }
  return false;
}

// 3-way liveness prediction for ipv_live: DoA → mostly_dead → mostly_alive.
// Uses the same history tables and mid_thd threshold as needs_mid_insertion(),
// but distinguishes DoA from mostly_dead instead of collapsing them.
// DoA takes priority: if both counters meet the threshold, returns doa.
CACHE::liveness_class CACHE::predict_liveness(uint64_t full_addr, uint64_t ip) const
{
  auto classify = [this](const std::map<uint64_t, hist_entry>& tbl, uint64_t key) -> liveness_class {
    const auto it = tbl.find(key);
    if (it == tbl.end())                      return liveness_class::mostly_alive;
    if (it->second.doa >= mid_thd)            return liveness_class::doa;
    if (it->second.mostly_dead >= mid_thd)    return liveness_class::mostly_dead;
    return liveness_class::mostly_alive;
  };
  if (NAME == "LLC")
    return (mid_key == mid_key_t::pc) ? classify(llc_mid_hist_pc,   ip)
                                      : classify(llc_mid_hist_addr,  full_addr >> OFFSET_BITS);
  if (NAME == "cpu0_STLB")
    return (mid_key == mid_key_t::pc) ? classify(stlb_mid_hist_pc,  ip)
                                      : classify(stlb_mid_hist_addr, full_addr >> OFFSET_BITS);
  return liveness_class::mostly_alive;
}

// Reads environment variables to configure the replacement policy.
// Variables (all optional; defaults match the header initializers):
//   MID_THD=<n>        min DoA-or-mostly-dead evictions before mid-insertion triggers (default 1)
//   MID_PROMOTE=<0|1>  promote mid-inserted blocks to MRU on hit (default 0)
//   MID_KEY=<0|1>      0 = addr-keyed history, 1 = PC-keyed history (default 0)
//   MID_HIST_CAP=<n>   capacity of each mid-history table (default 65536)
//   REPL_POL=<pol>     replacement policy for history tables: "lru" (default) | "lfu"
//   STLB_EVICT_LOG_CAP=<n>  capacity of the STLB eviction log (default 1024)
void CACHE::load_predictor_settings()
{
  auto getenv_uint64 = [](const char* var, uint64_t fallback) -> uint64_t {
    const char* val = std::getenv(var);
    if (!val || !*val) return fallback;
    try { return static_cast<uint64_t>(std::stoull(val)); }
    catch (...) { return fallback; }
  };

  mid_thd            = getenv_uint64("MID_THD",     mid_thd);
  mid_key            = (getenv_uint64("MID_KEY", 0) == 1) ? mid_key_t::pc : mid_key_t::addr;
  mid_promote_on_hit = (getenv_uint64("MID_PROMOTE", 0) == 1);
  mid_hist_cap       = getenv_uint64("MID_HIST_CAP", mid_hist_cap);
  stlb_evict_log_cap = getenv_uint64("STLB_EVICT_LOG_CAP", stlb_evict_log_cap);

  if (const char* pol = std::getenv("REPL_POL"))
    repl_pol = (std::strcmp(pol, "lfu") == 0) ? repl_pol_t::lfu : repl_pol_t::lru;
}

bool CACHE::handle_fill(const PACKET& fill_mshr)
{
  cpu = fill_mshr.cpu;

  // find victim
  auto [set_begin, set_end] = get_set_span(fill_mshr.address);
  auto way = std::find_if_not(set_begin, set_end, [](auto x) { return x.valid; });
  if (way == set_end)
    way = std::next(set_begin, impl_find_victim(fill_mshr.cpu, fill_mshr.instr_id, get_set_index(fill_mshr.address), &*set_begin, fill_mshr.ip,
                                                fill_mshr.address, fill_mshr.type));

  if (way != set_end && way->valid) {
    const auto lv = classify_liveness(*way);
    record_eviction_liveness(*way, lv);
    record_pc_liveness(*way, lv);
    update_eviction_counters(*way, lv);
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

      way->valid = true;
      way->prefetch = fill_mshr.prefetch_from_this;
      way->dirty = (fill_mshr.type == WRITE);
      way->insert_cycle   = current_cycle;
      way->last_hit_cycle = current_cycle;
      way->hit_count      = 0;
      way->address = fill_mshr.address;
      way->v_address = fill_mshr.v_address;
      way->data = fill_mshr.data;
      way->ip = fill_mshr.ip;

      if (NAME == "cpu0_STLB")
        stlb_evict_log.erase(fill_mshr.data >> LOG2_PAGE_SIZE);

      metadata_thru =
          impl_prefetcher_cache_fill(pkt_address, get_set_index(fill_mshr.address), way_idx, fill_mshr.type == PREFETCH, evicting_address, metadata_thru);
      impl_update_replacement_state(fill_mshr.cpu, get_set_index(fill_mshr.address), way_idx, fill_mshr.address, fill_mshr.ip, evicting_address, fill_mshr.type,
                                    false);

      way->pf_metadata = metadata_thru;
    }
  } else {
    assert(fill_mshr.type != WRITE);

    metadata_thru = impl_prefetcher_cache_fill(pkt_address, get_set_index(fill_mshr.address), way_idx, fill_mshr.type == PREFETCH, 0, metadata_thru);
    impl_update_replacement_state(fill_mshr.cpu, get_set_index(fill_mshr.address), way_idx, fill_mshr.address, fill_mshr.ip, 0, fill_mshr.type, false);
  }

  if (success) {
    // COLLECT STATS — skip for synthetic re-insertions (to_return is empty,
    // meaning this fill was not the result of a real miss reaching the lower level).
    if (!fill_mshr.to_return.empty())
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

    if (NAME == "cpu0_STLB" || NAME == "LLC") {
      way->hit_count++;
      way->last_hit_cycle = current_cycle;
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
  if (NAME == "cpu0_STLB")
    stlb_ptr = this;
  impl_prefetcher_initialize();
  impl_initialize_replacement();
}

void CACHE::begin_phase()
{
  roi_stats.emplace_back();
  sim_stats.emplace_back();

  roi_stats.back().name = NAME;
  sim_stats.back().name = NAME;

  // EMA carries forward across phase boundaries naturally — no reset needed.
  // Warmup observations are a reasonable prior for the start of simulation
  // and are downweighted automatically as simulation fills accumulate.
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

  roi_stats.back().evict_total        = sim_stats.back().evict_total;
  roi_stats.back().evict_doa          = sim_stats.back().evict_doa;
  roi_stats.back().evict_mostly_dead  = sim_stats.back().evict_mostly_dead;
  roi_stats.back().evict_mostly_alive = sim_stats.back().evict_mostly_alive;
  roi_stats.back().evict_zero_residence = sim_stats.back().evict_zero_residence;
  roi_stats.back().evict_hit_hist     = sim_stats.back().evict_hit_hist;
  roi_stats.back().evict_doa_on_doa_stlb_page    = sim_stats.back().evict_doa_on_doa_stlb_page;
  roi_stats.back().evict_doa_stlb_resident_alive = sim_stats.back().evict_doa_stlb_resident_alive;
  roi_stats.back().evict_doa_stlb_evicted_doa    = sim_stats.back().evict_doa_stlb_evicted_doa;
  roi_stats.back().evict_doa_stlb_evicted_alive  = sim_stats.back().evict_doa_stlb_evicted_alive;

  roi_stats.back().llt_pc_stats = std::move(sim_stats.back().llt_pc_stats);
  roi_stats.back().llc_pc_stats = std::move(sim_stats.back().llc_pc_stats);
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
