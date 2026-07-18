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
#include <numeric>

HistTable::HistTable(uint64_t cap, Policy pol, uint64_t buf_cap, uint64_t /*shadow_cap*/)
  : unbounded_(false), cap_(cap), pol_(pol), entries_(cap), buf_cap_(buf_cap), buffer_(buf_cap) {
  if (const char* ev = std::getenv("HIST_MA_PENALTY"))
    ma_penalty_ = std::atoi(ev);
}

void HistTable::record_bypass(uint64_t key) {
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

void HistTable::erase_key(uint64_t key) {
  if (unbounded_) { unmap_.erase(key); }
  else { for (auto& e : entries_) if (e.valid && e.key == key) { e.valid = false; break; } }
  bypass_since_update_.erase(key);
}

bool HistTable::should_probe(uint64_t key) {
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

int64_t HistTable::get_score(uint64_t key) const {
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

liveness_class HistTable::classify(uint64_t key, uint64_t thd_doa) const {
  key = hk_(key);
  if (unbounded_) {
    auto it = unmap_.find(key);
    if (it != unmap_.end() && it->second >= (int64_t)thd_doa) return liveness_class::doa;
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
    auto ait = aging_evicted_pcs_.find(key);
    if (ait != aging_evicted_pcs_.end()) {
      ++stats_.classify_warm_aged_out;
      stats_.classify_warm_aged_hitsum += ait->second.second;
    }
  } else {
    ++stats_.classify_cold_miss;
  }
  return liveness_class::alive;
}

void HistTable::print_stats(const char* prefix, uint64_t thd_doa) const {
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
      if (stats_.classify_warm_aged_out > 0) {
        auto avg_h = [](uint64_t sum, uint64_t n) { return n ? (double)sum / n : 0.0; };
        printf("%s repl_hist warm_aged : aged_out=%lu (%.1f%% of warm)  avg_hits=%.1f\n",
               prefix,
               stats_.classify_warm_aged_out,
               pct_c(stats_.classify_warm_aged_out),
               avg_h(stats_.classify_warm_aged_hitsum, stats_.classify_warm_aged_out));
      }
    }
  }
  if (evict_count_ > 0) {
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

void HistTable::update(uint64_t key, liveness_class evict_class, int64_t thd_doa) {
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

void HistTable::on_hit(Entry& e, liveness_class evict_class) {
  const bool is_doa = evict_class == liveness_class::doa;
  e.last_seen_update = update_count_;
  if (is_doa) e.freq = std::min(FREQ_CAP, e.freq + 3);
  else if (ma_penalty_ < 0) {
    const uint64_t loss   = static_cast<uint64_t>(-ma_penalty_);
    const uint64_t actual = std::min(e.freq, loss);
    e.ma_loss += actual;
    e.freq    -= actual;
  }
  ++e.hit_count;
  e.ts = ++clock_;
}

void HistTable::on_insert(Entry& e, liveness_class evict_class) {
  e.promoted = false;
  e.last_seen_update = update_count_;
  const bool is_doa = evict_class == liveness_class::doa;
  e.freq      = is_doa ? 3 : 0;
  e.ma_loss   = 0;
  e.hit_count = 0;
  e.ts = ++clock_; e.rrpv = 0;
  aging_evicted_pcs_.erase(e.key);
}

void HistTable::on_promote(Entry& e, uint64_t dead_count) {
  e.promoted = true;
  e.last_seen_update = update_count_;
  e.freq      = std::min(FREQ_CAP, dead_count * 3);
  e.ma_loss   = 0;
  e.hit_count = 0;
  e.ts = ++clock_; e.rrpv = 0;
  aging_evicted_pcs_.erase(e.key);
}

void HistTable::try_promote() {
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
    uint64_t min_freq = UINT64_MAX;
    for (const auto& e : entries_) min_freq = std::min(min_freq, e.freq);
    promote = best->dead_count > min_freq;
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

HistTable::Entry& HistTable::victim_slot() {
  for (auto& e : entries_) if (!e.valid) return e;
  stats_.main_ever_full = true;
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

HistTable::BufEntry& HistTable::buf_victim() {
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
