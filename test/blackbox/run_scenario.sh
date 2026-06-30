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
#   traces     : pr     - ligra PageRank      (graph DoA; bypass + aggressive arm)
#                cactus - 607.cactuBSSN        (many PCs -> history table active;
#                                               temporal reuse -> gentle arm wins)
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
CONDITIONS=(base fixed bypass duel)
TRACE_KEYS=(pr cactus bwaves qmm)

# --- trace key -> path + that trace's per-suite mostly-dead threshold ---------
trace_path() {
  case "$1" in
    pr)     echo "$ROOT/trace-files/ligra/ligra_PageRank.com-lj.ungraph.gcc_6.3.0_O3.drop_51000M.length_250M.champsimtrace.xz" ;;
    cactus) echo "$DPC3/607.cactuBSSN_s-2421B.champsimtrace.xz" ;;
    bwaves) echo "$DPC3/603.bwaves_s-891B.champsimtrace.xz" ;;
    qmm)    echo "$ROOT/trace-files/QMM/srv_12.champsimtrace.xz" ;;
    *) return 1 ;;
  esac
}
trace_dead() {            # per-suite THD_DEAD, matches the cluster sweeps
  case "$1" in
    pr) echo 16 ;; cactus|bwaves) echo 4 ;; qmm) echo 2 ;; *) return 1 ;;
  esac
}

# --- emit the full scenario list (single source of truth) --------------------
if [ "${1:-}" = "--list" ]; then
  for p in "${POLICIES[@]}"; do for c in "${CONDITIONS[@]}"; do
    for t in "${TRACE_KEYS[@]}"; do echo "${p}_${c}_${t}"; done
  done; done
  exit 0
fi

SCEN="${1:?usage: run_scenario.sh <policy>_<condition>_<trace>  (or --list)}"
IFS=_ read -r POL COND TRC <<< "$SCEN"

TRACE="${TRACE:-$(trace_path "$TRC")}" || { echo "unknown trace key in '$SCEN'" >&2; exit 2; }
DEAD="$(trace_dead "$TRC")"            || { echo "unknown trace key in '$SCEN'" >&2; exit 2; }

# liveness base shared by every non-baseline condition
BASE_ENV=(SCORING_MODE=5 THD_DOA=6 "THD_DEAD=$DEAD" BHIST_MODE=pc SRRIP_LIVE_TARGET=llc)

# --- (policy, condition) -> binary + env -------------------------------------
ENVV=()
case "${POL}_${COND}" in
  # -------- LRU-Live (bypass is an insertion mode; duel = latency metric) -----
  lru_base)    BIN=champsim_lru ;;
  lru_fixed)   BIN=champsim_lru_live; ENVV=("${BASE_ENV[@]}" LRU_LIVE_DOA_INS=2n3) ;;
  lru_bypass)  BIN=champsim_lru_live; ENVV=("${BASE_ENV[@]}" LRU_LIVE_DOA_INS=bypass) ;;
  lru_duel)    BIN=champsim_lru_live; ENVV=("${BASE_ENV[@]}" LRU_LIVE_DOA_INS=2n3 LRU_LIVE_DOA_INS_B=lru DUEL_N_SAMPLERS=32 DUEL_METRIC=latency) ;;

  # -------- SRRIP-Live (bypass via TARGET=none; duel = hit-count/PSEL) --------
  srrip_base)   BIN=champsim_srrip ;;
  srrip_fixed)  BIN=champsim_srrip_live; ENVV=("${BASE_ENV[@]}") ;;
  srrip_bypass) BIN=champsim_srrip_live; ENVV=("${BASE_ENV[@]/SRRIP_LIVE_TARGET=llc/SRRIP_LIVE_TARGET=none}" LIVENESS_BYPASS=1) ;;
  srrip_duel)   BIN=champsim_srrip_live; ENVV=("${BASE_ENV[@]}" SRRIP_DOA_INS_RRPV=2 SRRIP_DOA_HIT_RRPV=2 SRRIP_DOA_INS_RRPV_B=3 SRRIP_DOA_HIT_RRPV_B=0 DUEL_N_SAMPLERS=32) ;;

  # -------- IPV-Live (ilB fixed; duel = ins2-vs-ins3, latency metric) ---------
  ipv_base)    BIN=champsim_ipv ;;
  ipv_fixed)   BIN=champsim_ipv_live; ENVV=("${BASE_ENV[@]}" IPV_DOA=0:1:2:2:3 IPV_MOSTLY_DEAD=0:1:1:2:2) ;;
  ipv_bypass)  BIN=champsim_ipv_live; ENVV=("${BASE_ENV[@]/SRRIP_LIVE_TARGET=llc/SRRIP_LIVE_TARGET=none}" LIVENESS_BYPASS=1 IPV_DOA=0:1:2:2:3 IPV_MOSTLY_DEAD=0:1:1:2:2) ;;
  ipv_duel)    BIN=champsim_ipv_live; ENVV=("${BASE_ENV[@]}" DUEL_N_CONFIGS=2 DUEL_N_SAMPLERS=32 IPV_DOA_0=0:1:2:2:2 IPV_DOA_1=0:1:2:2:3 IPV_MOSTLY_DEAD=0:1:1:2:2 DUEL_METRIC=latency) ;;

  *) echo "run_scenario.sh: unknown scenario '$SCEN'" >&2; exit 2 ;;
esac

BIN_PATH="$BIN_DIR/$BIN"
[ -x "$BIN_PATH" ] || { echo "SKIP $SCEN: binary not found: $BIN_PATH" >&2; exit 77; }
[ -f "$TRACE" ]    || { echo "SKIP $SCEN: trace not found: $TRACE"       >&2; exit 77; }

mkdir -p "$OUT_DIR" "$EXPECTED_DIR"
ACTUAL="$OUT_DIR/$SCEN.out"
REFERENCE="$EXPECTED_DIR/$SCEN.out"

# ${ENVV[@]+...} guard: expanding an empty array under `set -u` errors on
# bash < 4.4 (the cluster), which the `base` condition (no env) would trip.
# sed -u (line-buffered) is required, not cosmetic: ChampSim flushes every
# heartbeat (std::endl), but without -u sed block-buffers its writes, so the
# output file stays empty mid-run and incremental verification (check_progress.sh)
# sees no progress until the process exits. -u streams each stripped line to the
# file as it is produced. Output content is identical either way.
env ${ENVV[@]+"${ENVV[@]}"} "$BIN_PATH" \
    --warmup_instructions "$WARMUP" --simulation_instructions "$SIM" "$TRACE" 2>&1 \
  | sed -u -E 's/ \(Simulation time: [0-9]+ hr [0-9]+ min [0-9]+ sec\)//' \
  > "$ACTUAL"

if [ "${GENERATE:-0}" = "1" ]; then
  cp "$ACTUAL" "$REFERENCE"
  echo "REFERENCE WRITTEN (no comparison): $REFERENCE"
  exit 0
fi

if [ ! -f "$REFERENCE" ]; then
  echo "FAIL $SCEN: no reference file ($REFERENCE). Run with GENERATE=1 to create it." >&2
  exit 1
fi

if diff -u "$REFERENCE" "$ACTUAL"; then
  echo "PASS $SCEN"
else
  echo "FAIL $SCEN: output diverged from reference" >&2
  exit 1
fi
