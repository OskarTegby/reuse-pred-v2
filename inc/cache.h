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

#ifndef CACHE_H
#define CACHE_H

#include <array>
#include <bitset>
#include <cassert>
#include <cstdlib>
#include <deque>
#include <fstream>
#include <functional>
#include <list>
#include <map>
#include <set>
#include <unordered_map>
#include <unordered_set>
#include <string>
#include <tuple>
#include <vector>

#include "champsim.h"
#include "champsim_constants.h"
#include "memory_class.h"
#include "operable.h"

enum class liveness_class { doa, alive };

class HistTable {
public:
  enum class Policy { LFU_DOA };

  struct Stats {
    uint64_t queries       = 0;
    uint64_t table_hits    = 0;
    uint64_t promotions    = 0;
    uint64_t promoted_hits = 0;
    bool     main_ever_full = false;
    bool     buf_ever_full  = false;
    uint64_t buf_evictions       = 0;
    uint64_t shadow_hits         = 0;
    uint64_t shadow_hit_doa_sum  = 0;
    uint64_t shadow_hit_nonzero  = 0;
    uint64_t doa_buf_miss            = 0;
    uint64_t demotions               = 0;
    uint64_t second_chance_promotions = 0;
    uint64_t second_chance_evictions  = 0;
    uint64_t promote_attempts        = 0;
    uint64_t promote_blocked         = 0;
    uint64_t buf_evict_dc_hist[6]   = {};
    uint64_t buf_promo_dc_hist[6]   = {};
    mutable uint64_t classify_main      = 0;
    mutable uint64_t classify_buf_guided= 0;
    mutable uint64_t classify_buf_weak  = 0;
    mutable uint64_t classify_warm_miss        = 0;
    mutable uint64_t classify_warm_buf_evicted = 0;
    mutable uint64_t classify_warm_oracle_hit  = 0;
    mutable uint64_t classify_warm_aged_out    = 0;
    mutable uint64_t classify_warm_aged_hitsum = 0;
    mutable uint64_t classify_cold_miss        = 0;
    uint64_t trans_alive_doa = 0;
    uint64_t trans_doa_alive = 0;
  };

  HistTable() : unbounded_(true) {}
  HistTable(uint64_t cap, Policy pol, uint64_t buf_cap = 0, uint64_t shadow_cap = 0);

  void set_hash(unsigned bits) { hash_bits_ = bits; }

  void set_reset_period(uint64_t period) { reset_period_ = period; }
  void set_bypass_pc_reset(uint64_t period) { bypass_pc_reset_period_ = period; }

  void set_doa_default_pct(int pct) { doa_default_pct_ = pct; }

  void set_doa_force_pct(int pct) { doa_force_pct_ = pct; }
  void maybe_force_doa(uint64_t key, int64_t value);

  void record_bypass(uint64_t key);

  void reset_scores() {
    if (unbounded_) { for (auto& [k, v] : unmap_) v = 0; }
    else            { for (auto& e : entries_) e.score = 0; }
  }

  void erase_key(uint64_t key);

  enum class RecheckMode { Off, Fixed, Backoff };
  void set_recheck(RecheckMode mode, uint64_t base, uint64_t cap) {
    recheck_mode_ = mode; recheck_base_ = base ? base : 1;
    recheck_cap_  = cap   ? cap  : recheck_base_;
  }

  bool should_probe(uint64_t key);

  uint64_t recheck_probes() const { return recheck_probes_; }

  int64_t get_score(uint64_t key) const;

  liveness_class classify(uint64_t key, uint64_t thd_doa) const;

  const Stats& get_stats() const { return stats_; }
  void reset_stats() {
    stats_ = Stats{};
    for (auto& e : entries_) e.promoted = false;
  }

  void print_stats(const char* prefix, uint64_t thd_doa = 0) const;

  void update(uint64_t key, liveness_class evict_class, int64_t thd_doa = 0);

  void reset(uint64_t key) {
    key = hk_(key);
    for (auto& e : entries_)
      if (e.valid && e.key == key) { e.score = 0; return; }
  }

private:
  static constexpr uint32_t SRRIP_INS  = 2;
  static constexpr uint32_t SRRIP_MAX  = 3;
  static constexpr uint64_t FREQ_CAP   = 64;
  int ma_penalty_ = -2;

  static uint64_t fold_(uint64_t val, unsigned bits) {
    uint64_t result = 0;
    const uint64_t mask = (1ULL << bits) - 1;
    for (unsigned i = 0; i < 32u / bits; ++i, val >>= bits)
      result ^= (val & mask);
    return result;
  }
  uint64_t hk_(uint64_t key) const { return hash_bits_ ? fold_(key, hash_bits_) : key; }

  struct Entry {
    uint64_t key              = 0;
    int64_t  score            = 0;
    uint64_t freq             = 0;
    uint64_t ts               = 0;
    uint64_t last_seen_update = 0;
    uint64_t ma_loss          = 0;
    uint64_t hit_count        = 0;
    uint32_t rrpv             = 0;
    bool          valid    = false;
    mutable bool  promoted = false;
  };

  struct BufEntry {
    uint64_t key          = 0;
    uint64_t dead_count   = 0;
    uint64_t ts           = 0;
    bool     valid        = false;
    bool     second_chance = false;
  };

  bool        unbounded_           = false;
  uint64_t    reset_period_        = 0;
  uint64_t    update_count_        = 0;
  uint64_t bypass_pc_reset_period_{0};
  mutable std::unordered_map<uint64_t, uint64_t> bypass_since_update_;
  RecheckMode recheck_mode_     = RecheckMode::Off;
  uint64_t    recheck_base_     = 0;
  uint64_t    recheck_cap_      = 0;
  uint64_t    recheck_probes_   = 0;
  std::unordered_map<uint64_t, uint64_t> recheck_count_;
  std::unordered_map<uint64_t, uint64_t> recheck_interval_;
  std::unordered_map<uint64_t, bool>     recheck_probing_;
  unsigned hash_bits_ = 0;
  int doa_default_pct_ = 0;
  int doa_force_pct_   = 0;

  static uint64_t mix64_(uint64_t x) {
    x ^= x >> 33; x *= 0xff51afd7ed558ccdULL; x ^= x >> 33;
    x *= 0xc4ceb9fe1a85ec53ULL; x ^= x >> 33;
    return x;
  }
  bool doa_default_(uint64_t key) const {
    return doa_default_pct_ > 0 && (mix64_(key) % 100) < static_cast<uint64_t>(doa_default_pct_);
  }
  mutable std::unordered_map<uint64_t, int64_t> unmap_;
  uint64_t cap_          = 0;
  Policy   pol_          = Policy::LFU_DOA;
  std::vector<Entry>    entries_;
  uint64_t clock_        = 0;
  uint64_t buf_cap_      = 0;
  uint64_t buf_clock_    = 0;
  std::vector<BufEntry> buffer_;
  std::unordered_set<uint64_t> seen_pcs_;
  mutable std::unordered_set<uint64_t> buf_evicted_pcs_;
  std::unordered_map<uint64_t, uint64_t> shadow_map_;
  std::unordered_map<uint64_t, uint64_t> oracle_buf_;
  mutable Stats stats_;
  uint64_t evict_count_          = 0;
  uint64_t evict_ma_nonzero_     = 0;
  uint64_t evict_ma_loss_sum_    = 0;
  uint64_t evict_ma_decisive_    = 0;
  uint64_t evict_aging_nonzero_  = 0;
  uint64_t evict_aging_loss_sum_ = 0;
  uint64_t evict_aging_decisive_ = 0;
  uint64_t evict_aging_hitsum_   = 0;
  int64_t  thd_doa_cache_  = 0;
  std::unordered_map<uint64_t, std::pair<int64_t,uint64_t>> aging_evicted_pcs_;

  void on_hit(Entry& e, liveness_class evict_class);
  void on_insert(Entry& e, liveness_class evict_class);
  void on_promote(Entry& e, uint64_t dead_count);
  void try_promote();
  Entry& victim_slot();
  BufEntry& buf_victim();
};

struct cache_stats {
  std::string name;
  // prefetch stats
  uint64_t pf_requested = 0;
  uint64_t pf_issued = 0;
  uint64_t pf_useful = 0;
  uint64_t pf_useless = 0;
  uint64_t pf_fill = 0;

  std::array<std::array<uint64_t, NUM_CPUS>, NUM_TYPES> hits = {};
  std::array<std::array<uint64_t, NUM_CPUS>, NUM_TYPES> misses = {};

  uint64_t total_miss_latency = 0;

  uint64_t liveness_bypasses = 0;
  uint64_t liveness_probes   = 0;
  uint64_t liveness_bypass_shadow_hits = 0;

  uint64_t evictions    = 0;
  uint64_t doa          = 0;
};

struct cache_queue_stats {
  uint64_t RQ_ACCESS = 0;
  uint64_t RQ_MERGED = 0;
  uint64_t RQ_FULL = 0;
  uint64_t RQ_TO_CACHE = 0;
  uint64_t PQ_ACCESS = 0;
  uint64_t PQ_MERGED = 0;
  uint64_t PQ_FULL = 0;
  uint64_t PQ_TO_CACHE = 0;
  uint64_t WQ_ACCESS = 0;
  uint64_t WQ_MERGED = 0;
  uint64_t WQ_FULL = 0;
  uint64_t WQ_TO_CACHE = 0;
  uint64_t WQ_FORWARD = 0;
  uint64_t PTWQ_ACCESS = 0;
  uint64_t PTWQ_MERGED = 0;
  uint64_t PTWQ_FULL = 0;
  uint64_t PTWQ_TO_CACHE = 0;
};

class CACHE : public champsim::operable, public MemoryRequestConsumer, public MemoryRequestProducer
{
  enum [[deprecated(
      "Prefetchers may not specify arbitrary fill levels. Use CACHE::prefetch_line(pf_addr, fill_this_level, prefetch_metadata) instead.")]] FILL_LEVEL{
      FILL_L1 = 1, FILL_L2 = 2, FILL_LLC = 4, FILL_DRC = 8, FILL_DRAM = 16};

  bool try_hit(const PACKET& handle_pkt);
  bool handle_fill(const PACKET& fill_mshr);
  bool handle_miss(const PACKET& handle_pkt);
  bool handle_write(const PACKET& handle_pkt);

  struct BLOCK {
    bool valid = false;
    bool prefetch = false;
    bool dirty = false;
    bool accessed = false;

    uint64_t address = 0;
    uint64_t v_address = 0;
    uint64_t data = 0;
    uint64_t ip = 0;

    uint32_t pf_metadata = 0;

    uint64_t install_cycle   = 0;
  };
  using set_type = std::vector<BLOCK>;

  std::pair<set_type::iterator, set_type::iterator> get_set_span(uint64_t address);
  std::pair<set_type::const_iterator, set_type::const_iterator> get_set_span(uint64_t address) const;
  std::size_t get_set_index(uint64_t address) const;

  uint64_t thd_doa  = 1;

  uint64_t bypass_shadow_cap_ = 0;
  std::unordered_map<uint64_t, std::pair<uint64_t, uint64_t>> bypass_shadow_;
  std::deque<uint64_t> bypass_shadow_fifo_;

  uint64_t last_fill_latency = 0;

  HistTable repl_hist_pc;
  bool repl_hist_use_addr{false};

  bool doa_trace_enable_ = false;
  std::ofstream doa_trace_file_;
  bool liveness_bypass{false};
  uint64_t bypass_thd{0};

  liveness_class classify_block_liveness(uint64_t block_address, uint64_t pc) const;

  struct AddrCounterEntry { int64_t score = 0; bool ever_reset = false; };
  bool doa_addr_summary_enable_ = false;
  std::unordered_map<uint64_t, std::unordered_map<uint64_t, AddrCounterEntry>> doa_addr_table_;
  std::unordered_map<uint64_t, uint64_t> doa_addr_pc_doa_total_;
  void record_doa_addr_summary(uint64_t pc, uint64_t addr, liveness_class evict_lv);
  void print_doa_addr_summary() const;

  void load_predictor_settings();
  void configure_thd_doa();
  void configure_repl_hist_table();
  void configure_doa_diagnostics();
  void apply_bypass_recheck(HistTable& tbl);
  void configure_bypass_llc();
  void shadow_record_bypass(uint64_t block_addr, uint64_t pc, uint64_t data);
  bool liveness_bypass_shadow_hit(const PACKET& handle_pkt);
  void update_eviction_counters(const BLOCK& victim, liveness_class lv);
  bool evaluate_liveness_bypass(uint64_t key, uint64_t level_thd, bool enabled);

public:
  struct NonTranslatingQueues : public champsim::operable {
    std::deque<PACKET> RQ, PQ, WQ, PTWQ;
    const std::size_t RQ_SIZE, PQ_SIZE, WQ_SIZE, PTWQ_SIZE;
    const uint64_t HIT_LATENCY;
    const unsigned OFFSET_BITS;
    const bool match_offset_bits;

    using stats_type = cache_queue_stats;

    std::vector<stats_type> sim_stats, roi_stats;

    NonTranslatingQueues(double freq_scale, std::size_t rq_size, std::size_t pq_size, std::size_t wq_size, std::size_t ptwq_size, uint64_t hit_latency,
                         unsigned offset_bits, bool match_offset)
        : champsim::operable(freq_scale), RQ_SIZE(rq_size), PQ_SIZE(pq_size), WQ_SIZE(wq_size), PTWQ_SIZE(ptwq_size), HIT_LATENCY(hit_latency),
          OFFSET_BITS(offset_bits), match_offset_bits(match_offset)
    {
    }
    void operate() override;

    template <typename R>
    bool do_add_queue(R& queue, std::size_t queue_size, const PACKET& packet);

    bool add_rq(const PACKET& packet);
    bool add_wq(const PACKET& packet);
    bool add_pq(const PACKET& packet);
    bool add_ptwq(const PACKET& packet);

    virtual bool is_ready(const PACKET& pkt) const;

    bool rq_has_ready() const;
    bool wq_has_ready() const;
    bool pq_has_ready() const;
    bool ptwq_has_ready() const;

    void begin_phase() override;
    void end_phase(unsigned cpu) override;

  private:
    void check_collision();
  };

  struct TranslatingQueues : public NonTranslatingQueues, public MemoryRequestProducer {
    void operate() override final;

    void issue_translation();
    void detect_misses();

    template <typename R>
    void do_issue_translation(R& queue);

    template <typename R>
    void do_detect_misses(R& queue);

    virtual bool is_ready(const PACKET& pkt) const override final;

    void return_data(const PACKET& packet) override final;

    using NonTranslatingQueues::NonTranslatingQueues;
  };

  uint32_t cpu = 0;
  const std::string NAME;
  const uint32_t NUM_SET, NUM_WAY, MSHR_SIZE;
  const uint32_t FILL_LATENCY;
  const unsigned OFFSET_BITS;
  set_type block{NUM_SET * NUM_WAY};
  const long int MAX_TAG, MAX_FILL;
  const bool prefetch_as_load;
  const bool match_offset_bits;
  const bool virtual_prefetch;
  bool ever_seen_data = false;
  const unsigned pref_activate_mask = (1 << static_cast<int>(LOAD)) | (1 << static_cast<int>(PREFETCH));

  using stats_type = cache_stats;

  std::vector<stats_type> sim_stats{}, roi_stats{};

  NonTranslatingQueues& queues;
  std::deque<PACKET> MSHR;
  std::deque<PACKET> inflight_writes;

  // functions
  bool add_rq(const PACKET& packet) override final;
  bool add_wq(const PACKET& packet) override final;
  bool add_pq(const PACKET& packet) override final;
  bool add_ptwq(const PACKET& packet) override final;

  void return_data(const PACKET& packet) override final;
  void operate() override final;

  void initialize() override final;
  void begin_phase() override final;
  void end_phase(unsigned cpu) override final;

  std::size_t get_occupancy(uint8_t queue_type, uint64_t address) override final;
  std::size_t get_size(uint8_t queue_type, uint64_t address) override final;

  [[deprecated("Use get_set_index() instead.")]] uint64_t get_set(uint64_t address) const;
  [[deprecated("This function should not be used to access the blocks directly.")]] uint64_t get_way(uint64_t address, uint64_t set) const;

  uint64_t invalidate_entry(uint64_t inval_addr);
  int prefetch_line(uint64_t pf_addr, bool fill_this_level, uint32_t prefetch_metadata);

  [[deprecated("Use CACHE::prefetch_line(pf_addr, fill_this_level, prefetch_metadata) instead.")]] int
  prefetch_line(uint64_t ip, uint64_t base_addr, uint64_t pf_addr, bool fill_this_level, uint32_t prefetch_metadata);

  bool should_activate_prefetcher(const PACKET& pkt) const;

  void print_deadlock() override;

#include "cache_modules.inc"

  const std::bitset<NUM_REPLACEMENT_MODULES> repl_type;
  const std::bitset<NUM_PREFETCH_MODULES> pref_type;

  // constructor
  CACHE(std::string v1, double freq_scale, uint32_t v2, uint32_t v3, uint32_t v8, uint32_t fill_lat, long int max_tag, long int max_fill, unsigned offset_bits,
        bool pref_load, bool wq_full_addr, bool va_pref, unsigned pref_mask, NonTranslatingQueues& queue_set, MemoryRequestConsumer* ll,
        std::bitset<NUM_PREFETCH_MODULES> pref, std::bitset<NUM_REPLACEMENT_MODULES> repl)
      : champsim::operable(freq_scale), MemoryRequestProducer(ll), NAME(v1), NUM_SET(v2), NUM_WAY(v3), MSHR_SIZE(v8), FILL_LATENCY(fill_lat),
        OFFSET_BITS(offset_bits), MAX_TAG(max_tag), MAX_FILL(max_fill), prefetch_as_load(pref_load), match_offset_bits(wq_full_addr), virtual_prefetch(va_pref),
        pref_activate_mask(pref_mask), queues(queue_set), repl_type(repl), pref_type(pref)
  {
    load_predictor_settings();
  }
};

#endif
