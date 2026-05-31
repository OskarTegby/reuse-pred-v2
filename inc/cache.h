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
#include <deque>
#include <functional>
#include <list>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "champsim.h"
#include "champsim_constants.h"
#include "memory_class.h"
#include "operable.h"

// Bounded history table with pluggable replacement policy.
// Used for both pHIST (PC-indexed) and bHIST (address-indexed).
class HistTable {
public:
  // LFU_DOA: freq increments only on dead (DoA) evictions — a live eviction
  // doesn't confirm bypass utility and shouldn't raise eviction priority.
  // SRRIP: dead eviction → rrpv=0 (protect); live eviction → rrpv=SRRIP_MAX
  // (demote immediately; entry becomes next eviction target and re-enters buffer).
  enum class Policy { LRU, LFU, LFU_DOA, SRRIP };

  struct Stats {
    uint64_t queries       = 0;  // total get() calls
    uint64_t table_hits    = 0;  // get() found the key (value > 0)
    uint64_t promotions    = 0;  // buffer → main table promotions
    uint64_t promoted_hits = 0;  // later get() hits on promoted entries
  };

  HistTable() = default;
  HistTable(uint64_t cap, Policy pol, uint64_t buf_cap = 0)
    : cap_(cap), pol_(pol), entries_(cap), buf_cap_(buf_cap), buffer_(buf_cap) {}

  uint64_t get(uint64_t key) const {
    stats_.queries++;
    for (const auto& e : entries_) {
      if (e.valid && e.key == key) {
        if (e.value > 0) {
          stats_.table_hits++;
          if (e.promoted) { stats_.promoted_hits++; e.promoted = false; }
        }
        return e.value;
      }
    }
    return 0;
  }

  const Stats& get_stats() const { return stats_; }
  void reset_stats() {
    stats_ = Stats{};
    for (auto& e : entries_) e.promoted = false;
  }

  void update(uint64_t key, bool accessed) {
    // 1. Main table hit.
    for (auto& e : entries_) {
      if (e.valid && e.key == key) {
        e.value = accessed ? 0 : std::min(e.value + 1, MAX_COUNTER);
        on_hit(e, accessed);
        return;
      }
    }
    // 2. Promotion buffer.
    if (buf_cap_ > 0) {
      for (auto& b : buffer_) {
        if (b.valid && b.key == key) {
          if (accessed) {
            b.dead_count = 0;
          } else {
            b.dead_count++;
            try_promote();
          }
          return;
        }
      }
      // Not in main table or buffer: stage in buffer (dead evictions only).
      if (!accessed) {
        auto& bslot      = buf_victim();
        bslot.key        = key;
        bslot.dead_count = 1;
        bslot.ts         = ++buf_clock_;
        bslot.valid      = true;
        try_promote();
      }
      return;
    }
    // 3. No buffer: insert directly.
    auto& slot  = victim_slot();
    slot.key    = key;
    slot.value  = accessed ? 0 : 1;
    slot.valid  = true;
    on_insert(slot, accessed);
  }

  void reset(uint64_t key) {
    for (auto& e : entries_)
      if (e.valid && e.key == key) { e.value = 0; return; }
  }

private:
  static constexpr uint64_t MAX_COUNTER = 16;
  static constexpr uint32_t SRRIP_INS  = 2;
  static constexpr uint32_t SRRIP_MAX  = 3;

  struct Entry {
    uint64_t key      = 0;
    uint64_t value    = 0;
    uint64_t freq     = 0;
    uint64_t ts       = 0;
    uint32_t rrpv     = 0;
    bool          valid    = false;
    mutable bool  promoted = false;  // set on buffer promotion; cleared on first hit
  };

  struct BufEntry {
    uint64_t key        = 0;
    uint64_t dead_count = 0;
    uint64_t ts         = 0;
    bool     valid      = false;
  };

  uint64_t cap_         = 0;
  Policy   pol_         = Policy::LRU;
  std::vector<Entry> entries_;
  uint64_t clock_       = 0;
  uint64_t buf_cap_   = 0;
  uint64_t buf_clock_ = 0;
  std::vector<BufEntry> buffer_;
  mutable Stats stats_;

  void on_hit(Entry& e, bool accessed) {
    switch (pol_) {
    case Policy::LRU:     e.ts = ++clock_;                                break;
    case Policy::LFU:     ++e.freq; e.ts = ++clock_;                      break;
    case Policy::LFU_DOA: if (!accessed) ++e.freq; e.ts = ++clock_;       break;
    // Dead → protect (rrpv=0). Live → demote to eviction target (rrpv=SRRIP_MAX);
    // victim_slot() will then evict it and re-enter it into the buffer.
    case Policy::SRRIP:   e.rrpv = accessed ? SRRIP_MAX : 0;              break;
    }
  }

  void on_insert(Entry& e, bool accessed) {
    e.promoted = false;
    switch (pol_) {
    case Policy::LRU:     e.ts = ++clock_; e.freq = 0; e.rrpv = 0;               break;
    case Policy::LFU:     e.freq = 1; e.ts = ++clock_; e.rrpv = 0;               break;
    case Policy::LFU_DOA: e.freq = accessed ? 0 : 1; e.ts = ++clock_; e.rrpv = 0; break;
    case Policy::SRRIP:   e.rrpv = SRRIP_INS; e.freq = 0; e.ts = 0;              break;
    }
  }

  // Promoted entries enter with higher priority than cold insertions.
  void on_promote(Entry& e, uint64_t dead_count) {
    e.promoted = true;
    switch (pol_) {
    case Policy::LRU:     e.ts = ++clock_; e.freq = 0; e.rrpv = 0;        break;
    case Policy::LFU:
    case Policy::LFU_DOA: e.freq = dead_count; e.ts = ++clock_; e.rrpv = 0; break;
    case Policy::SRRIP:   e.rrpv = 0; e.freq = 0; e.ts = 0;               break;
    }
  }

  // Promote the best buffer entry into the main table when it beats the worst
  // main table entry. The displaced main table entry re-enters the buffer with
  // dead_count=0 so it must re-prove relevance before being re-admitted.
  void try_promote() {
    // Find best buffer candidate: max dead_count, newest ts as tiebreak.
    BufEntry* best = nullptr;
    for (auto& b : buffer_) {
      if (!b.valid || b.dead_count == 0) continue;
      if (!best || b.dead_count > best->dead_count ||
          (b.dead_count == best->dead_count && b.ts > best->ts))
        best = &b;
    }
    if (!best) return;

    // Check whether best buffer entry beats worst main table entry.
    bool promote = false;
    for (const auto& e : entries_) if (!e.valid) { promote = true; break; }
    if (!promote) {
      switch (pol_) {
      case Policy::LRU:
      case Policy::LFU:
      case Policy::LFU_DOA: {
        uint64_t min_freq = UINT64_MAX;
        for (const auto& e : entries_) min_freq = std::min(min_freq, e.freq);
        promote = best->dead_count > min_freq;
        break;
      }
      case Policy::SRRIP:
        for (const auto& e : entries_)
          if (e.rrpv == SRRIP_MAX) { promote = true; break; }
        break;
      }
    }
    if (!promote) return;

    // Evict worst main table entry → re-enter into best's buffer slot.
    stats_.promotions++;
    auto& slot = victim_slot();
    const bool has_victim = slot.valid;
    const uint64_t victim_key = has_victim ? slot.key : 0;
    slot.key   = best->key;
    slot.value = best->dead_count;
    slot.valid = true;
    on_promote(slot, best->dead_count);
    best->key        = has_victim ? victim_key : 0;
    best->dead_count = 0;
    best->ts         = has_victim ? ++buf_clock_ : 0;
    best->valid      = has_victim;
  }

  Entry& victim_slot() {
    for (auto& e : entries_) if (!e.valid) return e;
    switch (pol_) {
    case Policy::LRU:
      return *std::min_element(entries_.begin(), entries_.end(),
        [](const Entry& a, const Entry& b){ return a.ts < b.ts; });
    case Policy::LFU:
    case Policy::LFU_DOA:
      return *std::min_element(entries_.begin(), entries_.end(),
        [](const Entry& a, const Entry& b){
          return a.freq < b.freq || (a.freq == b.freq && a.ts < b.ts); });
    case Policy::SRRIP:
      for (;;) {
        for (auto& e : entries_) if (e.rrpv == SRRIP_MAX) return e;
        for (auto& e : entries_) e.rrpv = std::min(e.rrpv + 1, SRRIP_MAX);
      }
    }
    return entries_[0];
  }

  // DoA-LFU eviction: evict the buffer entry with the fewest dead confirmations.
  // ts (insertion time) breaks ties — evict the older entry among equals.
  BufEntry& buf_victim() {
    for (auto& b : buffer_) if (!b.valid) return b;
    return *std::min_element(buffer_.begin(), buffer_.end(),
      [](const BufEntry& a, const BufEntry& b){
        return a.dead_count < b.dead_count ||
               (a.dead_count == b.dead_count && a.ts < b.ts); });
  }
};

// Two-level history table: PC → { block address → dead-confirmation counter }.
// Outer level: up to pc_ways distinct dpPred PCs, DoA-LFU eviction.
// Inner level: up to addr_ways block addresses per PC, DoA-LFU eviction.
// Both freq counters increment only on dead evictions (DoA-LFU).
// Optional per-PC addr promotion buffer: new addr entries stage here and are
// promoted to the inner table only when their dead count exceeds the weakest
// current addr entry's freq.
class PCPartitionedTable {
public:
  PCPartitionedTable() = default;
  PCPartitionedTable(uint64_t pc_ways, uint64_t addr_ways, uint64_t addr_buf_cap = 0)
    : addr_ways_(addr_ways), addr_buf_cap_(addr_buf_cap), entries_(pc_ways)
  {
    for (auto& e : entries_) {
      e.addrs.resize(addr_ways);
      e.buf.resize(addr_buf_cap);
    }
  }

  uint64_t get(uint64_t pc, uint64_t addr) const {
    for (const auto& e : entries_) {
      if (!e.valid || e.pc != pc) continue;
      for (const auto& a : e.addrs)
        if (a.valid && a.addr == addr) return a.count;
      return 0;
    }
    return 0;
  }

  // Increment counter on dead eviction (!accessed); reset to 0 on live eviction.
  void update(uint64_t pc, uint64_t addr, bool accessed) {
    // --- PC level: find or insert ---
    PCEntry* pe = nullptr;
    for (auto& e : entries_)
      if (e.valid && e.pc == pc) { pe = &e; break; }
    if (!pe) {
      pe = &evict_pc();
      pe->pc    = pc;
      pe->valid = true;
      pe->freq  = 0;
      for (auto& a : pe->addrs) a = AddrEntry{};
      for (auto& b : pe->buf)   b = BufEntry{};
    }
    if (!accessed) pe->freq++;  // DoA-LFU at PC level

    // --- Addr level: check main slots ---
    for (auto& a : pe->addrs) {
      if (a.valid && a.addr == addr) {
        a.count = accessed ? 0 : std::min(a.count + 1, MAX_COUNTER);
        if (!accessed) a.freq++;
        return;
      }
    }

    // --- Addr level: check promotion buffer ---
    if (addr_buf_cap_ > 0) {
      for (auto& b : pe->buf) {
        if (b.valid && b.addr == addr) {
          if (accessed) {
            b.dead_count = 0;
          } else {
            b.dead_count++;
            if (b.dead_count > addr_lfu_victim_freq(*pe)) {
              auto& slot  = evict_addr(*pe);
              slot.addr   = b.addr;
              slot.count  = b.dead_count;
              slot.freq   = b.dead_count;
              slot.valid  = true;
              b = BufEntry{};
            }
          }
          return;
        }
      }
      // New addr: add to buffer (dead evictions only).
      if (!accessed) {
        auto& bslot      = buf_victim(*pe);
        bslot.addr       = addr;
        bslot.dead_count = 1;
        bslot.ts         = ++buf_clock_;
        bslot.valid      = true;
      }
      return;
    }

    // --- No buffer: insert directly ---
    if (!accessed) {
      auto& slot  = evict_addr(*pe);
      slot.addr   = addr;
      slot.count  = 1;
      slot.freq   = 1;
      slot.valid  = true;
    }
  }

private:
  static constexpr uint64_t MAX_COUNTER = 16;

  struct AddrEntry {
    uint64_t addr  = 0;
    uint64_t count = 0;
    uint64_t freq  = 0;  // DoA-LFU: dead confirmation count
    bool     valid = false;
  };
  struct BufEntry {
    uint64_t addr       = 0;
    uint64_t dead_count = 0;
    uint64_t ts         = 0;
    bool     valid      = false;
  };
  struct PCEntry {
    uint64_t pc    = 0;
    uint64_t freq  = 0;  // DoA-LFU: total dead confirmations across all addrs
    bool     valid = false;
    std::vector<AddrEntry> addrs;
    std::vector<BufEntry>  buf;
  };

  uint64_t addr_ways_    = 0;
  uint64_t addr_buf_cap_ = 0;
  uint64_t buf_clock_    = 0;
  std::vector<PCEntry> entries_;

  PCEntry& evict_pc() {
    for (auto& e : entries_) if (!e.valid) return e;
    return *std::min_element(entries_.begin(), entries_.end(),
      [](const PCEntry& a, const PCEntry& b){ return a.freq < b.freq; });
  }

  uint64_t addr_lfu_victim_freq(const PCEntry& pe) const {
    uint64_t min_f = UINT64_MAX;
    for (const auto& a : pe.addrs) {
      if (!a.valid) return 0;
      min_f = std::min(min_f, a.freq);
    }
    return min_f;
  }

  AddrEntry& evict_addr(PCEntry& pe) {
    for (auto& a : pe.addrs) if (!a.valid) return a;
    return *std::min_element(pe.addrs.begin(), pe.addrs.end(),
      [](const AddrEntry& a, const AddrEntry& b){ return a.freq < b.freq; });
  }

  BufEntry& buf_victim(PCEntry& pe) {
    for (auto& b : pe.buf) if (!b.valid) return b;
    return *std::min_element(pe.buf.begin(), pe.buf.end(),
      [](const BufEntry& a, const BufEntry& b){ return a.ts < b.ts; });
  }
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

  uint64_t llt_bypasses = 0;
  uint64_t llc_bypasses = 0;
  uint64_t pfq_hits = 0;              // LLC fills where PFN was in PFQ (dp=true)
  uint64_t cbpred_nogate_bypasses = 0; // LLC bypasses that fired without a PFQ hit

  // DoA liveness stats.
  // For every cache: evictions = valid blocks displaced; doa = those never accessed.
  // For LLC only: doa_stlb_found / doa_stlb_also_doa track the reverse-STLB lookup
  // on each LLC DoA eviction — how often the corresponding STLB entry is still present
  // and also unaccessed (i.e., the LLC and STLB DoA are correlated).
  uint64_t evictions = 0;
  uint64_t doa = 0;
  uint64_t doa_stlb_found    = 0; // LLC DoA evictions where STLB entry was present
  uint64_t doa_stlb_also_doa = 0; // of those, STLB entry also had accessed == false

  // History table utilisation (ROI only, reset at warmup boundary).
  uint64_t phist_queries       = 0;
  uint64_t phist_table_hits    = 0;
  uint64_t phist_promotions    = 0;
  uint64_t phist_promoted_hits = 0;
  uint64_t bhist_queries       = 0;
  uint64_t bhist_table_hits    = 0;
  uint64_t bhist_promotions    = 0;
  uint64_t bhist_promoted_hits = 0;
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

// Liveness classification for cache blocks based on eviction history
enum class liveness_class { doa, mostly_dead, mostly_alive };

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
    bool accessed = false; // set on hit; read and cleared on eviction
    bool dp = false;       // dead-page bit: set on LLC fill when the block's PFN is in the PFQ;
                           // gates accessed tracking and bHIST updates (cbPred only)
    uint64_t dp_pc = 0;   // dpPred PC stored at fill time (valid when dp=true)

    uint64_t address = 0;
    uint64_t v_address = 0;
    uint64_t data = 0;
    uint64_t ip = 0; // PC that caused the miss that filled this block

    uint32_t pf_metadata = 0;
  };
  using set_type = std::vector<BLOCK>;

  std::pair<set_type::iterator, set_type::iterator> get_set_span(uint64_t address);
  std::pair<set_type::const_iterator, set_type::const_iterator> get_set_span(uint64_t address) const;
  std::size_t get_set_index(uint64_t address) const;

  // ── dpPred-cbPred predictor ──────────────────────────────────────────────

  // Shared physical-frame queue: dpPred fills it; cbPred reads it.
  // Each entry is (PFN, dpPred PC) so cbPred can use the PC as the bHIST key.
  inline static std::deque<std::pair<uint64_t, uint64_t>> pfq{};
  inline static uint64_t pfq_cap = 8;

  // Set by cpu0_STLB during initialize(); read by LLC for reverse STLB DoA lookup.
  inline static const set_type* stlb_block_ptr = nullptr;

  // Per-instance state
  bool dppred = false;
  bool cbpred = false;
  uint64_t pconf_thd = 6; // phist confidence threshold
  uint64_t bconf_thd = 6; // bhist confidence threshold
  uint64_t mid_thd = 1;   // min DoA-or-mostly-dead evictions before liveness guidance triggers
  bool mid_promote = false; // promote DoA blocks to MRU on hit (srrip_live)
  uint64_t st_size = 2;   // shadow table capacity

  HistTable phist;           // PC → confidence (dpPred)
  // cbPred bHIST: two modes selected by BHIST_MODE env var.
  //   "flat" (default): HistTable keyed by block address (addr-indexed, exp004 style)
  //   "pc":  PCPartitionedTable keyed by (dpPred PC, block address) — requires PFQ hit
  bool use_pc_bhist = false;
  HistTable          bhist_flat;  // used when use_pc_bhist=false
  PCPartitionedTable bhist_pc;    // used when use_pc_bhist=true
  std::deque<std::tuple<uint64_t, uint64_t, uint64_t>> shadow_table; // (VPN, data, PC)

  // Replacement guidance: use bHIST dead_count signals to guide cache replacement.
  // High dead_count → entry is often dead → better eviction target (prioritize eviction).
  // Used to integrate bypass predictor signals into replacement decisions.
  bool repl_guidance_enable = false;  // enable replacement guidance from bHIST
  uint64_t repl_guidance_thd = 0;     // threshold: dead_count >= thd → good victim

  // Query bHIST for guidance score (dead_count) of a block for replacement.
  // Returns the dead_count from bHIST, or 0 if not found or guidance disabled.
  uint64_t get_repl_guidance_score(uint64_t block_address, uint64_t dp_pc) const;

  // Classify block liveness based on PC-indexed bHIST DoA/mostly_dead counters.
  // Used by srrip_live and ipv_live replacement policies to guide insertion/promotion.
  liveness_class classify_block_liveness(uint64_t block_address, uint64_t pc) const;

  // Unbounded characterization: track all (PC, address) pairs to measure actual demand.
  // Enables data-driven sizing decisions: how many PCs and addresses per PC do we actually see?
  bool characterization_enable = false;
  std::map<uint64_t, std::set<uint64_t>> pc_to_addrs;  // PC → set of unique addresses
  void record_characterization(uint64_t dp_pc, uint64_t block_address);
  void print_characterization_stats() const;

  // PFQ gate control: when false, cbPred bypasses on bhist alone (no PFQ hit required).
  // pfq_ema_mode tracks the hit rate with an EMA and dynamically flips pfq_gate.
  bool pfq_gate = true;
  bool pfq_ema_mode = false;
  double pfq_ema_val = 1.0;           // starts at 100% → gate starts ON
  double pfq_ema_alpha = 1.0 / 1024.0;
  double pfq_ema_thd = 0.10;          // gate turns OFF when EMA drops below this

  static constexpr unsigned  VPN_BITS    = 4;
  static constexpr unsigned  PC_BITS     = 6;
  static constexpr unsigned  BHT_BITS    = 12;
  static constexpr uint64_t  MAX_COUNTER = 16;

  uint64_t fold_xor(uint64_t val, unsigned bits) const;
  void load_predictor_settings();                          // reads env vars to configure dpPred/cbPred at construction
  bool dppred_shadow_lookup(const PACKET& handle_pkt);     // true → shadow hit: history reset, data served, entry re-inserted into STLB, PTW skipped
  bool dppred_bypass(const PACKET& fill_mshr);             // true → skip STLB fill
  bool cbpred_bypass(const PACKET& fill_mshr);             // true → skip LLC fill
  void update_eviction_counters(const BLOCK& victim);      // update the history table for this cache level

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
