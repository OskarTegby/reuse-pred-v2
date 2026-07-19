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

HistTable::HistTable(uint64_t cap)
  : unbounded_(false), cap_(cap), entries_(cap) {
}

bool HistTable::should_probe(uint64_t key) {
  if (recheck_mode_ == RecheckMode::Off) {
    return false;
  }
  uint64_t& cnt = recheck_count_[key];
  uint64_t  iv  = recheck_interval_[key];
  if (iv == 0) {
    iv = recheck_base_;
  }
  if (++cnt >= iv) {
    cnt = 0;
    recheck_probing_[key] = true;
    return true;
  }
  return false;
}

liveness_class HistTable::classify(uint64_t key, uint64_t thd_doa) const {
  if (unbounded_) {
    auto it = unmap_.find(key);
    if (it != unmap_.end() && it->second >= (int64_t)thd_doa) {
      return liveness_class::doa;
    }
    return liveness_class::alive;
  }
  for (const auto& e : entries_) {
    if (e.valid && e.key == key) {
      return e.score >= (int64_t)thd_doa ? liveness_class::doa : liveness_class::alive;
    }
  }
  return liveness_class::alive;
}

void HistTable::print_stats(const char* prefix) const {
  if (const char* d = std::getenv("REPL_HIST_DUMP_PCS"); d && d[0] == '1') {
    std::vector<std::pair<uint64_t, int64_t>> dump;
    if (unbounded_) {
      for (const auto& [k, v] : unmap_) {
        dump.emplace_back(k, v);
      }
    } else {
      for (const auto& e : entries_) {
        if (e.valid) {
          dump.emplace_back(e.key, e.score);
        }
      }
    }
    std::sort(dump.begin(), dump.end());
    printf("%s repl_hist PCS: count=%zu\n", prefix, dump.size());
    for (const auto& [k, sc] : dump) {
      printf("%s repl_hist PC: key=0x%lx doa=%ld\n", prefix, k, sc);
    }
  }
  if (unbounded_) {
    printf("%s repl_hist: unbounded (%zu entries)\n", prefix, unmap_.size());
    return;
  }
  const uint64_t main_occ = static_cast<uint64_t>(
      std::count_if(entries_.begin(), entries_.end(), [](const Entry& e){ return e.valid; }));
  printf("%s repl_hist occupancy : main %lu/%lu (%.0f%%)\n",
         prefix,
         main_occ, cap_,
         cap_ ? 100.0 * main_occ / cap_ : 0.0);
}

void HistTable::update(uint64_t key, liveness_class evict_class) {
  if (!unbounded_ && cap_ == 0) {
    return;
  }
  ++update_count_;
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
  if (unbounded_) {
    auto it = unmap_.find(key);
    if (it == unmap_.end()) {
      if (evict_class != liveness_class::doa) {
        return;
      }
      it = unmap_.emplace(key, 0).first;
    }
    it->second = (evict_class == liveness_class::doa) ? it->second + 1 : 0;
    return;
  }
  for (auto& e : entries_) {
    if (e.valid && e.key == key) {
      e.score = (evict_class == liveness_class::doa) ? e.score + 1 : 0;
      on_hit(e, evict_class);
      return;
    }
  }
  if (evict_class == liveness_class::doa) {
    auto& slot   = victim_slot();
    slot.key     = key;
    slot.score   = 1;
    slot.valid   = true;
    on_insert(slot, evict_class);
  }
}

void HistTable::on_hit(Entry& e, liveness_class evict_class) {
  const bool is_doa = evict_class == liveness_class::doa;
  e.last_seen_update = update_count_;
  if (is_doa) {
    e.freq = std::min(FREQ_CAP, e.freq + 3);
  }
  e.ts = ++clock_;
}

void HistTable::on_insert(Entry& e, liveness_class evict_class) {
  e.last_seen_update = update_count_;
  const bool is_doa = evict_class == liveness_class::doa;
  e.freq = is_doa ? 3 : 0;
  e.ts = ++clock_;
}

HistTable::Entry& HistTable::victim_slot() {
  for (auto& e : entries_) {
    if (!e.valid) {
      return e;
    }
  }
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
  return victim;
}
