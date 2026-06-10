#!/usr/bin/env bash
set -euo pipefail
# test_bypass_debug.sh — Bypass probe debug run on 5 QMM traces.
#
# Tests bypass with K-probe mechanism on top of SRRIP-Live (LLC only, unbounded).
# Scoring mode: SCORING_MODE=3, THD_DEAD=2, THD_DOA=4 (same as size study).
# K-bypass probe: BYPASS_K=0 (always bypass), 4, 8, 16, 32.
#
# Configs:
#   repl_only  : SRRIP-Live, no bypass (replacement benefit only, reference)
#   bypass_k0  : LIVENESS_BYPASS=1, BYPASS_K=0 (no probe — starvation risk)
#   bypass_k4  : LIVENESS_BYPASS=1, BYPASS_K=4
#   bypass_k8  : LIVENESS_BYPASS=1, BYPASS_K=8
#   bypass_k16 : LIVENESS_BYPASS=1, BYPASS_K=16
#   bypass_k32 : LIVENESS_BYPASS=1, BYPASS_K=32
#
# SRRIP baseline (REPL_HIST_LLC_CAP=0) already in:
#   qmm_thd_rebaseline_20260605_2316/srrip  (45 traces)
#
# Usage: bash test_bypass_debug.sh
BASE=~/ChampSim-dev
TRACES="$BASE/trace-files/QMM"; EXT="champsimtrace.xz"
W=50000000; S=100000000
N=5  # first 5 QMM traces only
DATE=$(date +%Y%m%d_%H%M)
LABEL="qmm_bypass_debug_${DATE}"

COMMON="BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,SCORING_MODE=3,THD_DEAD=2,THD_DOA=4"

submit() {
  local label="$1" binary="$2" jobname="$3"; shift 3
  mkdir -p "$BASE/results/$label" "$BASE/logs/$label"
  local jid
  jid=$(qsub -t "1-${N}" -N "$jobname" \
       -o "$BASE/logs/$label/" -e "$BASE/logs/$label/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "$BASE" \
       -v WARMUP=$W,SIM=$S,TRACE_DIR="$TRACES",TRACE_EXT="$EXT",\
RUN_LABEL="$label",BINARY="$binary",$* \
       "$BASE/scripts/submit/run_cs.sh" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=$jid] $label"
}

echo "=== Bypass probe debug: QMM ${N} traces ==="
echo "Label: $LABEL"
echo ""

echo "--- Replacement only (no bypass, reference) ---"
submit "$LABEL/repl_only" champsim_srrip_live_hrp "bp_ref" \
  "$COMMON"

echo "--- Bypass K=0 (always bypass when DoA, no probe) ---"
submit "$LABEL/bypass_k0" champsim_srrip_live_hrp "bp_k0" \
  "$COMMON,LIVENESS_BYPASS=1,BYPASS_K=0"

echo "--- Bypass K=4 ---"
submit "$LABEL/bypass_k4" champsim_srrip_live_hrp "bp_k4" \
  "$COMMON,LIVENESS_BYPASS=1,BYPASS_K=4"

echo "--- Bypass K=8 ---"
submit "$LABEL/bypass_k8" champsim_srrip_live_hrp "bp_k8" \
  "$COMMON,LIVENESS_BYPASS=1,BYPASS_K=8"

echo "--- Bypass K=16 ---"
submit "$LABEL/bypass_k16" champsim_srrip_live_hrp "bp_k16" \
  "$COMMON,LIVENESS_BYPASS=1,BYPASS_K=16"

echo "--- Bypass K=32 ---"
submit "$LABEL/bypass_k32" champsim_srrip_live_hrp "bp_k32" \
  "$COMMON,LIVENESS_BYPASS=1,BYPASS_K=32"

echo ""
echo "Submitted: 6 configs x ${N} traces = $((6 * N)) tasks"
echo "Results:   $BASE/results/$LABEL/"
echo ""
echo "SRRIP baseline: qmm_thd_rebaseline_20260605_2316/srrip (45 traces, use first 5)"
