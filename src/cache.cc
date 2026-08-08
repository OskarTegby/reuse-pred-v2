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
#include <iomanip>
#include <iterator>
#include <numeric>

#include "champsim.h"
#include "champsim_constants.h"
#include "instruction.h"
#include "util.h"

namespace
{
bool doa_streak_probe_enabled()
{
  static const bool enabled = [] {
    const char* v = std::getenv("DOA_STREAK_PROBE");
    return v && v[0] != '\0' && v[0] != '0';
  }();
  return enabled;
}
} // namespace

bool CACHE::handle_fill(const PACKET& fill_mshr)
{
  cpu = fill_mshr.cpu;

  // find victim
  auto [set_begin, set_end] = get_set_span(fill_mshr.address);
  auto way = std::find_if_not(set_begin, set_end, [](auto x) { return x.valid; });
  bool policy_skipped_fill = false;
  if (way == set_end) {
    const auto victim_idx = impl_find_victim(fill_mshr.cpu, fill_mshr.instr_id, get_set_index(fill_mshr.address), &*set_begin, fill_mshr.ip,
                                                fill_mshr.address, fill_mshr.type);
    if (victim_idx < NUM_WAY)
      way = std::next(set_begin, victim_idx);
    else
      policy_skipped_fill = true; // way stays == set_end
  }

  const bool fill_bypassed = resolve_fill_bypass(fill_mshr, way, set_end) || policy_skipped_fill;

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
  const uint64_t fill_latency = current_cycle - (fill_mshr.cycle_enqueued + 1);
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
        record_doa_streak_eviction(way->ip, way->accessed);
        if (way->read_hit)        ++ev_read;
        else if (way->write_hit)  ++ev_write_only;
        else                      ++ev_untouched;
        if (doa_streak_probe_enabled()) {
          unsigned b = 0;
          for (uint64_t v = way->ctr_at_fill; v > 1; v >>= 1) ++b;
          b = std::min<unsigned>(b, 23);
          (way->accessed ? acc_bin_live : acc_bin_doa)[b]++;
          unsigned xb = 0;
          for (uint64_t v = way->xctr_at_fill; v > 1; v >>= 1) ++xb;
          (way->accessed ? xacc_bin_live : xacc_bin_doa)[std::min<unsigned>(xb, 23)]++;
          (way->accessed ? mask_bin_live : mask_bin_doa)[way->xmask_at_fill & 0xF]++;
        }
      }

      way->valid = true;
      way->prefetch = fill_mshr.prefetch_from_this;
      way->dirty = (fill_mshr.type == WRITE);
      way->accessed = false;
      way->write_hit = false;
      way->read_hit = false;
      way->address = fill_mshr.address;
      way->v_address = fill_mshr.v_address;
      way->data = fill_mshr.data;
      way->ip = fill_mshr.ip;
      way->ctr_at_fill = counter_for_fill(fill_mshr.address, fill_mshr.ip);
      way->xctr_at_fill = counter_from_source(fill_mshr.address, fill_mshr.ip);
      way->xmask_at_fill = source_agreement_mask(fill_mshr.address, fill_mshr.ip);
      way->install_cycle  = current_cycle;

      last_fill_latency = fill_latency;

      metadata_thru =
          impl_prefetcher_cache_fill(pkt_address, get_set_index(fill_mshr.address), way_idx, fill_mshr.type == PREFETCH, evicting_address, metadata_thru);
      impl_update_replacement_state(fill_mshr.cpu, get_set_index(fill_mshr.address), way_idx, fill_mshr.address, fill_mshr.ip, evicting_address, fill_mshr.type,
                                    false);

      way->pf_metadata = metadata_thru;
    }
  } else if (fill_bypassed && fill_mshr.type == WRITE) {
    // A bypassed WRITE holds the only up-to-date copy of the line, so declining
    // to allocate it obliges us to send it down rather than drop it.
    PACKET writeback_packet;

    writeback_packet.cpu = fill_mshr.cpu;
    writeback_packet.address = fill_mshr.address;
    writeback_packet.data = fill_mshr.data;
    writeback_packet.instr_id = fill_mshr.instr_id;
    writeback_packet.ip = 0;
    writeback_packet.type = WRITE;
    writeback_packet.pf_metadata = fill_mshr.pf_metadata;

    success = lower_level->add_wq(writeback_packet);
  } else if (!fill_bypassed) {
    assert(fill_mshr.type != WRITE);

    last_fill_latency = fill_latency;

    metadata_thru = impl_prefetcher_cache_fill(pkt_address, get_set_index(fill_mshr.address), way_idx, fill_mshr.type == PREFETCH, 0, metadata_thru);
    impl_update_replacement_state(fill_mshr.cpu, get_set_index(fill_mshr.address), way_idx, fill_mshr.address, fill_mshr.ip, 0, fill_mshr.type, false);
  }

  if (success) {
    // COLLECT STATS
    sim_stats.back().total_miss_latency += fill_latency;

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
    // A writeback absorbed from the level above is a hit that saves a memory write, so
    // whether it counts as "used" is a definitional choice. Mazumdar et al. (HPCA'21)
    // count any hit; we default to reads only. DOA_WRITE_COUNTS=1 selects their definition.
    if (handle_pkt.type == WRITE)
      way->write_hit = true;
    else
      way->read_hit = true;
    if (handle_pkt.type != WRITE || write_hit_counts_as_access())
      way->accessed = true;

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
  impl_prefetcher_initialize();
  impl_initialize_replacement();
}

void CACHE::begin_phase()
{
  roi_stats.emplace_back();
  sim_stats.emplace_back();

  roi_stats.back().name = NAME;
  sim_stats.back().name = NAME;
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

  roi_stats.back().cache_bypasses = sim_stats.back().cache_bypasses;

  roi_stats.back().evictions    = sim_stats.back().evictions;
  roi_stats.back().doa          = sim_stats.back().doa;
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

void CACHE::record_doa_streak_eviction(uint64_t ip, bool accessed)
{
  if (!doa_streak_probe_enabled())
    return;

  auto& h = doa_streak_history[ip];
  h.total_evictions++;
  if (accessed) h.total_alive++; else h.total_doa++;

  if (!h.ever_doa) {
    if (!accessed) {
      h.ever_doa = true;
      h.cur_streak = 1;
    }
    return;
  }
  h.events_since_first_doa++;
  if (!accessed) {
    h.doa_since_first_doa++;
    h.cur_streak++;
  } else {
    h.alive_since_first_doa++;
    if (h.cur_streak > 0) {
      h.streak_sum += h.cur_streak;
      h.streak_count++;
      unsigned b = 0;
      for (uint64_t v = h.cur_streak; v > 1; v >>= 1) ++b;
      streak_hist[std::min<unsigned>(b, 23)]++;
    }
    h.cur_streak = 0;
  }
}

void CACHE::print_doa_streak_stats() const
{
  if (!doa_streak_probe_enabled())
    return;

  uint64_t distinct_pcs = doa_streak_history.size();
  uint64_t pcs_ever_doa = 0;
  uint64_t tot_events_after = 0, tot_doa_after = 0, tot_alive_after = 0;
  double   pc_avg_streak_sum = 0.0;
  uint64_t pc_avg_streak_count = 0;
  uint64_t event_streak_sum = 0, event_streak_count = 0;

  for (const auto& [pc, h] : doa_streak_history) {
    if (!h.ever_doa) continue;
    ++pcs_ever_doa;
    tot_events_after += h.events_since_first_doa;
    tot_doa_after += h.doa_since_first_doa;
    tot_alive_after += h.alive_since_first_doa;

    uint64_t ssum = h.streak_sum, scount = h.streak_count;
    if (h.cur_streak > 0) { ssum += h.cur_streak; scount += 1; }

    event_streak_sum += ssum;
    event_streak_count += scount;
    if (scount > 0) {
      pc_avg_streak_sum += static_cast<double>(ssum) / scount;
      pc_avg_streak_count += 1;
    }
  }

  auto pct = [](uint64_t n, uint64_t d) -> double { return d ? 100.0 * n / d : 0.0; };

  printf("%s DOA-STREAK-PROBE STATS:\n", NAME.c_str());
  {
    uint64_t tot = 0;
    for (auto v : streak_hist) tot += v;
    if (tot > 0) {
      printf("  streak-length histogram (reset values), %lu resets:\n", (unsigned long)tot);
      for (unsigned b = 0; b < streak_hist.size(); ++b) {
        if (streak_hist[b] == 0) continue;
        printf("    STREAKBIN %lu-%lu : %lu (%.2f%%)\n",
               (unsigned long)(1ull << b), (unsigned long)((1ull << (b + 1)) - 1),
               (unsigned long)streak_hist[b], 100.0 * streak_hist[b] / tot);
      }
    }
  }
  {
    uint64_t tot = 0;
    for (auto v : insert_hist) tot += v;
    if (tot > 0) {
      printf("  counter-at-insertion histogram, %lu insertions:\n", (unsigned long)tot);
      for (unsigned b = 0; b < insert_hist.size(); ++b) {
        if (insert_hist[b] == 0) continue;
        printf("    INSBIN %lu-%lu : %lu (%.2f%%)\n",
               (unsigned long)(1ull << b), (unsigned long)((1ull << (b + 1)) - 1),
               (unsigned long)insert_hist[b], 100.0 * insert_hist[b] / tot);
      }
    }
  }
  {
    std::array<uint64_t, 24> pc_bin{}, ev_bin{};
    uint64_t tot_pc = 0, tot_ev = 0;
    for (const auto& [pc, h] : doa_streak_history) {
      if (!h.ever_doa) continue;
      uint64_t ssum = h.streak_sum, scount = h.streak_count;
      if (h.cur_streak > 0) { ssum += h.cur_streak; scount += 1; }
      if (scount == 0) continue;
      unsigned b = 0;
      for (uint64_t v = ssum / scount; v > 1; v >>= 1) ++b;
      b = std::min<unsigned>(b, 23);
      pc_bin[b]++; ev_bin[b] += h.total_doa;
      tot_pc++; tot_ev += h.total_doa;
    }
    if (tot_pc > 0) {
      printf("  per-PC mean streak histogram, %lu PCs, %lu DoA evictions:\n",
             (unsigned long)tot_pc, (unsigned long)tot_ev);
      for (unsigned b = 0; b < pc_bin.size(); ++b) {
        if (pc_bin[b] == 0) continue;
        printf("    PCBIN %lu-%lu : %lu PCs (%.2f%%), %lu DoA evictions (%.2f%%)\n",
               (unsigned long)(1ull << b), (unsigned long)((1ull << (b + 1)) - 1),
               (unsigned long)pc_bin[b], 100.0 * pc_bin[b] / tot_pc,
               (unsigned long)ev_bin[b], tot_ev ? 100.0 * ev_bin[b] / tot_ev : 0.0);
      }
    }
  }
  {
    uint64_t td = 0, tl = 0;
    for (unsigned b = 0; b < acc_bin_doa.size(); ++b) { td += acc_bin_doa[b]; tl += acc_bin_live[b]; }
    if (td + tl > 0) {
      printf("  outcome by counter-at-fill, %lu DoA / %lu live evictions:\n",
             (unsigned long)td, (unsigned long)tl);
      for (unsigned b = 0; b < acc_bin_doa.size(); ++b) {
        uint64_t n = acc_bin_doa[b] + acc_bin_live[b];
        if (n == 0) continue;
        printf("    ACCBIN %lu-%lu : %lu evictions, %lu DoA (P(DoA)=%.2f%%)\n",
               (unsigned long)(1ull << b), (unsigned long)((1ull << (b + 1)) - 1),
               (unsigned long)n, (unsigned long)acc_bin_doa[b], 100.0 * acc_bin_doa[b] / n);
      }
    }
  }
  {
    uint64_t td = 0, tl = 0;
    for (unsigned b = 0; b < xacc_bin_doa.size(); ++b) { td += xacc_bin_doa[b]; tl += xacc_bin_live[b]; }
    if (td + tl > 0) {
      printf("  outcome by SOURCE-level counter-at-fill, %lu DoA / %lu live evictions:\n",
             (unsigned long)td, (unsigned long)tl);
      for (unsigned b = 0; b < xacc_bin_doa.size(); ++b) {
        uint64_t n = xacc_bin_doa[b] + xacc_bin_live[b];
        if (n == 0) continue;
        printf("    XACCBIN %lu-%lu : %lu evictions, %lu DoA (P(DoA)=%.2f%%)\n",
               (unsigned long)(1ull << b), (unsigned long)((1ull << (b + 1)) - 1),
               (unsigned long)n, (unsigned long)xacc_bin_doa[b], 100.0 * xacc_bin_doa[b] / n);
      }
    }
  }
  {
    uint64_t td = 0, tl = 0;
    for (unsigned m = 0; m < 16; ++m) { td += mask_bin_doa[m]; tl += mask_bin_live[m]; }
    if (td + tl > 0) {
      printf("  outcome by source-agreement mask (bit0=L1D bit1=L2C bit2=DTLB bit3=STLB), "
             "%lu DoA / %lu live:\n", (unsigned long)td, (unsigned long)tl);
      for (unsigned m = 0; m < 16; ++m) {
        uint64_t n = mask_bin_doa[m] + mask_bin_live[m];
        if (n == 0) continue;
        printf("    MASKBIN %u%u%u%u : %lu evictions, %lu DoA (P(DoA)=%.2f%%)\n",
               (m >> 3) & 1, (m >> 2) & 1, (m >> 1) & 1, m & 1,
               (unsigned long)n, (unsigned long)mask_bin_doa[m], 100.0 * mask_bin_doa[m] / n);
      }
    }
  }
  // Per-PC behaviour across the hierarchy: for every PC that produced a DoA eviction
  // here, report how the same PC behaved at each other level. One line per PC.
  if (std::getenv("PC_XLEVEL_DUMP")) {
    static const char* kLv[5] = {"cpu0_L1D", "cpu0_L2C", "cpu0_DTLB", "cpu0_STLB", "LLC"};
    printf("%s PC-XLEVEL BEGIN (pc, then per level: evictions/doa for L1D L2C DTLB STLB LLC)\n", NAME.c_str());
    for (const auto& [pc, h] : doa_streak_history) {
      if (h.total_doa == 0) continue;
      printf("    PCXL %lx", (unsigned long)pc);
      for (unsigned i = 0; i < 5; ++i) {
        uint64_t ev = 0, dd = 0;
        if (CACHE* c = lookup_cache(kLv[i])) {
          auto it = c->doa_streak_history.find(pc);
          if (it != c->doa_streak_history.end()) { ev = it->second.total_evictions; dd = it->second.total_doa; }
        }
        printf(" %lu/%lu", (unsigned long)ev, (unsigned long)dd);
      }
      printf("\n");
    }
    printf("%s PC-XLEVEL END\n", NAME.c_str());
  }
  {
    const uint64_t tot3 = ev_untouched + ev_write_only + ev_read;
    if (tot3 > 0)
      printf("  EVICT3 untouched %lu (%.2f%%)  write-only %lu (%.2f%%)  read %lu (%.2f%%)\n",
             (unsigned long)ev_untouched, 100.0 * ev_untouched / tot3,
             (unsigned long)ev_write_only, 100.0 * ev_write_only / tot3,
             (unsigned long)ev_read, 100.0 * ev_read / tot3);
  }
  printf("  Distinct PCs (evicted at least once): %lu\n", distinct_pcs);
  printf("  PCs ever DoA-evicted: %lu (%.1f%% of distinct PCs)\n",
         pcs_ever_doa, pct(pcs_ever_doa, distinct_pcs));
  printf("  Post-first-DoA stickiness: of %lu evictions after a PC's first DoA eviction, "
         "%lu (%.1f%%) were also DoA, %lu (%.1f%%) were alive\n",
         tot_events_after, tot_doa_after, pct(tot_doa_after, tot_events_after),
         tot_alive_after, pct(tot_alive_after, tot_events_after));
  printf("  Avg DoA streak length -- event-weighted: %.2f (n=%lu streaks)  "
         "PC-weighted (mean of each PC's own avg): %.2f (n=%lu PCs)\n",
         event_streak_count ? static_cast<double>(event_streak_sum) / event_streak_count : 0.0, event_streak_count,
         pc_avg_streak_count ? pc_avg_streak_sum / pc_avg_streak_count : 0.0, pc_avg_streak_count);
  printf("\n");
}
