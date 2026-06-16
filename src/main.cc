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

#include <algorithm>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <functional>
#include <getopt.h>
#include <iostream>
#include <signal.h>
#include <string>
#include <unistd.h>
#include <vector>

#if __has_include("git_version.h")
#include "git_version.h"
#endif
#ifndef CHAMPSIM_GIT_SHA
#define CHAMPSIM_GIT_SHA "unknown"
#endif
#ifndef CHAMPSIM_GIT_DIRTY
#define CHAMPSIM_GIT_DIRTY "unknown"
#endif

#include "cache.h"
#include "champsim.h"
#include "champsim_constants.h"
#include "core_inst.inc"
#include "dram_controller.h"
#include "ooo_cpu.h"
#include "operable.h"
#include "phase_info.h"
#include "ptw.h"
#include "stats_printer.h"
#include "util.h"
#include "vmem.h"

namespace champsim
{
std::vector<phase_stats> main(environment& env, std::vector<phase_info>& phases, bool knob_cloudsuite, std::vector<std::string> trace_names);
}

void signal_handler(int signal)
{
  std::cout << "Caught signal: " << signal << std::endl;
  abort();
}

int main(int argc, char** argv)
{
  // interrupt signal hanlder
  struct sigaction sigIntHandler;
  sigIntHandler.sa_handler = signal_handler;
  sigemptyset(&sigIntHandler.sa_mask);
  sigIntHandler.sa_flags = 0;
  sigaction(SIGINT, &sigIntHandler, NULL);

  champsim::configured::generated_environment gen_environment{};

  // initialize knobs
  uint8_t knob_cloudsuite = 0;
  uint64_t warmup_instructions = 1000000, simulation_instructions = 10000000;
  bool knob_json_out = false;
  std::ofstream json_file;

  // check to see if knobs changed using getopt_long()
  int traces_encountered = 0;
  static struct option long_options[] = {{"warmup_instructions", required_argument, 0, 'w'},
                                         {"simulation_instructions", required_argument, 0, 'i'},
                                         {"hide_heartbeat", no_argument, 0, 'h'},
                                         {"cloudsuite", no_argument, 0, 'c'},
                                         {"json", optional_argument, 0, 'j'},
                                         {"traces", no_argument, &traces_encountered, 1},
                                         {0, 0, 0, 0}};

  int c;
  while ((c = getopt_long_only(argc, argv, "w:i:hc", long_options, NULL)) != -1 && !traces_encountered) {
    switch (c) {
    case 'w':
      warmup_instructions = atol(optarg);
      break;
    case 'i':
      simulation_instructions = atol(optarg);
      break;
    case 'h':
      for (O3_CPU& cpu : gen_environment.cpu_view())
        cpu.show_heartbeat = false;
      break;
    case 'c':
      knob_cloudsuite = 1;
      break;
    case 'j':
      knob_json_out = true;
      if (optarg)
        json_file.open(optarg);
    case 0:
      break;
    default:
      abort();
    }
  }

  std::vector<std::string> trace_names{std::next(argv, optind), std::next(argv, argc)};

  std::vector<champsim::phase_info> phases{{champsim::phase_info{"Warmup", true, warmup_instructions, trace_names},
                                            champsim::phase_info{"Simulation", false, simulation_instructions, trace_names}}};

  std::cout << std::endl;
  std::cout << "*** ChampSim Multicore Out-of-Order Simulator ***" << std::endl;
  std::cout << std::endl;
  std::cout << "Warmup Instructions: " << phases[0].length << std::endl;
  std::cout << "Simulation Instructions: " << phases[1].length << std::endl;
  std::cout << "Number of CPUs: " << std::size(gen_environment.cpu_view()) << std::endl;
  std::cout << "Page size: " << PAGE_SIZE << std::endl;
  std::cout << std::endl;

  // Dump full run configuration + build provenance to a sidecar file named by the
  // launcher via CHAMPSIM_RUN_CONFIG. Cache/TLB geometry is compile-time and is
  // otherwise never recorded anywhere, so this lets us pinpoint exactly what
  // settings (and which source commit) produced a result. Kept out of stdout.
  if (const char* cfg_path = std::getenv("CHAMPSIM_RUN_CONFIG"); cfg_path != nullptr && cfg_path[0] != '\0') {
    if (std::ofstream cfg{cfg_path}; cfg) {
      char host[256] = {0};
      if (gethostname(host, sizeof(host) - 1) != 0)
        std::snprintf(host, sizeof(host), "%s", "unknown");
      std::time_t now = std::time(nullptr);
      char tbuf[64] = "unknown";
      if (std::tm* lt = std::localtime(&now); lt != nullptr)
        std::strftime(tbuf, sizeof(tbuf), "%Y-%m-%dT%H:%M:%S", lt);

      cfg << "# ChampSim run configuration and build provenance\n";
      cfg << "git_sha=" << CHAMPSIM_GIT_SHA << "\n";
      cfg << "git_dirty=" << CHAMPSIM_GIT_DIRTY << "\n";
      cfg << "build_time=" << __DATE__ " " __TIME__ << "\n";
      cfg << "run_time=" << tbuf << "\n";
      cfg << "hostname=" << host << "\n";
      cfg << "cmdline=";
      for (int i = 0; i < argc; ++i)
        cfg << (i ? " " : "") << argv[i];
      cfg << "\n";
      cfg << "num_cpus=" << std::size(gen_environment.cpu_view()) << "\n";
      cfg << "page_size=" << PAGE_SIZE << "\n";
      cfg << "block_size=" << BLOCK_SIZE << "\n";
      cfg << "warmup_instructions=" << phases[0].length << "\n";
      cfg << "simulation_instructions=" << phases[1].length << "\n";
      cfg << "dram_channels=" << DRAM_CHANNELS << " dram_width_bits=" << (8 * DRAM_CHANNEL_WIDTH)
          << " dram_io_freq_MTps=" << DRAM_IO_FREQ << "\n";

      cfg << "# caches/TLBs: NAME sets ways line_bytes mshr fill_latency\n";
      for (CACHE& cache : gen_environment.cache_view())
        cfg << "cache " << cache.NAME << " sets=" << cache.NUM_SET << " ways=" << cache.NUM_WAY
            << " line=" << (1U << cache.OFFSET_BITS) << " mshr=" << cache.MSHR_SIZE
            << " fill_latency=" << cache.FILL_LATENCY << "\n";

      cfg << "# traces\n";
      for (const auto& t : trace_names)
        cfg << "trace=" << t << "\n";

      cfg << "# environment knobs (value or <unset>)\n";
      static const char* const env_keys[] = {
          "SCORING_MODE", "THD_DOA", "THD_DEAD", "LLC_THD_DOA", "LLC_THD_DEAD", "STLB_THD_DOA", "STLB_THD_DEAD",
          "MID_THD", "LOW_THD", "BHIST_MODE", "SRRIP_LIVE_TARGET", "LRU_LIVE_HIT_INIT",
          "LIVENESS_BYPASS", "BYPASS_THD", "STLB_LIVENESS_BYPASS", "STLB_BYPASS_THD",
          "CBPRED", "DPPRED", "CBPRED_IDX", "DPPRED_IDX", "CBPRED_KEY", "MAZ_UNBOUNDED", "BHIST_HASH", "PHIST_HASH",
          "BHIST_WAYS", "BHIST_PC_WAYS", "REPL_HIST_LLC_CAP", "REPL_HIST_STLB_CAP", "REPL_HIST_BUF_CAP", "REPL_HIST_REPL",
          "PFQ_CAP", "LIVENESS_CHAR", "ST_SIZE", "JOB_ID", "SGE_TASK_ID"};
      for (const char* k : env_keys) {
        const char* v = std::getenv(k);
        cfg << "env " << k << "=" << (v ? v : "<unset>") << "\n";
      }
    }
  }

  auto phase_stats = champsim::main(gen_environment, phases, knob_cloudsuite, trace_names);

  std::cout << std::endl;
  std::cout << "ChampSim completed all CPUs" << std::endl;
  std::cout << std::endl;

  champsim::plain_printer default_print{std::cout};
  default_print.print(phase_stats);

  for (CACHE& cache : gen_environment.cache_view())
    cache.impl_prefetcher_final_stats();

  for (CACHE& cache : gen_environment.cache_view())
    cache.impl_replacement_final_stats();

  if (knob_json_out) {
    if (json_file.is_open()) {
      champsim::json_printer printer{json_file};
      printer.print(phase_stats);
    } else {
      champsim::json_printer printer{std::cout};
      printer.print(phase_stats);
    }
  }

  return 0;
}
