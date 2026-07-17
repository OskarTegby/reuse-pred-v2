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
#include <numeric>
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
  enum class Policy { LRU, LFU, LFU_DOA, SRRIP };

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
  HistTable(uint64_t cap, Policy pol, uint64_t buf_cap = 0, uint64_t /*shadow_cap*/ = 0)
    : unbounded_(false), cap_(cap), pol_(pol), entries_(cap), buf_cap_(buf_cap), buffer_(buf_cap) {
    if (pol_ == Policy::LFU_DOA) {
      if (const char* ev = std::getenv("HIST_MA_PENALTY"))
        ma_penalty_ = std::atoi(ev);
    }
  }

  void set_hash(unsigned bits) { hash_bits_ = bits; }

  void set_checkpoint(uint64_t interval, std::string name) {
    checkpoint_interval_ = interval;
    checkpoint_name_     = std::move(name);
  }

  void set_reset_period(uint64_t period) { reset_period_ = period; }
  void set_bypass_pc_reset(uint64_t period) { bypass_pc_reset_period_ = period; }

  void set_doa_default_pct(int pct) { doa_default_pct_ = pct; }

  void set_doa_force_pct(int pct) { doa_force_pct_ = pct; }
  void maybe_force_doa(uint64_t key, int64_t value) {
    if (doa_force_pct_ <= 0 || !unbounded_) return;
    const uint64_t k = hk_(key);
    if ((mix64_(k ^ 0x9E3779B97F4A7C15ULL) % 100) < static_cast<uint64_t>(doa_force_pct_))
      unmap_[k] = value;
  }

  void record_bypass(uint64_t key) {
    if (bypass_pc_reset_period_ == 0) return;
    auto& cnt = bypass_since_update_[key];
    if (++cnt >= bypass_pc_reset_period_) {
      if (unbounded_) {
        auto it = unmap_.find(key);
        if (it != unmap_.end()) it->second = 0;
      } else {
        for (auto& e : entries_)
          if (e.valid && e.key == key) { e.score = 0; break; }
      }
      cnt = 0;
    }
  }

  void reset_scores() {
    if (unbounded_) { for (auto& [k, v] : unmap_) v = 0; }
    else            { for (auto& e : entries_) e.score = 0; }
  }

  void erase_key(uint64_t key) {
    if (unbounded_) { unmap_.erase(key); }
    else { for (auto& e : entries_) if (e.valid && e.key == key) { e.valid = false; break; } }
    bypass_since_update_.erase(key);
  }

  enum class RecheckMode { Off, Fixed, Backoff };
  void set_recheck(RecheckMode mode, uint64_t base, uint64_t cap) {
    recheck_mode_ = mode; recheck_base_ = base ? base : 1;
    recheck_cap_  = cap   ? cap  : recheck_base_;
  }

  bool should_probe(uint64_t key) {
    if (recheck_mode_ == RecheckMode::Off) return false;
    uint64_t& cnt = recheck_count_[key];
    uint64_t  iv  = recheck_interval_[key];
    if (iv == 0) iv = recheck_base_;
    if (++cnt >= iv) {
      cnt = 0;
      recheck_probing_[key] = true;
      ++recheck_probes_;
      return true;
    }
    return false;
  }

  uint64_t recheck_probes() const { return recheck_probes_; }

  int64_t get_score(uint64_t key) const {
    key = hk_(key);
    if (unbounded_) {
      auto it = unmap_.find(key);
      return it != unmap_.end() ? it->second : 0;
    }
    stats_.queries++;
    for (const auto& e : entries_) {
      if (e.valid && e.key == key) {
        if (e.score > 0) {
          stats_.table_hits++;
          if (e.promoted) { stats_.promoted_hits++; e.promoted = false; }
        }
        return e.score;
      }
    }
    return 0;
  }

  liveness_class classify(uint64_t key, uint64_t thd_doa) const {
    key = hk_(key);
    if (unbounded_) {
      auto it = unmap_.find(key);
      if (it != unmap_.end() && it->second >= (int64_t)thd_doa) return liveness_class::doa;
      if (it == unmap_.end() && doa_default_(key)) return liveness_class::doa;
      return liveness_class::alive;
    }
    for (const auto& e : entries_) {
      if (e.valid && e.key == key) {
        ++stats_.classify_main;
        return e.score >= (int64_t)thd_doa ? liveness_class::doa : liveness_class::alive;
      }
    }
    for (const auto& b : buffer_) {
      if (b.valid && b.key == key) {
        if (b.dead_count >= thd_doa) {
          ++stats_.classify_buf_guided;
          return liveness_class::doa;
        }
        ++stats_.classify_buf_weak;
        return liveness_class::alive;
      }
    }
    if (!seen_pcs_.empty() && seen_pcs_.count(key)) {
      ++stats_.classify_warm_miss;
      if (!buf_evicted_pcs_.empty() && buf_evicted_pcs_.count(key))
        ++stats_.classify_warm_buf_evicted;
      auto it = oracle_buf_.find(key);
      if (it != oracle_buf_.end() && it->second >= thd_doa)
        ++stats_.classify_warm_oracle_hit;
      if (pol_ == Policy::LFU_DOA) {
        auto ait = aging_evicted_pcs_.find(key);
        if (ait != aging_evicted_pcs_.end()) {
          ++stats_.classify_warm_aged_out;
          stats_.classify_warm_aged_hitsum += ait->second.second;
        }
      }
    } else {
      ++stats_.classify_cold_miss;
      if (doa_default_(key)) return liveness_class::doa;
    }
    return liveness_class::alive;
  }

  const Stats& get_stats() const { return stats_; }
  void reset_stats() {
    stats_ = Stats{};
    for (auto& e : entries_) e.promoted = false;
  }

  void print_stats(const char* prefix, uint64_t thd_doa = 0) const {
    if (const char* d = std::getenv("REPL_HIST_DUMP_PCS"); d && d[0] == '1') {
      std::vector<std::pair<uint64_t, int64_t>> dump;
      if (unbounded_) {
        for (const auto& [k, v] : unmap_) dump.emplace_back(k, v);
      } else {
        for (const auto& e : entries_)
          if (e.valid) dump.emplace_back(e.key, e.score);
      }
      std::sort(dump.begin(), dump.end());
      printf("%s repl_hist PCS: count=%zu\n", prefix, dump.size());
      for (const auto& [k, sc] : dump)
        printf("%s repl_hist PC: key=0x%lx doa=%ld\n", prefix, k, sc);
    }
    if (unbounded_) {
      printf("%s repl_hist: unbounded (%zu entries)\n", prefix, unmap_.size());
      if (thd_doa > 0)
        printf("%s repl_hist transitions: alive->doa=%lu  doa->alive=%lu\n",
               prefix, stats_.trans_alive_doa, stats_.trans_doa_alive);
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
    const uint64_t classify_total = stats_.classify_main + stats_.classify_buf_guided
                                  + stats_.classify_buf_weak + stats_.classify_warm_miss
                                  + stats_.classify_cold_miss;
    if (classify_total > 0) {
      auto pct_c = [&](uint64_t n){ return classify_total ? 100.0 * n / classify_total : 0.0; };
      printf("%s repl_hist classify  : main=%lu (%.1f%%)  "
             "buf_guided=%lu (%.1f%%)  buf_weak=%lu (%.1f%%)  "
             "warm_miss=%lu (%.1f%%)  cold_miss=%lu (%.1f%%)\n",
             prefix,
             stats_.classify_main,       pct_c(stats_.classify_main),
             stats_.classify_buf_guided, pct_c(stats_.classify_buf_guided),
             stats_.classify_buf_weak,   pct_c(stats_.classify_buf_weak),
             stats_.classify_warm_miss,  pct_c(stats_.classify_warm_miss),
             stats_.classify_cold_miss,  pct_c(stats_.classify_cold_miss));
      if (stats_.classify_warm_miss > 0) {
        printf("%s repl_hist warm_miss : total=%lu  buf_evicted=%lu (%.1f%%)  "
               "main_evicted=%lu (%.1f%%)\n",
               prefix,
               stats_.classify_warm_miss,
               stats_.classify_warm_buf_evicted,
               pct_c(stats_.classify_warm_buf_evicted),
               stats_.classify_warm_miss - stats_.classify_warm_buf_evicted,
               pct_c(stats_.classify_warm_miss - stats_.classify_warm_buf_evicted));
        printf("%s repl_hist oracle    : warm_miss=%lu  oracle_would_hit=%lu (%.1f%% of warm)  "
               "oracle_buf_size=%zu\n",
               prefix,
               stats_.classify_warm_miss,
               stats_.classify_warm_oracle_hit,
               stats_.classify_warm_miss ? 100.0 * stats_.classify_warm_oracle_hit / stats_.classify_warm_miss : 0.0,
               oracle_buf_.size());
        if (pol_ == Policy::LFU_DOA && stats_.classify_warm_aged_out > 0) {
          auto avg_h = [](uint64_t sum, uint64_t n) { return n ? (double)sum / n : 0.0; };
          printf("%s repl_hist warm_aged : aged_out=%lu (%.1f%% of warm)  avg_hits=%.1f\n",
                 prefix,
                 stats_.classify_warm_aged_out,
                 pct_c(stats_.classify_warm_aged_out),
                 avg_h(stats_.classify_warm_aged_hitsum, stats_.classify_warm_aged_out));
        }
      }
    }
    if (pol_ == Policy::LFU_DOA && evict_count_ > 0) {
      auto pct = [](uint64_t n, uint64_t d) { return d ? 100.0 * n / d : 0.0; };
      printf("%s repl_hist evict_attr: total=%lu  ma_penalty=%d  "
             "ma_loss: %.1f%% of evictions  avg_loss=%.2f  decisive=%.1f%%  |  "
             "aging: %.1f%% of evictions  avg_penalty=%.2f  decisive=%.1f%% (avg_hits=%.1f)\n",
             prefix, evict_count_, ma_penalty_,
             pct(evict_ma_nonzero_,    evict_count_),
             (double)evict_ma_loss_sum_    / evict_count_,
             pct(evict_ma_decisive_,   evict_count_),
             pct(evict_aging_nonzero_, evict_count_),
             (double)evict_aging_loss_sum_ / evict_count_,
             pct(evict_aging_decisive_, evict_count_),
             evict_aging_decisive_ ? (double)evict_aging_hitsum_ / evict_aging_decisive_ : 0.0);
    }
    if (buf_cap_ > 0) {
      auto pct = [](uint64_t n, uint64_t d){ return d ? 100.0 * n / d : 0.0; };
      printf("%s repl_hist buf_flow  : promotions=%lu  demotions=%lu  "
             "2nd_chance_promo=%lu (%.1f%% of demoted)  2nd_chance_evict=%lu (%.1f%%)  "
             "doa_buf_miss=%lu  attempts=%lu  blocked=%lu (%.1f%%)\n",
             prefix,
             stats_.promotions, stats_.demotions,
             stats_.second_chance_promotions, pct(stats_.second_chance_promotions, stats_.demotions),
             stats_.second_chance_evictions,  pct(stats_.second_chance_evictions,  stats_.demotions),
             stats_.doa_buf_miss,
             stats_.promote_attempts, stats_.promote_blocked,
             pct(stats_.promote_blocked, stats_.promote_attempts));
      const uint64_t evict_total = std::accumulate(
          stats_.buf_evict_dc_hist, stats_.buf_evict_dc_hist + 6, uint64_t{0});
      const uint64_t promo_total = std::accumulate(
          stats_.buf_promo_dc_hist, stats_.buf_promo_dc_hist + 6, uint64_t{0});
      if (evict_total > 0) {
        printf("%s repl_hist buf_evict_dc: total=%lu  "
               "dc=0:%.1f%%  dc=1:%.1f%%  dc=2:%.1f%%  dc=3:%.1f%%  dc=4:%.1f%%  dc=5+:%.1f%%\n",
               prefix, evict_total,
               pct(stats_.buf_evict_dc_hist[0], evict_total),
               pct(stats_.buf_evict_dc_hist[1], evict_total),
               pct(stats_.buf_evict_dc_hist[2], evict_total),
               pct(stats_.buf_evict_dc_hist[3], evict_total),
               pct(stats_.buf_evict_dc_hist[4], evict_total),
               pct(stats_.buf_evict_dc_hist[5], evict_total));
      }
      if (promo_total > 0) {
        printf("%s repl_hist buf_promo_dc: total=%lu  "
               "dc=1:%.1f%%  dc=2:%.1f%%  dc=3:%.1f%%  dc=4:%.1f%%  dc=5+:%.1f%%\n",
               prefix, promo_total,
               pct(stats_.buf_promo_dc_hist[1], promo_total),
               pct(stats_.buf_promo_dc_hist[2], promo_total),
               pct(stats_.buf_promo_dc_hist[3], promo_total),
               pct(stats_.buf_promo_dc_hist[4], promo_total),
               pct(stats_.buf_promo_dc_hist[5], promo_total));
      }
    }
    if (buf_cap_ > 0 && stats_.buf_evictions > 0) {
      auto pct = [](uint64_t n, uint64_t d){ return d ? 100.0 * n / d : 0.0; };
      const double avg_doa = stats_.shadow_hits
          ? static_cast<double>(stats_.shadow_hit_doa_sum) / stats_.shadow_hits : 0.0;
      printf("%s repl_hist shadow    : evictions=%lu  shadow_hits=%lu (%.1f%% of doa_miss)  "
             "avg_doa@evict=%.2f  nonzero=%lu\n",
             prefix,
             stats_.buf_evictions, stats_.shadow_hits,
             pct(stats_.shadow_hits, stats_.doa_buf_miss),
             avg_doa, stats_.shadow_hit_nonzero);
    }
    if (thd_doa > 0)
      printf("%s repl_hist transitions: alive->doa=%lu  doa->alive=%lu\n",
             prefix, stats_.trans_alive_doa, stats_.trans_doa_alive);
  }

  void update(uint64_t key, liveness_class evict_class, int64_t thd_doa = 0) {
    if (!unbounded_ && cap_ == 0 && buf_cap_ == 0) return;
    key = hk_(key);
    seen_pcs_.insert(key);
    ++update_count_;
    if (thd_doa > 0) thd_doa_cache_ = thd_doa;
    if (recheck_mode_ == RecheckMode::Backoff) {
      auto pit = recheck_probing_.find(key);
      if (pit != recheck_probing_.end() && pit->second) {
        pit->second = false;
        uint64_t& iv  = recheck_interval_[key];
        const uint64_t cur = iv ? iv : recheck_base_;
        iv = (evict_class == liveness_class::doa)
                 ? std::min(cur * 2, recheck_cap_)
                 : recheck_base_;
      }
    }
    if (buf_cap_ > 0 && evict_class == liveness_class::doa) {
      auto it = oracle_buf_.find(key);
      if (it != oracle_buf_.end()) ++it->second;
    }
    if (!unbounded_ && checkpoint_interval_ > 0) {
      if (update_count_ % checkpoint_interval_ == 0) {
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
    auto record_transition = [&](int64_t old_s, int64_t new_s) {
      if (thd_doa == 0 || old_s == new_s) return;
      const bool was_doa = old_s >= (int64_t)thd_doa;
      const bool is_doa  = new_s >= (int64_t)thd_doa;
      if (!was_doa && is_doa) ++stats_.trans_alive_doa;
      else if (was_doa && !is_doa) ++stats_.trans_doa_alive;
    };
    if (unbounded_) {
      bypass_since_update_[key] = 0;
      auto it = unmap_.find(key);
      if (it == unmap_.end()) {
        if (evict_class != liveness_class::doa) return;
        it = unmap_.emplace(key, 0).first;
      }
      const int64_t old_s = it->second;
      it->second = (evict_class == liveness_class::doa) ? old_s + 1 : 0;
      record_transition(old_s, it->second);
      if (reset_period_ > 0 && update_count_ % reset_period_ == 0) {
        for (auto& [k, v] : unmap_) v = 0;
      }
      return;
    }
    bypass_since_update_[key] = 0;
    for (auto& e : entries_) {
      if (e.valid && e.key == key) {
        const int64_t old_s = e.score;
        e.score = (evict_class == liveness_class::doa) ? old_s + 1 : 0;
        record_transition(old_s, e.score);
        on_hit(e, evict_class);
        return;
      }
    }
    if (buf_cap_ > 0) {
      for (auto& b : buffer_) {
        if (b.valid && b.key == key) {
          if (evict_class == liveness_class::doa) {
            b.dead_count++;
            try_promote();
          } else {
            b.dead_count = 0;
          }
          return;
        }
      }
      if (evict_class == liveness_class::doa) {
        auto sit = shadow_map_.find(key);
        if (sit != shadow_map_.end()) {
          ++stats_.shadow_hits;
          stats_.shadow_hit_doa_sum += sit->second;
          if (sit->second > 0) ++stats_.shadow_hit_nonzero;
          shadow_map_.erase(sit);
        }
      }
      if (evict_class == liveness_class::doa) {
        ++stats_.doa_buf_miss;
        buf_evicted_pcs_.erase(key);
        shadow_map_.erase(key);
        auto& bslot         = buf_victim();
        bslot.key           = key;
        bslot.dead_count    = 1;
        bslot.ts            = ++buf_clock_;
        bslot.valid         = true;
        bslot.second_chance = false;
        try_promote();
      }
      return;
    }
    if (evict_class == liveness_class::doa) {
      auto& slot   = victim_slot();
      slot.key     = key;
      slot.score   = 1;
      record_transition(0, slot.score);
      slot.valid   = true;
      on_insert(slot, evict_class);
    }
  }

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
  uint64_t    checkpoint_interval_ = 0;
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
  std::string checkpoint_name_;
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
  Policy   pol_          = Policy::LRU;
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

  void on_hit(Entry& e, liveness_class evict_class) {
    const bool is_doa = evict_class == liveness_class::doa;
    e.last_seen_update = update_count_;
    switch (pol_) {
    case Policy::LRU:     e.ts = ++clock_;                                break;
    case Policy::LFU:     ++e.freq; e.ts = ++clock_;                      break;
    case Policy::LFU_DOA:
      if (is_doa) e.freq = std::min(FREQ_CAP, e.freq + 3);
      else if (ma_penalty_ < 0) {
        const uint64_t loss   = static_cast<uint64_t>(-ma_penalty_);
        const uint64_t actual = std::min(e.freq, loss);
        e.ma_loss += actual;
        e.freq    -= actual;
      }
      ++e.hit_count;
      e.ts = ++clock_;
      break;
    case Policy::SRRIP:   e.rrpv = is_doa ? 0 : SRRIP_MAX;               break;
    }
  }

  void on_insert(Entry& e, liveness_class evict_class) {
    e.promoted = false;
    e.last_seen_update = update_count_;
    const bool is_doa = evict_class == liveness_class::doa;
    switch (pol_) {
    case Policy::LRU:     e.ts = ++clock_; e.freq = 0; e.rrpv = 0;                break;
    case Policy::LFU:     e.freq = 1; e.ts = ++clock_; e.rrpv = 0;                break;
    case Policy::LFU_DOA:
      e.freq      = is_doa ? 3 : 0;
      e.ma_loss   = 0;
      e.hit_count = 0;
      e.ts = ++clock_; e.rrpv = 0;
      aging_evicted_pcs_.erase(e.key);
      break;
    case Policy::SRRIP:   e.rrpv = SRRIP_INS; e.freq = 0; e.ts = 0;              break;
    }
  }

  void on_promote(Entry& e, uint64_t dead_count) {
    e.promoted = true;
    e.last_seen_update = update_count_;
    switch (pol_) {
    case Policy::LRU:     e.ts = ++clock_; e.freq = 0; e.rrpv = 0;           break;
    case Policy::LFU:     e.freq = dead_count; e.ts = ++clock_; e.rrpv = 0;  break;
    case Policy::LFU_DOA: e.freq      = std::min(FREQ_CAP, dead_count * 3);
                          e.ma_loss   = 0;
                          e.hit_count = 0;
                          e.ts = ++clock_; e.rrpv = 0;
                          aging_evicted_pcs_.erase(e.key);                    break;
    case Policy::SRRIP:   e.rrpv = 0; e.freq = 0; e.ts = 0;                  break;
    }
  }

  void try_promote() {
    BufEntry* best = nullptr;
    for (auto& b : buffer_) {
      if (!b.valid || b.dead_count == 0) continue;
      if (!best || b.dead_count > best->dead_count ||
          (b.dead_count == best->dead_count && b.ts > best->ts))
        best = &b;
    }
    if (!best) return;
    ++stats_.promote_attempts;

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
    if (!promote) { ++stats_.promote_blocked; return; }

    ++stats_.promotions;
    stats_.buf_promo_dc_hist[std::min(best->dead_count, uint64_t{5})]++;
    if (best->second_chance) ++stats_.second_chance_promotions;
    auto& slot = victim_slot();
    const bool has_victim = slot.valid;
    const uint64_t victim_key = has_victim ? slot.key : 0;
    slot.key   = best->key;
    slot.score = static_cast<int64_t>(best->dead_count);
    slot.valid = true;
    on_promote(slot, best->dead_count);
    best->key          = has_victim ? victim_key : 0;
    best->dead_count   = 0;
    best->ts           = has_victim ? ++buf_clock_ : 0;
    best->valid        = has_victim;
    best->second_chance = has_victim;
    if (has_victim) {
      ++stats_.demotions;
      buf_evicted_pcs_.erase(victim_key);
    }
  }

  Entry& victim_slot() {
    for (auto& e : entries_) if (!e.valid) return e;
    stats_.main_ever_full = true;
    switch (pol_) {
    case Policy::LRU:
      return *std::min_element(entries_.begin(), entries_.end(),
        [](const Entry& a, const Entry& b){ return a.ts < b.ts; });
    case Policy::LFU:
      return *std::min_element(entries_.begin(), entries_.end(),
        [](const Entry& a, const Entry& b){
          return a.freq < b.freq || (a.freq == b.freq && a.ts < b.ts); });
    case Policy::LFU_DOA: {
      const uint64_t aging_rate = cap_ > 0 ? cap_ : 1;
      auto eff = [&](const Entry& e) -> uint64_t {
        const uint64_t idle    = update_count_ - e.last_seen_update;
        const uint64_t penalty = idle / aging_rate;
        return e.freq > penalty ? e.freq - penalty : 0;
      };
      Entry& victim = *std::min_element(entries_.begin(), entries_.end(),
        [&](const Entry& a, const Entry& b){
          const uint64_t fa = eff(a), fb = eff(b);
          return fa < fb || (fa == fb && a.ts < b.ts); });
      ++evict_count_;
      const uint64_t idle          = update_count_ - victim.last_seen_update;
      const uint64_t aging_penalty = std::min(victim.freq, idle / aging_rate);
      const uint64_t eff_freq      = eff(victim);
      if (victim.ma_loss > 0)   { ++evict_ma_nonzero_;    evict_ma_loss_sum_    += victim.ma_loss;    }
      if (aging_penalty  > 0)   { ++evict_aging_nonzero_; evict_aging_loss_sum_ += aging_penalty;     }
      if (eff_freq == 0) {
        if (victim.ma_loss   > 0) ++evict_ma_decisive_;
        if (aging_penalty    > 0) {
          ++evict_aging_decisive_;
          aging_evicted_pcs_[victim.key] = {victim.score, victim.hit_count};
          evict_aging_hitsum_ += victim.hit_count;
        }
      }
      return victim;
    }
    case Policy::SRRIP:
      for (;;) {
        for (auto& e : entries_) if (e.rrpv == SRRIP_MAX) return e;
        for (auto& e : entries_) e.rrpv = std::min(e.rrpv + 1, SRRIP_MAX);
      }
    }
    return entries_[0];
  }

  BufEntry& buf_victim() {
    for (auto& b : buffer_) if (!b.valid) return b;
    stats_.buf_ever_full = true;
    auto& victim = *std::min_element(buffer_.begin(), buffer_.end(),
      [](const BufEntry& a, const BufEntry& b){
        return a.dead_count < b.dead_count ||
               (a.dead_count == b.dead_count && a.ts < b.ts); });
    if (victim.valid) {
      if (victim.second_chance) ++stats_.second_chance_evictions;
      stats_.buf_evict_dc_hist[std::min(victim.dead_count, uint64_t{5})]++;
      buf_evicted_pcs_.insert(victim.key);
      ++stats_.buf_evictions;
      shadow_map_[victim.key] = victim.dead_count;
      oracle_buf_[victim.key] += victim.dead_count;
    }
    return victim;
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

  uint64_t liveness_bypasses = 0;
  uint64_t liveness_probes   = 0;
  uint64_t liveness_bypass_shadow_hits = 0;

  uint64_t evictions    = 0;
  uint64_t doa          = 0;
  uint64_t doa_stlb_found    = 0;
  uint64_t doa_stlb_also_doa = 0;
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
    uint64_t last_hit_cycle  = 0;
  };
  using set_type = std::vector<BLOCK>;

  std::pair<set_type::iterator, set_type::iterator> get_set_span(uint64_t address);
  std::pair<set_type::const_iterator, set_type::const_iterator> get_set_span(uint64_t address) const;
  std::size_t get_set_index(uint64_t address) const;

  inline static const set_type* stlb_block_ptr = nullptr;

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
  bool stlb_liveness_bypass{false};
  uint64_t stlb_bypass_thd{0};

  liveness_class classify_block_liveness(uint64_t block_address, uint64_t pc) const;

  struct AddrCounterEntry { int64_t score = 0; bool ever_reset = false; };
  bool doa_addr_summary_enable_ = false;
  std::unordered_map<uint64_t, std::unordered_map<uint64_t, AddrCounterEntry>> doa_addr_table_;
  std::unordered_map<uint64_t, uint64_t> doa_addr_pc_doa_total_;
  void record_doa_addr_summary(uint64_t pc, uint64_t addr, liveness_class evict_lv);
  void print_doa_addr_summary() const;

  void load_predictor_settings();
  void shadow_record_bypass(uint64_t block_addr, uint64_t pc, uint64_t data);
  bool liveness_bypass_shadow_hit(const PACKET& handle_pkt);
  void update_eviction_counters(const BLOCK& victim, liveness_class lv);

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
