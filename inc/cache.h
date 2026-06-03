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
#include <unordered_map>
#include <unordered_set>
#include <string>
#include <vector>

#include "champsim.h"
#include "champsim_constants.h"
#include "memory_class.h"
#include "operable.h"

enum class liveness_class { doa, mostly_dead, mostly_alive };

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
    // Occupancy
    bool     main_ever_full = false; // true once victim_slot() found no free slot
    bool     buf_ever_full  = false; // true once buf_victim() found no free slot
    // Shadow (victim) buffer: tracks entries fully evicted from the promotion buffer.
    // When an evicted entry's PC appears again, we know useful history was lost.
    uint64_t buf_evictions       = 0;  // entries lost from the promotion buffer
    uint64_t shadow_hits         = 0;  // evicted PCs seen again (before shadow ages out)
    uint64_t shadow_hit_doa_sum  = 0;  // sum of dead_count at eviction for shadow hits
    uint64_t shadow_hit_nonzero  = 0;  // shadow hits where dead_count > 0 at eviction
    // Classification source tracking (set by classify()).
    mutable uint64_t classify_main      = 0;  // resolved from main table
    mutable uint64_t classify_buf       = 0;  // resolved from promotion buffer (main miss)
    mutable uint64_t classify_warm_miss = 0;  // not in table/buf, but found in shadow (recently evicted — accuracy loss)
    mutable uint64_t classify_cold_miss = 0;  // not found anywhere (no prior history — expected)
  };

  // Default: unbounded mode — backed by an unordered_map, no eviction.
  // Semantically identical to the old repl_hist_pc unordered_map; used as the
  // backward-compatible fallback when no capacity limit is configured.
  HistTable() : unbounded_(true) {}
  HistTable(uint64_t cap, Policy pol, uint64_t buf_cap = 0, uint64_t shadow_cap = 0)
    : cap_(cap), pol_(pol), entries_(cap), buf_cap_(buf_cap), buffer_(buf_cap),
      shadow_cap_(shadow_cap), shadow_(shadow_cap) {}

  // Enable periodic occupancy checkpoints to stderr every `interval` update() calls.
  // Call after construction; name labels the output lines.
  void set_checkpoint(uint64_t interval, std::string name) {
    checkpoint_interval_ = interval;
    checkpoint_name_     = std::move(name);
  }

  uint64_t get(uint64_t key) const {
    if (unbounded_) {
      auto it = unmap_.find(key);
      return it != unmap_.end() ? it->second.first : 0;
    }
    stats_.queries++;
    for (const auto& e : entries_) {
      if (e.valid && e.key == key) {
        if (e.doa > 0) {
          stats_.table_hits++;
          if (e.promoted) { stats_.promoted_hits++; e.promoted = false; }
        }
        return e.doa;
      }
    }
    return 0;
  }

  uint64_t get_dead(uint64_t key) const {
    if (unbounded_) {
      auto it = unmap_.find(key);
      return it != unmap_.end() ? it->second.second : 0;
    }
    for (const auto& e : entries_)
      if (e.valid && e.key == key) return e.mostly_dead;
    return 0;
  }

  // Returns {doa, mostly_dead} in one scan — use instead of separate get()+get_dead()
  // calls when both values are needed (avoids scanning entries_ twice in bounded mode).
  std::pair<uint64_t,uint64_t> get_both(uint64_t key) const {
    if (unbounded_) {
      auto it = unmap_.find(key);
      return it != unmap_.end() ? it->second : std::pair<uint64_t,uint64_t>{0, 0};
    }
    for (const auto& e : entries_)
      if (e.valid && e.key == key) return {e.doa, e.mostly_dead};
    return {0, 0};
  }

  // Classify a PC against mid_thd / low_thd, consulting main table then promotion
  // buffer. Tracks which structure resolved the classification in stats.
  liveness_class classify(uint64_t key, uint64_t mid_thd, uint64_t low_thd) const {
    if (unbounded_) {
      auto it = unmap_.find(key);
      if (it != unmap_.end()) {
        const auto [doa, dead] = it->second;
        if (doa  >= mid_thd)                return liveness_class::doa;
        if (low_thd > 0 && dead >= low_thd) return liveness_class::mostly_dead;
      }
      return liveness_class::mostly_alive;
    }
    // 1. Main table.
    for (const auto& e : entries_) {
      if (e.valid && e.key == key) {
        if (e.doa >= mid_thd) {
          ++stats_.classify_main;
          return liveness_class::doa;
        }
        if (low_thd > 0 && e.mostly_dead >= low_thd) {
          ++stats_.classify_main;
          return liveness_class::mostly_dead;
        }
        // Found in table but below threshold — counts as main hit (evidence exists).
        ++stats_.classify_main;
        return liveness_class::mostly_alive;
      }
    }
    // 2. Promotion buffer: can only signal DoA (buffer tracks dead_count only).
    for (const auto& b : buffer_) {
      if (b.valid && b.key == key) {
        if (b.dead_count >= mid_thd) {
          ++stats_.classify_buf;
          return liveness_class::doa;
        }
        ++stats_.classify_buf;  // found in buffer but below threshold
        return liveness_class::mostly_alive;
      }
    }
    // 3. Not found anywhere. Warm miss: PC was seen before (entry evicted).
    // Cold miss: PC has never generated an eviction — no history to lose.
    if (!seen_pcs_.empty() && seen_pcs_.count(key))
      ++stats_.classify_warm_miss;
    else
      ++stats_.classify_cold_miss;
    return liveness_class::mostly_alive;
  }

  const Stats& get_stats() const { return stats_; }
  void reset_stats() {
    stats_ = Stats{};
    for (auto& e : entries_) e.promoted = false;
  }

  // Print occupancy and shadow-buffer instrumentation to stdout.
  // mid_thd: used to flag shadow hits where dead_count >= mid_thd, meaning the
  // next block from that PC was misclassified (should have been DoA but was mostly_alive).
  void print_stats(const char* prefix, uint64_t mid_thd = 0, uint64_t low_thd = 0) const {
    if (unbounded_) {
      printf("%s repl_hist: unbounded (%zu entries)\n", prefix, unmap_.size());
      return;
    }
    const uint64_t main_occ = static_cast<uint64_t>(
        std::count_if(entries_.begin(), entries_.end(), [](const Entry& e){ return e.valid; }));
    const uint64_t buf_occ  = static_cast<uint64_t>(
        std::count_if(buffer_.begin(), buffer_.end(), [](const BufEntry& b){ return b.valid; }));
    printf("%s repl_hist occupancy : main %lu/%lu (%.0f%%)%s  buf %lu/%lu (%.0f%%)%s\n",
           prefix,
           main_occ, cap_,
           cap_ ? 100.0 * main_occ / cap_ : 0.0,
           stats_.main_ever_full ? " [was full]" : "",
           buf_occ, buf_cap_,
           buf_cap_ ? 100.0 * buf_occ / buf_cap_ : 0.0,
           stats_.buf_ever_full  ? " [was full]" : "");
    const uint64_t classify_total = stats_.classify_main + stats_.classify_buf
                                  + stats_.classify_warm_miss + stats_.classify_cold_miss;
    if (classify_total > 0) {
      auto pct_c = [&](uint64_t n){ return classify_total ? 100.0 * n / classify_total : 0.0; };
      printf("%s repl_hist classify  : main=%lu (%.1f%%)  buf=%lu (%.1f%%)  "
             "warm_miss=%lu (%.1f%%)  cold_miss=%lu (%.1f%%)\n",
             prefix,
             stats_.classify_main,      pct_c(stats_.classify_main),
             stats_.classify_buf,       pct_c(stats_.classify_buf),
             stats_.classify_warm_miss, pct_c(stats_.classify_warm_miss),
             stats_.classify_cold_miss, pct_c(stats_.classify_cold_miss));
    }
    if (shadow_cap_ > 0) {
      const double hit_rate = stats_.buf_evictions
          ? 100.0 * stats_.shadow_hits / stats_.buf_evictions : 0.0;
      const double avg_doa  = stats_.shadow_hits
          ? static_cast<double>(stats_.shadow_hit_doa_sum) / stats_.shadow_hits : 0.0;
      uint64_t misclass = 0;
      if (mid_thd > 0)
        misclass = std::count_if(shadow_.begin(), shadow_.end(),
            [&](const ShadowEntry& s){ return s.valid && s.dead_count >= mid_thd; });
      printf("%s repl_hist shadow    : evictions=%lu  shadow_hits=%lu (%.1f%%)  "
             "avg_doa@evict=%.2f  nonzero=%lu",
             prefix,
             stats_.buf_evictions, stats_.shadow_hits, hit_rate,
             avg_doa, stats_.shadow_hit_nonzero);
      if (mid_thd > 0)
        printf("  misclass(doa>=%lu)=%lu", mid_thd, misclass);
      printf("\n");
    }
    (void)low_thd;  // reserved for future mostly-dead misclassification tracking
  }

  void update(uint64_t key, liveness_class lv) {
    if (shadow_cap_ > 0) seen_pcs_.insert(key);
    if (!unbounded_ && checkpoint_interval_ > 0) {
      if (++update_count_ % checkpoint_interval_ == 0) {
        const uint64_t main_occ = static_cast<uint64_t>(
            std::count_if(entries_.begin(), entries_.end(),
                          [](const Entry& e){ return e.valid; }));
        const uint64_t buf_occ = static_cast<uint64_t>(
            std::count_if(buffer_.begin(), buffer_.end(),
                          [](const BufEntry& b){ return b.valid; }));
        fprintf(stderr,
            "[repl_hist %s] update=%-10lu  main=%lu/%lu (%.0f%%)  buf=%lu/%lu (%.0f%%)  shadow_evictions=%lu  shadow_hits=%lu\n",
            checkpoint_name_.c_str(), update_count_,
            main_occ, cap_, cap_ ? 100.0 * main_occ / cap_ : 0.0,
            buf_occ,  buf_cap_, buf_cap_ ? 100.0 * buf_occ / buf_cap_ : 0.0,
            stats_.buf_evictions, stats_.shadow_hits);
      }
    }
    if (unbounded_) {
      auto& [doa, dead] = unmap_[key];
      switch (lv) {
        case liveness_class::doa:          doa++;              break;
        case liveness_class::mostly_dead:  dead++; doa = 0;   break;
        case liveness_class::mostly_alive: doa = 0; dead = 0; break;
      }
      return;
    }
    const bool accessed = (lv != liveness_class::doa);
    // 1. Main table hit.
    for (auto& e : entries_) {
      if (e.valid && e.key == key) {
        switch (lv) {
          case liveness_class::doa:
            e.doa = std::min(e.doa + 1, MAX_COUNTER);
            break;
          case liveness_class::mostly_dead:
            e.mostly_dead = std::min(e.mostly_dead + 1, MAX_COUNTER);
            e.doa = 0;
            break;
          case liveness_class::mostly_alive:
            e.doa = 0;
            e.mostly_dead = 0;
            break;
        }
        on_hit(e, accessed);
        return;
      }
    }
    // 2. Promotion buffer: tracks DoA confirmations only.
    if (buf_cap_ > 0) {
      for (auto& b : buffer_) {
        if (b.valid && b.key == key) {
          if (lv == liveness_class::doa) {
            b.dead_count++;
            try_promote();
          } else {
            b.dead_count = 0;
          }
          return;
        }
      }
      // Not in main table or buffer: check shadow before staging.
      // A shadow hit means this PC was fully evicted but is still generating DoA events.
      if (shadow_cap_ > 0 && lv == liveness_class::doa) {
        for (auto& s : shadow_) {
          if (s.valid && s.key == key) {
            ++stats_.shadow_hits;
            stats_.shadow_hit_doa_sum += s.dead_count;
            if (s.dead_count > 0) ++stats_.shadow_hit_nonzero;
            s.valid = false;  // consume: count first re-appearance only
            break;
          }
        }
      }
      // Stage in buffer on DoA evictions only.
      if (lv == liveness_class::doa) {
        auto& bslot      = buf_victim();
        bslot.key        = key;
        bslot.dead_count = 1;
        bslot.ts         = ++buf_clock_;
        bslot.valid      = true;
        try_promote();
      }
      return;
    }
    // 3. No buffer: insert on dead evictions; skip on mostly-alive.
    if (lv != liveness_class::mostly_alive) {
      auto& slot       = victim_slot();
      slot.key         = key;
      slot.doa         = (lv == liveness_class::doa) ? 1 : 0;
      slot.mostly_dead = (lv == liveness_class::mostly_dead) ? 1 : 0;
      slot.valid       = true;
      on_insert(slot, accessed);
    }
  }

  void reset(uint64_t key) {
    for (auto& e : entries_)
      if (e.valid && e.key == key) { e.doa = 0; e.mostly_dead = 0; return; }
  }

private:
  static constexpr uint64_t MAX_COUNTER = 16;
  static constexpr uint32_t SRRIP_INS  = 2;
  static constexpr uint32_t SRRIP_MAX  = 3;

  struct Entry {
    uint64_t key         = 0;
    uint64_t doa         = 0;  // saturating count of consecutive DoA evictions
    uint64_t mostly_dead = 0;  // saturating count of consecutive mostly-dead evictions
    uint64_t freq        = 0;
    uint64_t ts          = 0;
    uint32_t rrpv        = 0;
    bool          valid    = false;
    mutable bool  promoted = false;  // set on buffer promotion; cleared on first hit
  };

  struct BufEntry {
    uint64_t key        = 0;
    uint64_t dead_count = 0;
    uint64_t ts         = 0;
    bool     valid      = false;
  };

  // Shadow (victim) buffer: holds entries evicted from the promotion buffer.
  // Pure instrumentation — does not affect policy decisions.
  struct ShadowEntry {
    uint64_t key        = 0;
    uint64_t dead_count = 0;  // dead_count from the promotion buffer at final eviction
    uint64_t ts         = 0;
    bool     valid      = false;
  };

  bool        unbounded_           = false;
  uint64_t    checkpoint_interval_ = 0;
  uint64_t    update_count_        = 0;
  std::string checkpoint_name_;
  mutable std::unordered_map<uint64_t, std::pair<uint64_t,uint64_t>> unmap_;
  uint64_t cap_          = 0;
  Policy   pol_          = Policy::LRU;
  std::vector<Entry>    entries_;
  uint64_t clock_        = 0;
  uint64_t buf_cap_      = 0;
  uint64_t buf_clock_    = 0;
  std::vector<BufEntry> buffer_;
  uint64_t shadow_cap_   = 0;
  uint64_t shadow_clock_ = 0;
  std::vector<ShadowEntry> shadow_;
  // Instrumentation: tracks every key ever passed to update(), so classify() can
  // distinguish warm misses (PC was known, entry was evicted) from cold misses
  // (PC has never generated an eviction before). Only populated when shadow_cap_ > 0.
  std::unordered_set<uint64_t> seen_pcs_;
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
    slot.key         = best->key;
    slot.doa         = best->dead_count;
    slot.mostly_dead = 0;
    slot.valid       = true;
    on_promote(slot, best->dead_count);
    best->key        = has_victim ? victim_key : 0;
    best->dead_count = 0;
    best->ts         = has_victim ? ++buf_clock_ : 0;
    best->valid      = has_victim;
  }

  Entry& victim_slot() {
    for (auto& e : entries_) if (!e.valid) return e;
    stats_.main_ever_full = true;
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

  ShadowEntry& shadow_victim() {
    for (auto& s : shadow_) if (!s.valid) return s;
    // LRU eviction within the shadow buffer.
    return *std::min_element(shadow_.begin(), shadow_.end(),
      [](const ShadowEntry& a, const ShadowEntry& b){ return a.ts < b.ts; });
  }

  // DoA-LFU eviction: evict the buffer entry with the fewest dead confirmations.
  // ts (insertion time) breaks ties — evict the older entry among equals.
  // Records the evicted entry in the shadow buffer (instrumentation only).
  BufEntry& buf_victim() {
    for (auto& b : buffer_) if (!b.valid) return b;
    stats_.buf_ever_full = true;
    auto& victim = *std::min_element(buffer_.begin(), buffer_.end(),
      [](const BufEntry& a, const BufEntry& b){
        return a.dead_count < b.dead_count ||
               (a.dead_count == b.dead_count && a.ts < b.ts); });
    // Record the final eviction in the shadow buffer.
    if (shadow_cap_ > 0 && victim.valid) {
      ++stats_.buf_evictions;
      auto& se    = shadow_victim();
      se.key        = victim.key;
      se.dead_count = victim.dead_count;
      se.ts         = ++shadow_clock_;
      se.valid      = true;
    }
    return victim;
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

  uint64_t get_dead(uint64_t pc, uint64_t addr) const {
    for (const auto& e : entries_) {
      if (!e.valid || e.pc != pc) continue;
      for (const auto& a : e.addrs)
        if (a.valid && a.addr == addr) return a.mostly_dead;
      return 0;
    }
    return 0;
  }

  void update(uint64_t pc, uint64_t addr, liveness_class lv) {
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
    if (lv == liveness_class::doa) pe->freq++;  // DoA-LFU at PC level

    // --- Addr level: check main slots ---
    for (auto& a : pe->addrs) {
      if (a.valid && a.addr == addr) {
        switch (lv) {
          case liveness_class::doa:
            a.count = std::min(a.count + 1, MAX_COUNTER);
            a.freq++;
            break;
          case liveness_class::mostly_dead:
            a.mostly_dead = std::min(a.mostly_dead + 1, MAX_COUNTER);
            a.count = 0;
            break;
          case liveness_class::mostly_alive:
            a.count = 0;
            a.mostly_dead = 0;
            break;
        }
        return;
      }
    }

    // --- Addr level: check promotion buffer (DoA confirmations only) ---
    if (addr_buf_cap_ > 0) {
      for (auto& b : pe->buf) {
        if (b.valid && b.addr == addr) {
          if (lv == liveness_class::doa) {
            b.dead_count++;
            if (b.dead_count > addr_lfu_victim_freq(*pe)) {
              auto& slot       = evict_addr(*pe);
              slot.addr        = b.addr;
              slot.count       = b.dead_count;
              slot.mostly_dead = 0;
              slot.freq        = b.dead_count;
              slot.valid       = true;
              b = BufEntry{};
            }
          } else {
            b.dead_count = 0;
          }
          return;
        }
      }
      // New addr: stage in buffer on DoA evictions only.
      if (lv == liveness_class::doa) {
        auto& bslot      = buf_victim(*pe);
        bslot.addr       = addr;
        bslot.dead_count = 1;
        bslot.ts         = ++buf_clock_;
        bslot.valid      = true;
      }
      return;
    }

    // --- No buffer: insert on dead evictions only ---
    if (lv != liveness_class::mostly_alive) {
      auto& slot       = evict_addr(*pe);
      slot.addr        = addr;
      slot.count       = (lv == liveness_class::doa) ? 1 : 0;
      slot.mostly_dead = (lv == liveness_class::mostly_dead) ? 1 : 0;
      slot.freq        = (lv == liveness_class::doa) ? 1 : 0;
      slot.valid       = true;
    }
  }

private:
  static constexpr uint64_t MAX_COUNTER = 16;

  struct AddrEntry {
    uint64_t addr        = 0;
    uint64_t count       = 0;  // DoA counter (renamed from count for clarity)
    uint64_t mostly_dead = 0;  // mostly-dead counter
    uint64_t freq        = 0;  // DoA-LFU: dead confirmation count
    bool     valid       = false;
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

    uint64_t install_cycle   = 0; // cycle when block was installed (for halflife classification)
    uint64_t last_hit_cycle  = 0; // cycle of most recent hit (0 = never hit)
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
  uint64_t mid_thd = 1;   // repl_hist_pc: doa_count  >= mid_thd → DoA
  uint64_t low_thd = 0;   // repl_hist_pc: dead_count >= low_thd → mostly-dead (0 = disabled)
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

  // Per-PC replacement guidance history.
  // Tracks two counters per PC: doa (consecutive DoA evictions) and mostly_dead
  // (consecutive mostly-dead evictions). Updated at every LLC/STLB eviction.
  // Default: unbounded (unordered_map fallback, backward compatible).
  // Bounded: configured via REPL_HIST_{LLC,STLB}_CAP + REPL_HIST_{BUF_CAP,REPL} env vars
  // in load_predictor_settings(). Uses the same HistTable replacement policies
  // (lru/lfu/lfu_doa/srrip) and optional promotion buffer as phist/bhist.
  HistTable repl_hist_pc;

  // Classify block liveness based on repl_hist_pc counters for the fill PC.
  // Used by srrip_live and ipv_live replacement policies to guide insertion/promotion.
  liveness_class classify_block_liveness(uint64_t block_address, uint64_t pc) const;

  // Unbounded characterization: track all (PC, address) pairs to measure actual demand.
  // Enables data-driven sizing decisions: how many PCs and addresses per PC do we actually see?
  bool characterization_enable = false;
  std::map<uint64_t, std::set<uint64_t>> pc_to_addrs;  // PC → set of unique addresses
  void record_characterization(uint64_t dp_pc, uint64_t block_address);
  void print_characterization_stats() const;

  // Per-PC liveness characterization: enabled by LIVENESS_CHAR=1.
  // Classifies each eviction as DoA / mostly-dead / mostly-alive using the halflife criterion
  // and accumulates counts per PC, then prints them at end_phase.
  struct PCLivenessEntry { uint64_t total = 0, doa = 0, mostly_dead = 0, mostly_alive = 0; };
  bool liveness_char_enable = false;
  std::unordered_map<uint64_t, PCLivenessEntry> pc_liveness_char;
  void record_liveness_char(uint64_t pc, uint64_t install_cycle,
                            uint64_t last_hit_cycle, uint64_t evict_cycle,
                            bool accessed);
  void print_liveness_char() const;

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
  void update_eviction_counters(const BLOCK& victim, liveness_class lv);  // update history tables at eviction

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
