#!/usr/bin/env bash
#
# Black-box scenario runner for the liveness replacement policies.
#
#   Usage: run_scenario.sh <scenario>            # run + compare
#          GENERATE=1 run_scenario.sh <scenario> # write reference output
#          run_scenario.sh --list                # print every scenario name
#
# A scenario is  <policy>_<condition>_<trace>  and names a binary + environment,
# run on one real trace (50M warmup + 100M sim). The runner captures the entire
# ChampSim report, strips the one nondeterministic wall-clock line, and
# byte-compares it against test/blackbox/expected/<scenario>.out.
#
# Design (see README): instead of isolating one knob on a synthetic trace, the
# matrix exercises every mechanism we developed AND kept, on workloads where
# that mechanism is actually active:
#
#   policies   : lru / srrip / ipv          (the three liveness policies)
#   conditions : base   - the non-liveness baseline policy (own reference point)
#                fixed  - liveness, single fixed insertion config (no dueling)
#                bypass - liveness with DoA blocks bypassing the LLC
#                duel   - liveness with set dueling (each policy's kept metric)
#                addr   - liveness with per-ADDRESS history indexing (bounded 4K,
#                         lfu_doa eviction) -- guards the per-address ablation used
#                         in the paper and the bounded-table eviction path
#   traces     : pr     - ligra PageRank      (graph DoA; bypass + aggressive arm)
#                cactus - 607.cactuBSSN_s-3477B (many PCs -> history table active;
#                                               temporal reuse -> gentle arm wins,
#                                               cfgA by +55%; faster slice than 2421B)
#                bwaves - 603.bwaves           (streaming -> bypass; ~4x faster to
#                                               simulate than lbm, same coverage)
#                qmm    - srv_12               (many PCs, different workload)
#
# Determinism makes the full-report reference sufficient: any change to winner
# selection, tier classification, or eviction moves some counter and the diff
# catches it -- no separate winner-flip / threshold / eviction asserts needed.
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

# --- trace key -> path --------------------------------------------------------
trace_path() {
  case "$1" in
    pr)     echo "$ROOT/trace-files/ligra/ligra_PageRank.com-lj.ungraph.gcc_6.3.0_O3.drop_51000M.length_250M.champsimtrace.xz" ;;
    cactus) echo "$DPC3/607.cactuBSSN_s-3477B.champsimtrace.xz" ;;
    bwaves) echo "$DPC3/603.bwaves_s-891B.champsimtrace.xz" ;;
    qmm)    echo "$ROOT/trace-files/QMM/srv_12.champsimtrace.xz" ;;
    *) return 1 ;;
  esac
}

# --- emit every scenario name: <policy>_<condition>_<trace> ------------------
# The single source of truth: CMakeLists.txt and the cluster drivers all call
# this (via --list) instead of defining the matrix themselves.
list_scenarios() {
  for p in "${POLICIES[@]}"; do for c in "${CONDITIONS[@]}"; do
    for t in "${TRACE_KEYS[@]}"; do echo "${p}_${c}_${t}"; done
  done; done
}

# --- split "<policy>_<condition>_<trace>" into the POL/COND/TRC globals ------
parse_scenario() {
  IFS=_ read -r POL COND TRC <<< "$1"
}

# --- shared env-var fragments, reused across several (policy,condition) cells
# Sets the globals BASE_ENV / ADDR_ENV / BYPASS_ENV / IPV_VEC, consumed by the
# per-policy resolvers below.
build_env_fragments() {
  # liveness base shared by every non-baseline condition
  BASE_ENV=(THD_DOA=6 BHIST_MODE=pc SRRIP_LIVE_TARGET=llc)
  # 'addr' condition: address-keyed history table, bounded to 4K with lfu_doa eviction.
  ADDR_ENV=(REPL_HIST_MODE=addr REPL_HIST_LLC_CAP=4096 REPL_HIST_REPL=lfu_doa)
  # 'bypass' for SRRIP/IPV-Live: DoA blocks skip the LLC instead of being inserted.
  # SRRIP_LIVE_TARGET=none turns off the in-cache liveness insert (so we flip it out
  # of BASE_ENV) and LIVENESS_BYPASS=1 enables the bypass path. (LRU-Live expresses
  # bypass differently, as the LRU_LIVE_DOA_INS=bypass insertion mode.)
  BYPASS_ENV=("${BASE_ENV[@]/SRRIP_LIVE_TARGET=llc/SRRIP_LIVE_TARGET=none}" LIVENESS_BYPASS=1)
  # IPV-Live's kept "ilB" insertion vector.
  IPV_VEC=(IPV_DOA=0:1:2:2:3)
}

# -------- LRU-Live (bypass is an insertion mode; duel = latency metric) -----
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

# -------- SRRIP-Live (bypass via TARGET=none; duel = hit-count/PSEL) --------
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

# -------- IPV-Live (ilB fixed; duel = ins2-vs-ins3, latency metric) ---------
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

# --- (policy, condition) -> binary + env --------------------------------------
# Sets the globals BIN and ENVV by dispatching to the matching per-policy
# resolver above.
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

# --- bail out (exit 77 = ctest "skipped") if the binary or trace is missing --
check_prereqs() {
  local bin_path="$1" trace="$2" scen="$3"
  [ -x "$bin_path" ] || { echo "SKIP $scen: binary not found: $bin_path" >&2; exit 77; }
  [ -f "$trace" ]    || { echo "SKIP $scen: trace not found: $trace"    >&2; exit 77; }
}

# --- run the binary under ENVV, writing the stripped report to `actual` ------
# ${ENVV[@]+...} guard: expanding an empty array under `set -u` errors on
# bash < 4.4 (the cluster), which the `base` condition (no env) would trip.
# sed -u (line-buffered) is required, not cosmetic: ChampSim flushes every
# heartbeat (std::endl), but without -u sed block-buffers its writes, so the
# output file stays empty mid-run and incremental verification (check_progress.sh)
# sees no progress until the process exits. -u streams each stripped line to the
# file as it is produced. Output content is identical either way.
run_binary() {
  local bin_path="$1" trace="$2" actual="$3"
  env ${ENVV[@]+"${ENVV[@]}"} "$bin_path" \
      --warmup_instructions "$WARMUP" --simulation_instructions "$SIM" "$trace" 2>&1 \
    | sed -u -E 's/ \(Simulation time: [0-9]+ hr [0-9]+ min [0-9]+ sec\)//' \
    > "$actual"
}

# --- GENERATE=1: snapshot `actual` as the new reference, no comparison ------
write_reference() {
  local actual="$1" reference="$2"
  cp "$actual" "$reference"
  echo "REFERENCE WRITTEN (no comparison): $reference"
}

# --- compare `actual` against `reference`; exit 1 with a diff on mismatch ---
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
