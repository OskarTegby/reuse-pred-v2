#!/usr/bin/env bash
#
# Black-box scenario runner for the liveness replacement policies. A scenario
# is <policy>_<condition>_<trace>; see README for what each axis covers and
# why these particular traces were picked.
#
#   Usage: run_scenario.sh <scenario>            # run + compare
#          GENERATE=1 run_scenario.sh <scenario> # write reference output
#          run_scenario.sh --list                # print every scenario name
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${SRC_ROOT:-$(cd "$HERE/../.." && pwd)}"
BIN_DIR="${BIN_DIR:-$ROOT/bin}"
EXPECTED_DIR="$HERE/expected"
OUT_DIR="${OUTPUT_DIR:-$HERE/test_outputs}"
WARMUP="${WARMUP:-50000000}"
SIM="${SIM:-100000000}"
DPC3=/home/users/shared/traces/dpc3_traces

POLICIES=(lru srrip ipv)
CONDITIONS=(base fixed bypass duel addr)
TRACE_KEYS=(pr cactus bwaves qmm)

trace_path() {
  case "$1" in
    pr)     echo "$ROOT/trace-files/ligra/ligra_PageRank.com-lj.ungraph.gcc_6.3.0_O3.drop_51000M.length_250M.champsimtrace.xz" ;;
    cactus) echo "$DPC3/607.cactuBSSN_s-3477B.champsimtrace.xz" ;;
    bwaves) echo "$DPC3/603.bwaves_s-891B.champsimtrace.xz" ;;
    qmm)    echo "$ROOT/trace-files/QMM/srv_12.champsimtrace.xz" ;;
    *) return 1 ;;
  esac
}

list_scenarios() {
  for p in "${POLICIES[@]}"; do for c in "${CONDITIONS[@]}"; do
    for t in "${TRACE_KEYS[@]}"; do echo "${p}_${c}_${t}"; done
  done; done
}

parse_scenario() {
  IFS=_ read -r POL COND TRC <<< "$1"
}

build_env_fragments() {
  BASE_ENV=(THD_DOA=6 BHIST_MODE=pc SRRIP_LIVE_TARGET=llc)
  ADDR_ENV=(REPL_HIST_MODE=addr REPL_HIST_LLC_CAP=4096 REPL_HIST_REPL=lfu_doa)
  # LRU-Live expresses bypass as an insertion mode instead; see resolve_lru_env.
  BYPASS_ENV=("${BASE_ENV[@]/SRRIP_LIVE_TARGET=llc/SRRIP_LIVE_TARGET=none}" LIVENESS_BYPASS=1)
  IPV_VEC=(IPV_DOA=0:1:2:2:3)
}

resolve_lru_env() {
  local cond="$1" scen="$2"
  case "$cond" in
    base)   BIN=champsim_lru ;;
    fixed)  BIN=champsim_lru_live; ENVV=("${BASE_ENV[@]}" LRU_LIVE_DOA_INS=2n3) ;;
    bypass) BIN=champsim_lru_live; ENVV=("${BASE_ENV[@]}" LRU_LIVE_DOA_INS=bypass) ;;
    duel)   BIN=champsim_lru_live; ENVV=("${BASE_ENV[@]}" LRU_LIVE_DOA_INS=2n3 LRU_LIVE_DOA_INS_B=lru DUEL_N_SAMPLERS=32 DUEL_METRIC=latency) ;;
    addr)   BIN=champsim_lru_live; ENVV=("${BASE_ENV[@]}" LRU_LIVE_DOA_INS=2n3 "${ADDR_ENV[@]}") ;;
    *) echo "run_scenario.sh: unknown scenario '$scen'" >&2; exit 2 ;;
  esac
}

resolve_srrip_env() {
  local cond="$1" scen="$2"
  case "$cond" in
    base)   BIN=champsim_srrip ;;
    fixed)  BIN=champsim_srrip_live; ENVV=("${BASE_ENV[@]}") ;;
    bypass) BIN=champsim_srrip_live; ENVV=("${BYPASS_ENV[@]}") ;;
    duel)   BIN=champsim_srrip_live; ENVV=("${BASE_ENV[@]}" SRRIP_DOA_INS_RRPV=2 SRRIP_DOA_HIT_RRPV=2 SRRIP_DOA_INS_RRPV_B=3 SRRIP_DOA_HIT_RRPV_B=0 DUEL_N_SAMPLERS=32) ;;
    addr)   BIN=champsim_srrip_live; ENVV=("${BASE_ENV[@]}" "${ADDR_ENV[@]}") ;;
    *) echo "run_scenario.sh: unknown scenario '$scen'" >&2; exit 2 ;;
  esac
}

resolve_ipv_env() {
  local cond="$1" scen="$2"
  case "$cond" in
    base)   BIN=champsim_ipv ;;
    fixed)  BIN=champsim_ipv_live; ENVV=("${BASE_ENV[@]}" "${IPV_VEC[@]}") ;;
    bypass) BIN=champsim_ipv_live; ENVV=("${BYPASS_ENV[@]}" "${IPV_VEC[@]}") ;;
    duel)   BIN=champsim_ipv_live; ENVV=("${BASE_ENV[@]}" DUEL_N_CONFIGS=2 DUEL_N_SAMPLERS=32 IPV_DOA_0=0:1:2:2:2 IPV_DOA_1=0:1:2:2:3 DUEL_METRIC=latency) ;;
    addr)   BIN=champsim_ipv_live; ENVV=("${BASE_ENV[@]}" "${IPV_VEC[@]}" "${ADDR_ENV[@]}") ;;
    *) echo "run_scenario.sh: unknown scenario '$scen'" >&2; exit 2 ;;
  esac
}

resolve_binary_and_env() {
  local pol="$1" cond="$2" scen="$3"
  build_env_fragments
  ENVV=()
  case "$pol" in
    lru)   resolve_lru_env   "$cond" "$scen" ;;
    srrip) resolve_srrip_env "$cond" "$scen" ;;
    ipv)   resolve_ipv_env   "$cond" "$scen" ;;
    *) echo "run_scenario.sh: unknown scenario '$scen'" >&2; exit 2 ;;
  esac
}

# 77 is ctest's SKIP_RETURN_CODE (see CMakeLists.txt).
check_prereqs() {
  local bin_path="$1" trace="$2" scen="$3"
  [ -x "$bin_path" ] || { echo "SKIP $scen: binary not found: $bin_path" >&2; exit 77; }
  [ -f "$trace" ]    || { echo "SKIP $scen: trace not found: $trace"    >&2; exit 77; }
}

run_binary() {
  local bin_path="$1" trace="$2" actual="$3"
  # ${ENVV[@]+...}: expanding an empty array under `set -u` fails on bash < 4.4
  # (the cluster), which the `base` condition (empty ENVV) would hit.
  # sed -u: without line buffering, `actual` stays empty until the process
  # exits, breaking check_progress.sh's incremental verification.
  env ${ENVV[@]+"${ENVV[@]}"} "$bin_path" \
      --warmup_instructions "$WARMUP" --simulation_instructions "$SIM" "$trace" 2>&1 \
    | sed -u -E 's/ \(Simulation time: [0-9]+ hr [0-9]+ min [0-9]+ sec\)//' \
    > "$actual"
}

write_reference() {
  local actual="$1" reference="$2"
  cp "$actual" "$reference"
  echo "REFERENCE WRITTEN (no comparison): $reference"
}

compare_to_reference() {
  local actual="$1" reference="$2" scen="$3"
  if [ ! -f "$reference" ]; then
    echo "FAIL $scen: no reference file ($reference). Run with GENERATE=1 to create it." >&2
    exit 1
  fi
  if diff -u "$reference" "$actual"; then
    echo "PASS $scen"
  else
    echo "FAIL $scen: output diverged from reference" >&2
    exit 1
  fi
}

main() {
  if [ "${1:-}" = "--list" ]; then
    list_scenarios
    exit 0
  fi

  local scen="${1:?usage: run_scenario.sh <policy>_<condition>_<trace>  (or --list)}"
  parse_scenario "$scen"

  local trace
  trace="${TRACE:-$(trace_path "$TRC")}" || { echo "unknown trace key in '$scen'" >&2; exit 2; }

  resolve_binary_and_env "$POL" "$COND" "$scen"

  local bin_path="$BIN_DIR/$BIN"
  check_prereqs "$bin_path" "$trace" "$scen"

  mkdir -p "$OUT_DIR" "$EXPECTED_DIR"
  local actual="$OUT_DIR/$scen.out"
  local reference="$EXPECTED_DIR/$scen.out"

  run_binary "$bin_path" "$trace" "$actual"

  if [ "${GENERATE:-0}" = "1" ]; then
    write_reference "$actual" "$reference"
    exit 0
  fi

  compare_to_reference "$actual" "$reference" "$scen"
}

main "$@"
