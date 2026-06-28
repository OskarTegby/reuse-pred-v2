cmake_minimum_required(VERSION 3.16)
project(reuse_pred_blackbox NONE)
enable_testing()

get_filename_component(SRC_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
set(RUNNER  "${CMAKE_CURRENT_SOURCE_DIR}/run_scenario.sh")
set(OUT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/test_outputs")
set(ENV_COMMON "SRC_ROOT=${SRC_ROOT};OUTPUT_DIR=${OUT_DIR}")

# 50M warmup + 100M sim per scenario (~8 min each).
# Exit 77 (binary/trace missing) is reported as skipped, not failed.
function(cs_scenario name)
  add_test(NAME ${name} COMMAND bash ${RUNNER} ${name})
  set_tests_properties(${name} PROPERTIES
    TIMEOUT 900 SKIP_RETURN_CODE 77
    ENVIRONMENT "${ENV_COMMON}")
endfunction()

# ---- scenarios (policy x condition x trace) ----
# run_scenario.sh --list is the single source of truth; keep this in lockstep.
execute_process(
  COMMAND bash ${RUNNER} --list
  OUTPUT_VARIABLE SCENARIO_LIST
  OUTPUT_STRIP_TRAILING_WHITESPACE)
string(REPLACE "\n" ";" SCENARIOS "${SCENARIO_LIST}")
foreach(scen ${SCENARIOS})
  cs_scenario(${scen})
endforeach()
