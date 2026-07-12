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
#include <cmath>
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

// Bounded history table: per-key DoA-eviction counter with a pluggable
// replacement policy for its own (capacity-limited) storage. Used for both
// pHIST (PC-indexed) and bHIST (address-indexed), as well as the replacement
// policies' own repl_hist_pc/g_merged_repl_hist instances.
//
// Scoring is deliberately simple: a DoA eviction increments the key's score
// by 1; any other (accessed) eviction resets it to 0. An earlier, much more
// elaborate scheme (9 selectable "scoring modes", a third "mostly-dead"
// classification tier between DoA and alive, lifespan-EMA adaptive
// weighting, a TIERED bounded-table eviction policy keyed on that third
// tier) was tried and removed for the replacement policies — see
// docs/JOBS.md "Set-dueling MD isolation" for the evidence that the extra
// machinery wasn't earning its complexity. The prefetch predictor (phist/
// bhist_flat/bhist_pc) never consumed the 3-way classification either — it
// only ever reads the raw DoA-tagged score via get_score()/get(), never
// classify() — so this simplification doesn't change its behavior.
class HistTable {
public:
  // LFU_DOA: freq increments only on DoA evictions — a live eviction
  // doesn't confirm bypass utility and shouldn't raise eviction priority.
  // SRRIP: DoA eviction → rrpv=0 (protect); live eviction → rrpv=SRRIP_MAX
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
    // Promotion-buffer flow diagnostics.
    uint64_t doa_buf_miss            = 0;  // DoA evictions that missed both main table and buffer
    uint64_t demotions               = 0;  // main-table entries demoted back to the buffer
    uint64_t second_chance_promotions = 0; // demoted entries that were subsequently re-promoted
    uint64_t second_chance_evictions  = 0; // demoted entries lost from buffer before re-promotion
    uint64_t promote_attempts        = 0;  // try_promote() found a valid candidate (dead_count > 0)
    uint64_t promote_blocked         = 0;  // candidate found but failed dead_count > min_freq threshold
    uint64_t buf_evict_dc_hist[6]   = {};  // dead_count histogram at buffer eviction (index = min(dc,5))
    uint64_t buf_promo_dc_hist[6]   = {};  // dead_count histogram at buffer promotion (index = min(dc,5))
    // Classification source tracking (set by classify()).
    mutable uint64_t classify_main      = 0;  // found in main table (at or above threshold)
    mutable uint64_t classify_buf_guided= 0;  // found in promo buffer AND above threshold → DoA (recovered)
    mutable uint64_t classify_buf_weak  = 0;  // found in promo buffer but below threshold (demoted from main, doa lost)
    mutable uint64_t classify_warm_miss        = 0;  // not in table or buf, but PC was seen before (fully evicted)
    mutable uint64_t classify_warm_buf_evicted = 0;  // warm miss where entry was specifically evicted from the promotion buffer
    mutable uint64_t classify_warm_oracle_hit  = 0;  // warm miss where oracle would have classified correctly (oracle dead_count >= thd_doa)
    mutable uint64_t classify_warm_aged_out    = 0;  // warm miss where eviction was aging-decisive (eff_freq hit 0 due to aging)
    mutable uint64_t classify_warm_aged_hitsum = 0;  // sum of hit_count for all aged-out warm misses
    mutable uint64_t classify_cold_miss        = 0;  // PC never seen before (no history — expected)
    // Score tier transition counters (only meaningful when thd_doa is non-zero).
    uint64_t trans_alive_doa = 0;  // score crossed thd_doa upward (alive → DoA)
    uint64_t trans_doa_alive = 0;  // score dropped below thd_doa (DoA → alive, recovery)
  };

  // Default: unbounded mode — backed by an unordered_map, no eviction.
  // Semantically identical to the old repl_hist_pc unordered_map; used as the
  // backward-compatible fallback when no capacity limit is configured.
  HistTable() : unbounded_(true) {}
  HistTable(uint64_t cap, Policy pol, uint64_t buf_cap = 0, uint64_t /*shadow_cap*/ = 0)
    : unbounded_(false), cap_(cap), pol_(pol), entries_(cap), buf_cap_(buf_cap), buffer_(buf_cap) {
    if (pol_ == Policy::LFU_DOA) {
      if (const char* ev = std::getenv("HIST_MA_PENALTY"))
        ma_penalty_ = std::atoi(ev);
    }
  }

  // Hash the key into `bits` bits before indexing (models Mazumdar's finite,
  // hashed history table). bits==0 → raw key (default, our idealized table).
  void set_hash(unsigned bits) { hash_bits_ = bits; }

  void set_checkpoint(uint64_t interval, std::string name) {
    checkpoint_interval_ = interval;
    checkpoint_name_     = std::move(name);
  }

  void set_reset_period(uint64_t period) { reset_period_ = period; }
  void set_bypass_pc_reset(uint64_t period) { bypass_pc_reset_period_ = period; }

  // DOA_DEFAULT_PCT=<0-100>: a deterministic per-key coin flip that makes that
  // percentage of never-before-seen keys classify as DoA on their very first
  // fill instead of the default alive/full-insertion treatment (every key
  // normally gets one free "assume alive" pass before any score evidence
  // exists). Tests whether removing that free pass helps workloads where a
  // typical key is seen only once or twice in the whole run (e.g. QMM), where
  // waiting for score evidence rarely pays off anyway. 0 = off (default).
  void set_doa_default_pct(int pct) { doa_default_pct_ = pct; }

  // DOA_FORCE_PCT=<0-100>: a separate deterministic per-key coin flip (distinct
  // subset from doa_default_pct_) that, once per fill, force-writes a key's
  // *persistent* score up to `value` -- unlike set_doa_default_pct (a read-time
  // override for never-seen keys only), this mutates real state, so it applies
  // to already-tracked keys too and the effect persists until the normal
  // update() path resets or changes it. Called once per fill right before
  // classify_block_liveness(), independent of whether bypass is enabled -- it
  // affects insertion depth and later hit-time promotion on its own. If bypass
  // is also enabled, its classify() call reads the same persistent score, so a
  // forced key can incidentally become bypass-eligible too, but that's not
  // this mechanism's target. Unbounded table only (no-op when bounded). 0 = off.
  void set_doa_force_pct(int pct) { doa_force_pct_ = pct; }
  void maybe_force_doa(uint64_t key, int64_t value) {
    if (doa_force_pct_ <= 0 || !unbounded_) return;
    const uint64_t k = hk_(key);
    if ((mix64_(k ^ 0x9E3779B97F4A7C15ULL) % 100) < static_cast<uint64_t>(doa_force_pct_))
      unmap_[k] = value;
  }

  // Adaptive per-key threshold (unbounded path only): instead of one fixed
  // thd_doa for the whole table, each key gets its own effective threshold
  // derived from an EWMA of the run-lengths it has actually shown at past
  // breaks (alive evictions), scaled by a margin:
  //   theta_key = max(theta_min_, round(ewma_runlen * theta_margin_))
  // margin > 1 = demand more evidence than the key's typical streak length
  // (conservative); margin < 1 = commit sooner (aggressive); margin = 1 =
  // commit right at "as likely to run longer as not". EWMA bootstraps from
  // the suite's fixed thd_doa so behavior matches the non-adaptive system
  // exactly until a key's first break.
  void set_adaptive_theta(bool b) { adaptive_theta_ = b; }
  void set_theta_margin(double m) { theta_margin_ = m; }
  void set_theta_alpha(double a) { theta_alpha_ = a; }
  void set_theta_min(int64_t m) { theta_min_ = m; }

  int64_t effective_theta(uint64_t key, int64_t thd_doa_default) const {
    if (!adaptive_theta_) return thd_doa_default;
    const uint64_t k = hk_(key);
    auto it = theta_ewma_.find(k);
    const double ewma = (it != theta_ewma_.end()) ? it->second : static_cast<double>(thd_doa_default);
    return std::max(theta_min_, static_cast<int64_t>(std::llround(ewma * theta_margin_)));
  }

  // Call on each bypass fire for a key. If the key has bypassed bypass_pc_reset_period_
  // times without receiving an eviction update, its score is zeroed so it must
  // re-earn its DoA classification (breaks per-PC lock-in).
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

  // Remove a key's entry entirely (used by the bypass shadow on a confirmed
  // mistake: the PC must re-earn its DoA classification from scratch).
  void erase_key(uint64_t key) {
    if (unbounded_) { unmap_.erase(key); }
    else { for (auto& e : entries_) if (e.valid && e.key == key) { e.valid = false; break; } }
    bypass_since_update_.erase(key);
  }

  // Periodic bypass recheck (probe): instead of bypassing every DoA fill for a
  // locked-in PC forever, occasionally let one fill THROUGH so it generates a
  // fresh eviction observation. If the probe still evicts as DoA, the PC is
  // confirmed dead; if it shows life (MA/MD), its score decays and bypass stops.
  //   Off     : disabled — never force a probe (classic always-bypass).
  //   Fixed   : probe every recheck_base_ bypasses for a PC.
  //   Backoff : probe every recheck_interval_[key] bypasses; on a DoA probe the
  //             interval doubles (capped at recheck_cap_), on a non-DoA probe it
  //             resets to recheck_base_. Frequent early checks, rare late checks.
  enum class RecheckMode { Off, Fixed, Backoff };
  void set_recheck(RecheckMode mode, uint64_t base, uint64_t cap) {
    recheck_mode_ = mode; recheck_base_ = base ? base : 1;
    recheck_cap_  = cap   ? cap  : recheck_base_;
  }

  // Called at fill time when a key has classified as DoA and would be bypassed.
  // Returns true if this fill should instead be INSERTED as a probe (caller must
  // not bypass it); false to bypass as usual. Advances the per-key schedule.
  bool should_probe(uint64_t key) {
    if (recheck_mode_ == RecheckMode::Off) return false;
    uint64_t& cnt = recheck_count_[key];
    uint64_t  iv  = recheck_interval_[key];
    if (iv == 0) iv = recheck_base_;
    if (++cnt >= iv) {
      cnt = 0;
      recheck_probing_[key] = true;  // next eviction for this key is the probe result
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

  // Classify a key against thd_doa, consulting main table then promotion
  // buffer. Tracks which structure resolved the classification in stats.
  liveness_class classify(uint64_t key, uint64_t thd_doa) const {
    const uint64_t raw_key = key;
    key = hk_(key);
    if (unbounded_) {
      auto it = unmap_.find(key);
      const int64_t eff_thd = adaptive_theta_ ? effective_theta(raw_key, (int64_t)thd_doa) : (int64_t)thd_doa;
      if (it != unmap_.end() && it->second >= eff_thd) return liveness_class::doa;
      if (it == unmap_.end() && doa_default_(key)) return liveness_class::doa;
      return liveness_class::alive;
    }
    // 1. Main table.
    for (const auto& e : entries_) {
      if (e.valid && e.key == key) {
        ++stats_.classify_main;
        return e.score >= (int64_t)thd_doa ? liveness_class::doa : liveness_class::alive;
      }
    }
    // 2. Promotion buffer: interprets dead_count as a score proxy.
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
    // 3. Not found. Warm miss (entry evicted) or cold miss (never seen).
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

  // Print occupancy and shadow-buffer instrumentation to stdout.
  // thd_doa: used to flag shadow hits where dead_count >= thd_doa — recovered
  // classification that the bounded table missed.
  void print_stats(const char* prefix, uint64_t thd_doa = 0) const {
    // TEMPORARY (testing): dump the PCs currently resident in the history table,
    // sorted by key for determinism. Opt-in via REPL_HIST_DUMP_PCS=1 so normal
    // runs are unaffected. Lets black-box tests verify which PCs survive under a
    // realistic cap on many-PC traces (QMM/SPEC), where the eviction policy is
    // actually exercised.
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
                                  + stats_.classify_cold_miss;  // oracle_hit is a subset of warm_miss, not additive
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
      // dead_count histograms: where do evicted / promoted entries stand?
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

  // Update the history table with one eviction observation: a DoA eviction
  // increments the key's score by 1; any other (accessed) eviction resets it
  // to 0.
  void update(uint64_t key, liveness_class evict_class, int64_t thd_doa = 0) {
    if (!unbounded_ && cap_ == 0 && buf_cap_ == 0) return;
    key = hk_(key);
    seen_pcs_.insert(key);
    ++update_count_;
    if (thd_doa > 0) thd_doa_cache_ = thd_doa;
    // Recheck backoff: if this eviction is the outcome of a forced probe, adjust
    // the per-key probe interval. DoA → confirmed dead, probe less often (double,
    // capped). Non-DoA → showed life, reset to the base interval.
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
      bypass_since_update_[key] = 0;  // eviction feedback arrived: no longer locked in
      // Allocate only on a DoA eviction: an alive eviction of an untracked key
      // carries no information (its classification is already the default,
      // alive), so storing a zero entry for it would only waste space.
      auto it = unmap_.find(key);
      if (it == unmap_.end()) {
        if (evict_class != liveness_class::doa) return;
        it = unmap_.emplace(key, 0).first;
      }
      const int64_t old_s = it->second;
      if (adaptive_theta_ && evict_class != liveness_class::doa && old_s > 0) {
        // A real streak just broke (old_s > 0): fold its length into this
        // key's EWMA of typical run-length-at-break. Bootstrap from thd_doa
        // on the first break so behavior matches the non-adaptive system
        // until a key has actually shown one.
        double& ewma = theta_ewma_[key];
        if (ewma <= 0.0) ewma = static_cast<double>(thd_doa > 0 ? thd_doa : old_s);
        ewma = theta_alpha_ * static_cast<double>(old_s) + (1.0 - theta_alpha_) * ewma;
      }
      it->second = (evict_class == liveness_class::doa) ? old_s + 1 : 0;
      record_transition(old_s, it->second);
      // Periodic reset: break DoA lock-in by zeroing all scores every N updates.
      if (reset_period_ > 0 && update_count_ % reset_period_ == 0) {
        for (auto& [k, v] : unmap_) v = 0;
      }
      return;
    }
    bypass_since_update_[key] = 0;
    // 1. Main table hit: apply delta, floor at zero.
    for (auto& e : entries_) {
      if (e.valid && e.key == key) {
        const int64_t old_s = e.score;
        e.score = (evict_class == liveness_class::doa) ? old_s + 1 : 0;
        record_transition(old_s, e.score);
        on_hit(e, evict_class);
        return;
      }
    }
    // 2. Promotion buffer: tracks DoA confirmations until threshold is reached.
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
        buf_evicted_pcs_.erase(key);  // re-entering the buffer; no longer "evicted"
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
    // 3. No buffer: insert new entry on a DoA signal.
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
  // Configurable non-DoA eviction penalty for LFU_DOA (read from HIST_MA_PENALTY env var).
  // Default -2: each non-DoA eviction subtracts 2 from freq. Use -1 or 0 to reduce/remove penalty.
  int ma_penalty_ = -2;

  // Fold the low 32 bits of val into `bits` bits by XOR (Mazumdar-style hash).
  static uint64_t fold_(uint64_t val, unsigned bits) {
    uint64_t result = 0;
    const uint64_t mask = (1ULL << bits) - 1;
    for (unsigned i = 0; i < 32u / bits; ++i, val >>= bits)
      result ^= (val & mask);
    return result;
  }
  // Apply the optional hash to a key (identity when hash_bits_ == 0).
  uint64_t hk_(uint64_t key) const { return hash_bits_ ? fold_(key, hash_bits_) : key; }

  struct Entry {
    uint64_t key              = 0;
    int64_t  score            = 0;  // DoA counter
    uint64_t freq             = 0;
    uint64_t ts               = 0;
    uint64_t last_seen_update = 0;  // update_count_ at last on_hit/on_insert/on_promote
    uint64_t ma_loss          = 0;  // cumulative freq reduction from non-DoA eviction penalties
    uint64_t hit_count        = 0;  // number of on_hit() calls since last insertion/promotion
    uint32_t rrpv             = 0;
    bool          valid    = false;
    mutable bool  promoted = false;
  };

  struct BufEntry {
    uint64_t key          = 0;
    uint64_t dead_count   = 0;
    uint64_t ts           = 0;
    bool     valid        = false;
    bool     second_chance = false;  // true if this slot holds a main-table evictee
  };

  bool        unbounded_           = false;
  uint64_t    checkpoint_interval_ = 0;
  uint64_t    reset_period_        = 0;  // 0 = disabled; reset all scores every N updates
  uint64_t    update_count_        = 0;
  // Per-PC lock-in detection: counts bypass fires per key since the last eviction
  // update for that key. When the count reaches bypass_pc_reset_period_, the
  // entry's score is zeroed so the PC must re-earn its DoA classification.
  // Cleared to 0 by update() whenever eviction feedback arrives for a key.
  uint64_t bypass_pc_reset_period_{0};
  mutable std::unordered_map<uint64_t, uint64_t> bypass_since_update_;
  // Periodic bypass recheck (probe) state — see set_recheck()/should_probe().
  RecheckMode recheck_mode_     = RecheckMode::Off;
  uint64_t    recheck_base_     = 0;  // base probe interval (bypasses between probes)
  uint64_t    recheck_cap_      = 0;  // max interval for Backoff mode
  uint64_t    recheck_probes_   = 0;  // total probes forced (instrumentation)
  std::unordered_map<uint64_t, uint64_t> recheck_count_;     // bypasses since last probe
  std::unordered_map<uint64_t, uint64_t> recheck_interval_;  // current interval (0 = base)
  std::unordered_map<uint64_t, bool>     recheck_probing_;   // awaiting probe eviction outcome
  std::string checkpoint_name_;
  unsigned hash_bits_ = 0;  // >0 → hash keys into this many bits (faithful Mazumdar)
  int doa_default_pct_ = 0;  // DOA_DEFAULT_PCT: % of never-seen keys defaulted to DoA
  int doa_force_pct_   = 0;  // DOA_FORCE_PCT: % of fills whose persistent score is forced up
  bool adaptive_theta_ = false;                          // ADAPTIVE_THETA: per-key learned threshold
  double theta_margin_ = 1.0;                             // ADAPTIVE_THETA_MARGIN
  double theta_alpha_  = 0.25;                            // ADAPTIVE_THETA_ALPHA (EWMA decay rate)
  int64_t theta_min_   = 1;                               // ADAPTIVE_THETA_MIN (floor)
  std::unordered_map<uint64_t, double> theta_ewma_;  // per-key EWMA of run-length at break

  static uint64_t mix64_(uint64_t x) {
    x ^= x >> 33; x *= 0xff51afd7ed558ccdULL; x ^= x >> 33;
    x *= 0xc4ceb9fe1a85ec53ULL; x ^= x >> 33;
    return x;
  }
  // Deterministic per-key coin flip: true for doa_default_pct_% of keys.
  bool doa_default_(uint64_t key) const {
    return doa_default_pct_ > 0 && (mix64_(key) % 100) < static_cast<uint64_t>(doa_default_pct_);
  }
  mutable std::unordered_map<uint64_t, int64_t> unmap_;  // DoA counter per key
  uint64_t cap_          = 0;
  Policy   pol_          = Policy::LRU;
  std::vector<Entry>    entries_;
  uint64_t clock_        = 0;
  uint64_t buf_cap_      = 0;
  uint64_t buf_clock_    = 0;
  std::vector<BufEntry> buffer_;
  // Instrumentation (active when buf_cap_ > 0, always unbounded):
  // seen_pcs_: every key ever passed to update() — distinguishes warm vs cold misses.
  // buf_evicted_pcs_: keys currently evicted from the buffer and not re-inserted.
  // shadow_map_: keys evicted from buffer → dead_count at eviction; cleared on re-entry.
  // oracle_buf_: unbounded accumulation of dead_count for all ever-evicted keys.
  std::unordered_set<uint64_t> seen_pcs_;
  mutable std::unordered_set<uint64_t> buf_evicted_pcs_;
  std::unordered_map<uint64_t, uint64_t> shadow_map_;
  std::unordered_map<uint64_t, uint64_t> oracle_buf_;
  mutable Stats stats_;
  // Eviction attribution counters (LFU_DOA bounded only, not reset with stats_).
  // At each hist-table eviction: record how much non-DoA penalty and aging
  // contributed to the evicted entry's score reduction, and whether they
  // drove it to zero.
  uint64_t evict_count_          = 0;
  uint64_t evict_ma_nonzero_     = 0;  // evictions where ma_loss > 0
  uint64_t evict_ma_loss_sum_    = 0;  // sum of ma_loss across all evicted entries
  uint64_t evict_ma_decisive_    = 0;  // evictions where eff_freq==0 AND ma_loss > 0
  uint64_t evict_aging_nonzero_  = 0;  // evictions where aging penalty > 0
  uint64_t evict_aging_loss_sum_ = 0;  // sum of aging penalties on evicted entries
  uint64_t evict_aging_decisive_ = 0;  // evictions where eff_freq==0 AND aging_penalty > 0
  uint64_t evict_aging_hitsum_   = 0;  // sum of hit_count for all aging-decisive evictions
  // Cached threshold (updated from update()'s arg) for use in victim_slot().
  int64_t  thd_doa_cache_  = 0;
  // PCs whose hist-table entry was last evicted due to aging (eff_freq==0 caused by aging).
  // Maps PC → {score, hit_count} at eviction time. Cleared when the PC is re-inserted.
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
    // DoA → protect (rrpv=0). Live → demote to eviction target (rrpv=SRRIP_MAX).
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

  // Promoted entries enter with higher priority than cold insertions.
  void on_promote(Entry& e, uint64_t dead_count) {
    e.promoted = true;
    e.last_seen_update = update_count_;
    switch (pol_) {
    case Policy::LRU:     e.ts = ++clock_; e.freq = 0; e.rrpv = 0;           break;
    case Policy::LFU:     e.freq = dead_count; e.ts = ++clock_; e.rrpv = 0;  break;
    // Buffer dead_count is in DoA units (1 per DoA hit); scale by 3 to match LFU_DOA freq units.
    case Policy::LFU_DOA: e.freq      = std::min(FREQ_CAP, dead_count * 3);
                          e.ma_loss   = 0;
                          e.hit_count = 0;
                          e.ts = ++clock_; e.rrpv = 0;
                          aging_evicted_pcs_.erase(e.key);                    break;
    case Policy::SRRIP:   e.rrpv = 0; e.freq = 0; e.ts = 0;                  break;
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
    ++stats_.promote_attempts;

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
    if (!promote) { ++stats_.promote_blocked; return; }

    // Evict worst main table entry → re-enter into best's buffer slot.
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
    best->second_chance = has_victim;  // demoted main entry must re-earn promotion
    if (has_victim) {
      ++stats_.demotions;
      buf_evicted_pcs_.erase(victim_key);  // back in the buffer; no longer "evicted"
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
      // Aging: lose 1 unit of replacement priority per cap_ idle updates (one full round).
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
      // Attribution: record how much MA penalty and aging contributed to this eviction.
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
        if (lv == liveness_class::doa) { a.count = std::min(a.count + 1, MAX_COUNTER); a.freq++; }
        else                           { a.count = 0; }
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
              auto& slot  = evict_addr(*pe);
              slot.addr   = b.addr;
              slot.count  = b.dead_count;
              slot.freq   = b.dead_count;
              slot.valid  = true;
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

    // --- No buffer: insert on DoA evictions only ---
    if (lv == liveness_class::doa) {
      auto& slot = evict_addr(*pe);
      slot.addr  = addr;
      slot.count = 1;
      slot.freq  = 1;
      slot.valid = true;
    }
  }

private:
  static constexpr uint64_t MAX_COUNTER = 16;

  struct AddrEntry {
    uint64_t addr        = 0;
    uint64_t count       = 0;  // DoA counter
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
  uint64_t liveness_bypasses = 0;    // LLC bypasses from repl_hist DoA classification
  uint64_t liveness_probes   = 0;    // DoA fills inserted as probes instead of bypassed (recheck)
  uint64_t liveness_bypass_shadow_hits = 0;  // re-references to bypassed blocks (confirmed bypass mistakes)
  uint64_t bypass_duel_suppressed = 0; // DoA fills not bypassed because the duel selected arm A (no-bypass)

  // DoA liveness stats.
  // For every cache: evictions = valid blocks displaced; doa = those never accessed.
  // For LLC only: doa_stlb_found / doa_stlb_also_doa track the reverse-STLB lookup
  // on each LLC DoA eviction — how often the corresponding STLB entry is still present
  // and also unaccessed (i.e., the LLC and STLB DoA are correlated).
  uint64_t evictions    = 0;
  uint64_t doa          = 0;
  // Recency 4-state census (LIVENESS_CHAR only): indexed by BLOCK::eviction_state
  // [0]=dead [1]=mid_lru [2]=mid_mru [3]=live.
  uint64_t recency_state[4] = {};
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
    uint64_t prop_pc = 0; // STLB→LLC propagated PC (STLB_LLC_PROP): the STLB PC that
                          // bypassed this block's page. 0 = none. Used to index the
                          // LLC liveness history table on eviction (matches the fill-time
                          // bypass decision). Kept separate from dp_pc/dp to avoid cbPred semantics.

    uint64_t address = 0;
    uint64_t v_address = 0;
    uint64_t data = 0;
    uint64_t ip = 0; // PC that caused the miss that filled this block

    uint32_t pf_metadata = 0;

    uint64_t install_cycle   = 0; // cycle when block was installed (for halflife classification)
    uint64_t last_hit_cycle  = 0; // cycle of most recent hit (0 = never hit)
    liveness_class ins_class = liveness_class::alive; // class predicted at fill time
    uint8_t eviction_state = 0; // 2-bit recency liveness state: 0=dead 1=mid_lru 2=mid_mru
                                // 3=live. Set online on each demand hit from the block's
                                // recency-stack rank, per RECENCY_VERSION. Reset to 0 on fill.
  };
  using set_type = std::vector<BLOCK>;

  std::pair<set_type::iterator, set_type::iterator> get_set_span(uint64_t address);
  std::pair<set_type::const_iterator, set_type::const_iterator> get_set_span(uint64_t address) const;
  std::size_t get_set_index(uint64_t address) const;

  // ── dpPred-cbPred predictor ──────────────────────────────────────────────

  // Shared physical-frame queue: dpPred fills it; cbPred reads it.
  // Each entry is (PFN, dpPred PC) so cbPred can use the PC as the bHIST key.
  inline static std::deque<std::pair<uint64_t, uint64_t>> pfq{};
  // STLB→LLC propagation (STLB_LLC_PROP): idealized/unbounded PFN→PC map. The STLB
  // bypass records PFN→(STLB PC); the LLC reads it at fill (always available, no
  // aging). This is the "magic" oracle store to evaluate whether the cross-level
  // signal helps at all — a realistic bounded structure comes later if it does.
  inline static std::unordered_map<uint64_t, uint64_t> prop_map{};
  // STLB→LLC propagation, PC-gate variant (PROP_GATE=pc): the set of PCs whose
  // translations the STLB bypassed. An LLC block is gated-in iff its own loading PC
  // is in this set (instruction-granular cross-level signal), vs the PFN-gate above
  // (page-granular). Idealized/unbounded, like prop_map.
  inline static std::unordered_set<uint64_t> stlb_dead_pcs{};
  inline static uint64_t pfq_cap = 8;

  // Set by cpu0_STLB during initialize(); read by LLC for reverse STLB DoA lookup.
  inline static const set_type* stlb_block_ptr = nullptr;

  // Per-instance state
  bool dppred = false;
  bool cbpred = false;
  uint64_t pconf_thd = 6; // phist confidence threshold
  uint64_t bconf_thd = 6; // bhist confidence threshold
  uint64_t thd_doa  = 1;  // repl_hist_pc: score >= thd_doa  → DoA (θ_doa)
  bool mid_promote = false; // promote DoA blocks to MRU on hit (srrip_live)
  uint64_t st_size = 2;   // shadow table capacity

  HistTable phist;           // PC → confidence (dpPred)
  // cbPred bHIST: three modes selected by BHIST_MODE env var.
  //   "flat" (default): HistTable keyed by block address (addr-indexed, exp004 style)
  //   "pc":     PCPartitionedTable keyed by (dpPred PC, block address) — requires PFQ hit
  //   "pconly": HistTable (bhist_flat) keyed by the dpPred PC ALONE — aggregates a PC's
  //             deadness across all its addresses (like our repl_hist), to isolate the
  //             per-PC-aggregate vs per-(PC,address) difference in the Mazumdar→ours bridge.
  bool use_pc_bhist = false;
  bool cbpred_pc_only_ = false;   // BHIST_MODE=pconly: bhist_flat keyed by dp_pc only
  bool cbpred_access_pc_ = false; // CBPRED_KEY set: use the clean ungated cbPred path
                                  // (learn every eviction, evict_lv + thresholds)
  bool cbpred_key_addr_  = false; // CBPRED_KEY=block_addr: key that clean path by block
                                  // address instead of the demand-access PC. Lets us vary
                                  // indexing and scoring ONE at a time in the morph.
  HistTable          bhist_flat;  // used when use_pc_bhist=false (keyed by address, or dp_pc if pc_only)
  PCPartitionedTable bhist_pc;    // used when use_pc_bhist=true
  std::deque<std::tuple<uint64_t, uint64_t, uint64_t>> shadow_table; // (VPN, data, PC)

  // Liveness-bypass shadow: block addresses our own predictor bypassed. A later
  // re-reference to one is a confirmed bypass mistake → we feed an alive
  // observation for that PC (which zeroes its score), so it stops bypassing.
  // Self-calibrating: silent when bypass is correct (no re-refs → no cost).
  // Enabled by BYPASS_SHADOW_SIZE (0 = disabled). Tags only, no data.
  uint64_t bypass_shadow_cap_ = 0;
  std::unordered_map<uint64_t, std::pair<uint64_t, uint64_t>> bypass_shadow_;  // block_addr → (pc, data)
  std::deque<uint64_t> bypass_shadow_fifo_;               // FIFO eviction order

  // Replacement guidance: use bHIST dead_count signals to guide cache replacement.
  // High dead_count → entry is often dead → better eviction target (prioritize eviction).
  // Used to integrate bypass predictor signals into replacement decisions.
  bool repl_guidance_enable = false;  // enable replacement guidance from bHIST
  uint64_t repl_guidance_thd = 0;     // threshold: dead_count >= thd → good victim

  // Most recent miss-fill latency in cycles (current_cycle - cycle_enqueued - 1),
  // set in handle_fill immediately before impl_update_replacement_state. Lets a
  // replacement module attribute per-fill miss cost (e.g. ipv_live set dueling on
  // total miss latency instead of hit count). 0 on warmup-elided fills.
  uint64_t last_fill_latency = 0;


  // Query bHIST for guidance score (dead_count) of a block for replacement.
  // Returns the dead_count from bHIST, or 0 if not found or guidance disabled.
  uint64_t get_repl_guidance_score(uint64_t block_address, uint64_t dp_pc) const;

  // Per-PC replacement guidance history.
  // Tracks a single score per PC: +1 on every DoA eviction, reset to 0 on any
  // accessed eviction. Updated at every LLC/STLB eviction.
  // Default: unbounded (unordered_map fallback, backward compatible).
  // Bounded: configured via REPL_HIST_{LLC,STLB}_CAP + REPL_HIST_{BUF_CAP,REPL} env vars
  // in load_predictor_settings(). Uses the same HistTable replacement policies
  // (lru/lfu/lfu_doa/srrip) and optional promotion buffer as phist/bhist.
  HistTable repl_hist_pc;
  bool repl_hist_use_addr{false};  // REPL_HIST_MODE=addr: index by block addr (LLC) or VPN (STLB)

  // DOA_COUNTER_TRACE=1: log every repl_hist_pc score update (ROI only) to
  // doa_counter_trace_<NAME>.csv as "cycle,pc,addr,evict_class,old_score,new_score",
  // so the full per-key counter time series can be reconstructed offline to
  // check whether scores saturate cleanly per PC or oscillate, and which
  // block addresses within a PC are driving its score.
  bool doa_trace_enable_ = false;
  std::ofstream doa_trace_file_;
  bool liveness_bypass{false};      // LIVENESS_BYPASS=1: bypass DoA LLC fills using repl_hist
  uint64_t bypass_thd{0};           // BYPASS_THD: score >= bypass_thd → bypass (must be >= thd_doa)
  bool stlb_liveness_bypass{false}; // STLB_LIVENESS_BYPASS=1: bypass DoA STLB fills using repl_hist
  uint64_t stlb_bypass_thd{0};      // STLB_BYPASS_THD: threshold for STLB bypass
  bool stlb_llc_prop_{false};       // STLB_LLC_PROP=1: STLB bypass records PFN→(STLB PC); the LLC
                                    // bypass predictor indexes repl_hist by that propagated STLB PC
                                    // for STLB-bypassed pages (cross-level, like Mazumdar's cbPred).
  bool prop_hybrid_{false};         // STLB_LLC_PROP_HYBRID=1 (version B): on a prop_map MISS, fall
                                    // back to the LLC's own PC for both predict and update. Off
                                    // (version A): a miss means no predict and no update (pure
                                    // cross-level / Mazumdar-like).
  bool prop_ownpc_{false};          // STLB_LLC_PROP_OWNPC=1 (version D): use the PFN match only as a
                                    // dead-page GATE (require a prop_map hit) but index repl_hist by
                                    // the LLC's OWN PC, not the propagated STLB PC. Isolates the gate
                                    // from the index.
  bool prop_gate_pc_{false};        // PROP_GATE=pc: gate the LLC predictor by the block's own PC being
                                    // in the STLB-dead-PC set (instruction-granular), indexing by own
                                    // PC — vs the default PFN-gate (page-granular, index by propagated
                                    // STLB PC). Tests whether the cross-level signal transfers better
                                    // at page or PC granularity.
  uint64_t bypass_fire_reset_period_{0}; // BYPASS_FIRE_RESET_PERIOD: reset scores every N bypass fires (global, legacy)
  uint64_t bypass_fire_count_{0};        // running count of bypass fires (for fire-based reset)

  // Bypass set-dueling (BYPASS_DUEL=1 + LIVENESS_BYPASS=1).
  // arm A: bypass suppressed; arm B: bypass active; followers adopt the lower-
  // miss-latency arm.  Independent of the replacement-guidance PSEL in srrip_live.
  bool     bypass_duel_enable_{false};
  int      bypass_duel_ns_{0};       // BYPASS_DUEL_N_SAMPLERS (default 32 when enabled)
  int64_t  bypass_duel_lat_a_{0};    // cumulative miss latency for arm-A sampler sets
  int64_t  bypass_duel_lat_b_{0};    // cumulative miss latency for arm-B sampler sets
  int64_t  bypass_duel_hyst_{0};     // BYPASS_DUEL_HYST: B must lead A by this margin to win

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

  // Per-(PC, address) DoA counter: enabled by DOA_ADDR_SUMMARY=1. Replays the
  // same +1-on-DoA/reset-on-alive rule as repl_hist_pc, but keyed by (pc, addr)
  // instead of pc alone, so we can see the distribution of counter values
  // *within* a PC's own address population -- not something the live
  // replacement decision ever computes (repl_hist_pc is always single-keyed),
  // this is diagnostic only. Aggregated per-PC summary printed at end_phase
  // instead of an event log, so it scales to suites with huge address counts
  // without writing multi-GB files.
  struct AddrCounterEntry { int64_t score = 0; bool ever_reset = false; };
  bool doa_addr_summary_enable_ = false;
  std::unordered_map<uint64_t, std::unordered_map<uint64_t, AddrCounterEntry>> doa_addr_table_;
  std::unordered_map<uint64_t, uint64_t> doa_addr_pc_doa_total_;  // pc -> total DoA events
  void record_doa_addr_summary(uint64_t pc, uint64_t addr, liveness_class evict_lv);
  void print_doa_addr_summary() const;

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
  void shadow_record_bypass(uint64_t block_addr, uint64_t pc, uint64_t data);  // record a bypassed block + its data
  bool liveness_bypass_shadow_hit(const PACKET& handle_pkt);            // re-reference of a bypassed block: erase history entry + reinsert; true → STLB miss satisfied
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
