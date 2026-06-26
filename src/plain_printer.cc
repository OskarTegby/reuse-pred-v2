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

    if (stats.evictions > 0) {
      stream << stats.name << " DOA: " << stats.doa << " / " << stats.evictions
             << " (" << std::fixed << std::setprecision(2) << (100.0 * stats.doa / stats.evictions) << "%)" << std::endl;
      stream << stats.name << " LIVENESS EVICTIONS: " << stats.evictions
             << "  DOA: " << stats.doa
             << " (" << std::fixed << std::setprecision(1) << (100.0 * stats.doa / stats.evictions) << "%)"
             << "  MOSTLY_DEAD: " << stats.mostly_dead
             << " (" << (100.0 * stats.mostly_dead / stats.evictions) << "%)"
             << "  MOSTLY_ALIVE: " << stats.mostly_alive
             << " (" << (100.0 * stats.mostly_alive / stats.evictions) << "%)"
             << std::endl;
      if (stats.doa_stlb_found > 0)
        stream << stats.name << " DOA_STLB_CORR: " << stats.doa_stlb_also_doa << " / " << stats.doa_stlb_found
               << " (" << std::fixed << std::setprecision(2) << (100.0 * stats.doa_stlb_also_doa / stats.doa_stlb_found) << "%)" << std::endl;
    }
    if (stats.llt_bypasses > 0)
      stream << stats.name << " LLT_BYPASSES: " << stats.llt_bypasses << std::endl;
    if (stats.llc_bypasses > 0 || stats.pfq_hits > 0) {
      stream << stats.name << " LLC_BYPASSES: " << stats.llc_bypasses << "  PFQ_HITS: " << stats.pfq_hits;
      if (stats.cbpred_nogate_bypasses > 0)
        stream << "  NOGATE_BYPASSES: " << stats.cbpred_nogate_bypasses;
      stream << std::endl;
    }
    if (stats.liveness_bypasses > 0)
      stream << stats.name << " LIVENESS_BYPASSES: " << stats.liveness_bypasses << std::endl;
    if (stats.liveness_probes > 0)
      stream << stats.name << " LIVENESS_PROBES: " << stats.liveness_probes << std::endl;
    if (stats.liveness_bypass_shadow_hits > 0)
      stream << stats.name << " LIVENESS_BYPASS_SHADOW_HITS: " << stats.liveness_bypass_shadow_hits << std::endl;
    if (stats.bypass_duel_suppressed > 0)
      stream << stats.name << " BYPASS_DUEL_SUPPRESSED: " << stats.bypass_duel_suppressed << std::endl;
    // History table utilisation (ROI only).
    auto print_hist = [&](const char* tag, uint64_t q, uint64_t h, uint64_t p, uint64_t ph) {
      if (q == 0) return;
      stream << stats.name << " " << tag << "_HIT_RATE: "
             << std::fixed << std::setprecision(2) << (100.0 * h / q) << "%"
             << "  QUERIES: " << q << "  HITS: " << h;
      if (p > 0)
        stream << "  PROMOTIONS: " << p
               << "  PROMOTED_HIT_RATE: "
               << std::setprecision(2) << (100.0 * ph / p) << "%";
      stream << std::endl;
    };
    print_hist("PHIST", stats.phist_queries, stats.phist_table_hits,
               stats.phist_promotions, stats.phist_promoted_hits);
    print_hist("BHIST", stats.bhist_queries, stats.bhist_table_hits,
               stats.bhist_promotions, stats.bhist_promoted_hits);
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
