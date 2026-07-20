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

#include <cstdio>

uint64_t HistTable::hash_pc(uint64_t pc) {
  return (pc ^ (pc >> 2) ^ (pc >> 5)) % PRED_COUNTERS;
}

liveness_class HistTable::classify(uint64_t key, uint64_t thd_doa) const {
  return counters_[hash_pc(key)] >= thd_doa ? liveness_class::doa : liveness_class::alive;
}

void HistTable::update(uint64_t key, liveness_class evict_class) {
  unsigned& ctr = counters_[hash_pc(key)];
  if (evict_class == liveness_class::doa) {
    if (ctr < COUNTER_MAX) {
      ++ctr;
    }
  } else {
    ctr = 0;
  }
}

void HistTable::print_stats(const char* prefix) const {
  unsigned nonzero = 0;
  for (unsigned i = 0; i < PRED_COUNTERS; ++i) {
    if (counters_[i] > 0) {
      ++nonzero;
    }
  }
  printf("%s repl_hist occupancy : main %u/%u (%.0f%%)\n",
         prefix, nonzero, PRED_COUNTERS,
         100.0 * nonzero / PRED_COUNTERS);
}
