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

#include <iomanip>
#include <iostream>
#include <numeric>
#include <sstream>
#include <utility>
#include <vector>

#include "stats_printer.h"

void champsim::plain_printer::print(O3_CPU::stats_type stats)
{
  constexpr std::array<std::pair<std::string_view, std::size_t>, 6> types{
      {std::pair{"BRANCH_DIRECT_JUMP", BRANCH_DIRECT_JUMP}, std::pair{"BRANCH_INDIRECT", BRANCH_INDIRECT}, std::pair{"BRANCH_CONDITIONAL", BRANCH_CONDITIONAL},
       std::pair{"BRANCH_DIRECT_CALL", BRANCH_DIRECT_CALL}, std::pair{"BRANCH_INDIRECT_CALL", BRANCH_INDIRECT_CALL},
       std::pair{"BRANCH_RETURN", BRANCH_RETURN}}};

  auto total_branch = std::ceil(
      std::accumulate(std::begin(types), std::end(types), 0ll, [tbt = stats.total_branch_types](auto acc, auto next) { return acc + tbt[next.second]; }));
  auto total_mispredictions = std::ceil(
      std::accumulate(std::begin(types), std::end(types), 0ll, [btm = stats.branch_type_misses](auto acc, auto next) { return acc + btm[next.second]; }));

  stream << std::endl;
  stream << stats.name << " cumulative IPC: " << std::ceil(stats.instrs()) / std::ceil(stats.cycles()) << " instructions: " << stats.instrs()
         << " cycles: " << stats.cycles() << std::endl;
  stream << stats.name << " Branch Prediction Accuracy: " << (100.0 * std::ceil(total_branch - total_mispredictions)) / total_branch
         << "% MPKI: " << (1000.0 * total_mispredictions) / std::ceil(stats.instrs());
  stream << " Average ROB Occupancy at Mispredict: " << std::ceil(stats.total_rob_occupancy_at_branch_mispredict) / total_mispredictions << std::endl;

  std::vector<double> mpkis;
  std::transform(std::begin(stats.branch_type_misses), std::end(stats.branch_type_misses), std::back_inserter(mpkis),
                 [instrs = stats.instrs()](auto x) { return 1000.0 * std::ceil(x) / std::ceil(instrs); });

  stream << "Branch type MPKI" << std::endl;
  for (auto [str, idx] : types)
    stream << str << ": " << mpkis[idx] << std::endl;
  stream << std::endl;
}

void champsim::plain_printer::print(CACHE::stats_type stats)
{
  constexpr std::array<std::pair<std::string_view, std::size_t>, 5> types{
      {std::pair{"LOAD", LOAD}, std::pair{"RFO", RFO}, std::pair{"PREFETCH", PREFETCH}, std::pair{"WRITE", WRITE}, std::pair{"TRANSLATION", TRANSLATION}}};

  for (std::size_t cpu = 0; cpu < NUM_CPUS; ++cpu) {
    uint64_t TOTAL_HIT = 0, TOTAL_MISS = 0;
    for (const auto& type : types) {
      TOTAL_HIT += stats.hits.at(type.second).at(cpu);
      TOTAL_MISS += stats.misses.at(type.second).at(cpu);
    }

    stream << stats.name << " TOTAL       ";
    stream << "ACCESS: " << std::setw(10) << TOTAL_HIT + TOTAL_MISS << "  ";
    stream << "HIT: " << std::setw(10) << TOTAL_HIT << "  ";
    stream << "MISS: " << std::setw(10) << TOTAL_MISS << std::endl;

    for (const auto& type : types) {
      std::ostringstream name;
      name << std::left << std::setw(12) << type.first;
      stream << stats.name << " " << name.str() << " ";
      stream << "ACCESS: " << std::setw(10) << stats.hits[type.second][cpu] + stats.misses[type.second][cpu] << "  ";
      stream << "HIT: " << std::setw(10) << stats.hits[type.second][cpu] << "  ";
      stream << "MISS: " << std::setw(10) << stats.misses[type.second][cpu] << std::endl;
    }

    stream << stats.name << " PREFETCH  ";
    stream << "REQUESTED: " << std::setw(10) << stats.pf_requested << "  ";
    stream << "ISSUED: " << std::setw(10) << stats.pf_issued << "  ";
    stream << "USEFUL: " << std::setw(10) << stats.pf_useful << "  ";
    stream << "USELESS: " << std::setw(10) << stats.pf_useless << std::endl;

    stream << stats.name << " AVERAGE MISS LATENCY: " << std::ceil(stats.total_miss_latency) / std::ceil(TOTAL_MISS) << " cycles" << std::endl;

    if (stats.name == "cpu0_STLB")
      stream << stats.name << " BYPASSES: " << std::setw(10) << stats.llt_bypasses << std::endl;
    if (stats.name == "LLC")
      stream << stats.name << " BYPASSES: " << std::setw(10) << stats.llc_bypasses << std::endl;

    if (stats.name == "cpu0_STLB" || stats.name == "LLC") {
      const auto& s = stats;
      const double total = static_cast<double>(s.evict_total ? s.evict_total : 1);
      stream << s.name << " LIVENESS EVICTIONS: " << s.evict_total
             << "  DOA: "         << s.evict_doa          << " (" << std::fixed << std::setprecision(1) << 100.0 * s.evict_doa          / total << "%)"
             << "  MOSTLY_DEAD: " << s.evict_mostly_dead  << " (" << 100.0 * s.evict_mostly_dead  / total << "%)"
             << "  MOSTLY_ALIVE: "<< s.evict_mostly_alive << " (" << 100.0 * s.evict_mostly_alive / total << "%)"
             << std::endl;
      stream << s.name << " LIVENESS HIT_HIST:";
      for (std::size_t i = 0; i < cache_stats::HIT_HIST_BINS; ++i) {
        if (i + 1 < cache_stats::HIT_HIST_BINS)
          stream << "  " << i << ":" << s.evict_hit_hist[i];
        else
          stream << "  " << i << "+:" << s.evict_hit_hist[i];
      }
      stream << std::endl;

      // ── Suspicious-condition summary (omitted when zero) ──────────────────
      if (s.evict_zero_residence > 0)
        stream << s.name << " LIVENESS WARNING: " << s.evict_zero_residence
               << " eviction(s) with zero residence (installed and evicted same cycle)"
               << std::endl;
      if (s.evict_saturated_hitcount > 0)
        stream << s.name << " LIVENESS WARNING: " << s.evict_saturated_hitcount
               << " eviction(s) with saturated hit_count (>= " << UINT16_MAX
               << "); dead-tail may be overstated for those entries"
               << std::endl;

      // ── Consistency checks ────────────────────────────────────────────────
      // (1) The three liveness classes are mutually exclusive and exhaustive.
      const uint64_t class_sum = s.evict_doa + s.evict_mostly_dead + s.evict_mostly_alive;
      if (class_sum != s.evict_total)
        stream << s.name << " LIVENESS BUG: class counts sum to " << class_sum
               << " but evict_total is " << s.evict_total
               << " (delta " << static_cast<int64_t>(class_sum) - static_cast<int64_t>(s.evict_total) << ")"
               << std::endl;

      // (2) Every eviction increments exactly one histogram bin.
      const uint64_t hist_sum = std::accumulate(s.evict_hit_hist.begin(),
                                                 s.evict_hit_hist.end(), uint64_t{0});
      if (hist_sum != s.evict_total)
        stream << s.name << " LIVENESS BUG: hit_hist sums to " << hist_sum
               << " but evict_total is " << s.evict_total
               << " (delta " << static_cast<int64_t>(hist_sum) - static_cast<int64_t>(s.evict_total) << ")"
               << std::endl;
    }
    // stream << " AVERAGE MISS LATENCY: " << (stats.total_miss_latency)/TOTAL_MISS << " cycles " << stats.total_miss_latency << "/" << TOTAL_MISS<< std::endl;
  }
}

void champsim::plain_printer::print(DRAM_CHANNEL::stats_type stats)
{
  stream << stats.name << std::endl;
  stream << " RQ ROW_BUFFER_HIT: " << std::setw(10) << stats.RQ_ROW_BUFFER_HIT << std::endl;
  stream << "  ROW_BUFFER_MISS: " << std::setw(10) << stats.RQ_ROW_BUFFER_MISS << std::endl;
  stream << " AVG DBUS CONGESTED CYCLE: ";
  if (stats.dbus_count_congested > 0)
    stream << std::setw(10) << std::ceil(stats.dbus_cycle_congested) / std::ceil(stats.dbus_count_congested);
  else
    stream << "-";
  stream << std::endl;
  stream << " WQ ROW_BUFFER_HIT: " << std::setw(10) << stats.WQ_ROW_BUFFER_HIT << std::endl;
  stream << "  ROW_BUFFER_MISS: " << std::setw(10) << stats.WQ_ROW_BUFFER_MISS;
  stream << "  FULL: " << std::setw(10) << stats.WQ_FULL << std::endl;
  stream << std::endl;
}

void champsim::plain_printer::print(champsim::phase_stats& stats)
{
  stream << "=== " << stats.name << " ===" << std::endl;

  int i = 0;
  for (auto tn : stats.trace_names)
    stream << "CPU " << i++ << " runs " << tn << std::endl;

  if (NUM_CPUS > 1) {
    stream << std::endl;
    stream << "Total Simulation Statistics (not including warmup)" << std::endl;

    for (const auto& stat : stats.sim_cpu_stats)
      print(stat);

    for (const auto& stat : stats.sim_cache_stats)
      print(stat);
  }

  stream << std::endl;
  stream << "Region of Interest Statistics" << std::endl;

  for (const auto& stat : stats.roi_cpu_stats)
    print(stat);

  for (const auto& stat : stats.roi_cache_stats)
    print(stat);

  stream << std::endl;
  stream << "DRAM Statistics" << std::endl;
  for (const auto& stat : stats.roi_dram_stats)
    print(stat);
}

void champsim::plain_printer::print(std::vector<phase_stats>& stats)
{
  for (auto p : stats)
    print(p);
}
