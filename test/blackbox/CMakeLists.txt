# Black-box regression tests for the liveness replacement policies.
#
# Each scenario runs a liveness binary on the deterministic pagerank trace and
# byte-diffs the full ChampSim report against expected/<name>.<phase>.out.
# Determinism (same binary + same trace = bit-identical output, modulo the
# stripped wall-clock line) is what lets a golden diff guard the whole report
# with zero tolerance.
#
# Two phases per scenario:
#   <name>_gate   ~250K instructions (~3s)  — fast early check
#   <name>_full    2M  instructions (~25s)  — thorough guard
#
# The gate is a CTest fixture SETUP; the full REQUIRES it.  If the gate fails,
# CTest skips the full automatically — no wasted 25s on an already-broken
# scenario, and no separate long suite to forget to run.  Because warmup is
# identical and only the sim window differs, the gate is a true prefix of the
# full: passing the gate proves nothing diverged through instruction 250K.
#
# Usage:
#   cmake -S test/blackbox -B test/blackbox/cmake_build
#   ctest --test-dir test/blackbox/cmake_build -L gate -j8        # fast loop (~15s)
#   ctest --test-dir test/blackbox/cmake_build -j8 --output-on-failure  # gate+full
#   ctest --test-dir test/blackbox/cmake_build -L invariants      # ordering only
#
# Regenerate goldens after an intentional change (review the diff first):
#   GENERATE=1 bash test/blackbox/run_scenario.sh <name> gate
#   GENERATE=1 bash test/blackbox/run_scenario.sh <name> full
#
cmake_minimum_required(VERSION 3.16)
project(reuse_pred_blackbox NONE)
enable_testing()

get_filename_component(SRC_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
set(RUNNER  "${CMAKE_CURRENT_SOURCE_DIR}/run_scenario.sh")
set(ORDERER "${CMAKE_CURRENT_SOURCE_DIR}/assert_order.sh")
set(OUT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/test_outputs")
set(ENV_COMMON "SRC_ROOT=${SRC_ROOT};OUTPUT_DIR=${OUT_DIR}")

# A scenario: a fast gate (fixture setup) + a full run gated on it.
# Exit 77 (binary/trace missing) is reported as "skipped", not failed.
function(cs_scenario name)
  add_test(NAME ${name}_gate COMMAND bash ${RUNNER} ${name} gate)
  set_tests_properties(${name}_gate PROPERTIES
    LABELS "gate" TIMEOUT 120 SKIP_RETURN_CODE 77
    FIXTURES_SETUP fx_${name}
    ENVIRONMENT "${ENV_COMMON}")

  add_test(NAME ${name}_full COMMAND bash ${RUNNER} ${name} full)
  set_tests_properties(${name}_full PROPERTIES
    LABELS "full" TIMEOUT 300 SKIP_RETURN_CODE 77
    FIXTURES_REQUIRED fx_${name}
    ENVIRONMENT "${ENV_COMMON}")
endfunction()

# An invariant: assert an IPC ordering between two scenarios, on the gate phase
# (so it runs in the fast loop).  Requires both scenarios' gate fixtures, which
# makes their gate outputs available for comparison.
function(cs_order name a op b)
  add_test(NAME ${name} COMMAND bash ${ORDERER} ${a} ${op} ${b})
  set_tests_properties(${name} PROPERTIES
    LABELS "invariants" TIMEOUT 300 SKIP_RETURN_CODE 77
    FIXTURES_REQUIRED "fx_${a};fx_${b}"
    ENVIRONMENT "${ENV_COMMON}")
endfunction()

# ---- scenarios ----
cs_scenario(lru_default)
cs_scenario(lru_2n3)
cs_scenario(lru_lru)
cs_scenario(lru_bypass)
cs_scenario(lru_bypass_off)
cs_scenario(lru_duel_hits)
cs_scenario(lru_duel_lat_hyst)
cs_scenario(lru_cap256)

cs_scenario(srrip_default)
cs_scenario(srrip_mode3)
cs_scenario(srrip_mode4)
cs_scenario(srrip_mode5)
cs_scenario(srrip_mode7)
cs_scenario(srrip_mode8)
cs_scenario(srrip_cap256)
cs_scenario(srrip_duel_cfg0)
cs_scenario(srrip_bypass_fixed)
cs_scenario(srrip_bypass_duel)

cs_scenario(ipv_default)
cs_scenario(ipv_canonical)
cs_scenario(ipv_ins3_comma)
cs_scenario(ipv_ins3_colon)
cs_scenario(ipv_cap256)

cs_scenario(duel_ipv_cfg0_ins2)
cs_scenario(duel_ipv_cfg0_ins3)
cs_scenario(duel_ipv_3way)

# ---- directional invariants ----
# On a 100% DoA trace, freeing LLC ways faster raises IPC: bypass and plain-LRU
# insertion both beat 2n3 insertion.
cs_order(inv_bypass_beats_2n3   lru_bypass gt lru_2n3)
cs_order(inv_lru_beats_2n3      lru_lru    gt lru_2n3)
# ins@3 evicts DoA blocks immediately, beating ins@2 (canonical).
cs_order(inv_ins3_beats_ins2    ipv_ins3_comma gt ipv_canonical)
# Set dueling: assigning the stronger config (ins@3) to the cfg0 sampler makes
# followers converge to it, raising IPC over assigning ins@2.
cs_order(inv_duel_follower_conv duel_ipv_cfg0_ins3 gt duel_ipv_cfg0_ins2)
