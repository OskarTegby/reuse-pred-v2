cmake_minimum_required(VERSION 3.16)
project(reuse_pred_blackbox NONE)
enable_testing()

get_filename_component(SRC_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)
set(RUNNER  "${CMAKE_CURRENT_SOURCE_DIR}/run_scenario.sh")
set(ORDERER "${CMAKE_CURRENT_SOURCE_DIR}/assert_order.sh")
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

function(cs_order name a op b)
  add_test(NAME ${name} COMMAND bash ${ORDERER} ${a} ${op} ${b})
  set_tests_properties(${name} PROPERTIES
    TIMEOUT 1800 SKIP_RETURN_CODE 77
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
cs_order(inv_bypass_beats_2n3   lru_bypass     gt lru_2n3)
cs_order(inv_lru_beats_2n3      lru_lru        gt lru_2n3)
cs_order(inv_ins3_beats_ins2    ipv_ins3_comma gt ipv_canonical)
cs_order(inv_duel_follower_conv duel_ipv_cfg0_ins3 gt duel_ipv_cfg0_ins2)
