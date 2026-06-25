# Black-box regression tests for the liveness replacement policies.
#
# Each scenario runs a liveness binary on the deterministic pagerank trace and
# byte-diffs the full ChampSim report against test/blackbox/expected/<name>.out.
# Determinism (same binary + same trace = bit-identical output, modulo the
# stripped wall-clock line) is what lets a golden diff guard the whole report
# with zero tolerance.  A handful of cross-scenario invariants additionally pin
# directional relationships the design depends on.
#
# Usage:
#   cmake -S test/blackbox -B test/blackbox/cmake_build
#   ctest --test-dir test/blackbox/cmake_build --output-on-failure
#   ctest --test-dir test/blackbox/cmake_build -L scenarios     # only goldens
#
# Regenerate goldens after an intentional change (review the diff first):
#   GENERATE=1 ctest --test-dir test/blackbox/cmake_build -L scenarios
#
cmake_minimum_required(VERSION 3.16)
project(reuse_pred_blackbox NONE)
enable_testing()

get_filename_component(SRC_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
set(RUNNER  "${CMAKE_CURRENT_SOURCE_DIR}/run_scenario.sh")
set(ORDERER "${CMAKE_CURRENT_SOURCE_DIR}/assert_order.sh")
set(OUT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/test_outputs")

# A scenario test: run the binary and golden-diff the full report.
# Exit code 77 (binary/trace missing) is reported as "skipped", not failed.
function(cs_test name)
  add_test(NAME ${name} COMMAND bash ${RUNNER} ${name})
  set_tests_properties(${name} PROPERTIES
    LABELS "scenarios"
    TIMEOUT 300
    SKIP_RETURN_CODE 77
    ENVIRONMENT "SRC_ROOT=${SRC_ROOT};OUTPUT_DIR=${OUT_DIR}")
endfunction()

# An invariant test: assert an IPC ordering between two scenarios.
function(cs_order name a op b)
  add_test(NAME ${name} COMMAND bash ${ORDERER} ${a} ${op} ${b})
  set_tests_properties(${name} PROPERTIES
    LABELS "invariants"
    TIMEOUT 300
    SKIP_RETURN_CODE 77
    ENVIRONMENT "SRC_ROOT=${SRC_ROOT};OUTPUT_DIR=${OUT_DIR}")
endfunction()

# ---- golden scenarios ----
cs_test(lru_default)
cs_test(lru_2n3)
cs_test(lru_lru)
cs_test(lru_bypass)
cs_test(lru_bypass_off)
cs_test(lru_duel_hits)
cs_test(lru_duel_lat_hyst)
cs_test(lru_cap256)

cs_test(srrip_default)
cs_test(srrip_mode3)
cs_test(srrip_mode4)
cs_test(srrip_mode5)
cs_test(srrip_mode7)
cs_test(srrip_mode8)
cs_test(srrip_cap256)
cs_test(srrip_duel_cfg0)

cs_test(ipv_default)
cs_test(ipv_canonical)
cs_test(ipv_ins3_comma)
cs_test(ipv_ins3_colon)
cs_test(ipv_cap256)

cs_test(duel_ipv_cfg0_ins2)
cs_test(duel_ipv_cfg0_ins3)
cs_test(duel_ipv_3way)

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
