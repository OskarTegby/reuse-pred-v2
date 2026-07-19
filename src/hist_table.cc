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
  : cap_(cap), entries_(cap) {
}

liveness_class HistTable::classify(uint64_t key, uint64_t thd_doa) const {
  if (cap_ == 0) {
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
    if (cap_ == 0) {
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
  if (cap_ == 0) {
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
  ++update_count_;
  if (cap_ == 0) {
    update_unbounded(key, evict_class);
  } else {
    update_bounded(key, evict_class);
  }
}

void HistTable::update_unbounded(uint64_t key, liveness_class evict_class) {
  auto it = unmap_.find(key);
  if (it == unmap_.end()) {
    if (evict_class != liveness_class::doa) {
      return;
    }
    it = unmap_.emplace(key, 0).first;
  }
  it->second = (evict_class == liveness_class::doa) ? it->second + 1 : 0;
}

void HistTable::update_bounded(uint64_t key, liveness_class evict_class) {
  for (auto& e : entries_) {
    if (e.valid && e.key == key) {
      const bool is_doa = evict_class == liveness_class::doa;
      e.score = is_doa ? e.score + 1 : 0;
      if (is_doa) {
        e.freq = std::min(FREQ_CAP, e.freq + 3);
      }
      e.last_seen_update = update_count_;
      return;
    }
  }
  if (evict_class == liveness_class::doa) {
    auto& slot          = victim_slot();
    slot.key            = key;
    slot.score          = 1;
    slot.valid          = true;
    slot.freq           = 3;
    slot.last_seen_update = update_count_;
  }
}

HistTable::Entry& HistTable::victim_slot() {
  for (auto& e : entries_) {
    if (!e.valid) {
      return e;
    }
  }
  auto eff = [&](const Entry& e) -> uint64_t {
    const uint64_t idle    = update_count_ - e.last_seen_update;
    const uint64_t penalty = idle / cap_;
    return e.freq > penalty ? e.freq - penalty : 0;
  };
  Entry& victim = *std::min_element(entries_.begin(), entries_.end(),
    [&](const Entry& a, const Entry& b){
      const uint64_t fa = eff(a), fb = eff(b);
      return fa < fb || (fa == fb && a.last_seen_update < b.last_seen_update); });
  return victim;
}
