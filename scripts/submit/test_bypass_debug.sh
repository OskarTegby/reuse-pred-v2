#!/usr/bin/env bash
set -euo pipefail
# test_bypass_debug.sh — Bypass debug run on 5 QMM traces.
#
# The DoA score IS the bypass confidence counter. Bypass fires when score >= BYPASS_THD.
# Setting BYPASS_THD > THD_DOA means a PC must accumulate more evidence before bypassing
# starts; it cannot bypass on its first DoA classification.
#
# Configs:
#   repl_only     : SRRIP-Live, no bypass (replacement benefit only, reference)
#   bypass_thd4   : BYPASS_THD=4  (same as THD_DOA — bypass on first DoA classification)
#   bypass_thd8   : BYPASS_THD=8  (2× THD_DOA — need 2 consecutive DoA confirmations)
#   bypass_thd16  : BYPASS_THD=16 (4× THD_DOA)
#   bypass_thd32  : BYPASS_THD=32 (8× THD_DOA)
#
# SRRIP baseline already in: qmm_thd_rebaseline_20260605_2316/srrip
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

echo "=== Bypass debug: QMM ${N} traces ==="
echo "Label: $LABEL"
echo ""

echo "--- Replacement only (no bypass, reference) ---"
submit "$LABEL/repl_only" champsim_srrip_live_hrp "bp_ref" \
  "$COMMON"

echo "--- Bypass BYPASS_THD=4 (= THD_DOA, bypass on first DoA classification) ---"
submit "$LABEL/bypass_thd4" champsim_srrip_live_hrp "bp_t4" \
  "$COMMON,LIVENESS_BYPASS=1,BYPASS_THD=4"

echo "--- Bypass BYPASS_THD=8 ---"
submit "$LABEL/bypass_thd8" champsim_srrip_live_hrp "bp_t8" \
  "$COMMON,LIVENESS_BYPASS=1,BYPASS_THD=8"

echo "--- Bypass BYPASS_THD=16 ---"
submit "$LABEL/bypass_thd16" champsim_srrip_live_hrp "bp_t16" \
  "$COMMON,LIVENESS_BYPASS=1,BYPASS_THD=16"

echo "--- Bypass BYPASS_THD=32 ---"
submit "$LABEL/bypass_thd32" champsim_srrip_live_hrp "bp_t32" \
  "$COMMON,LIVENESS_BYPASS=1,BYPASS_THD=32"

echo ""
echo "Submitted: 5 configs x ${N} traces = $((5 * N)) tasks"
echo "Results:   $BASE/results/$LABEL/"
echo ""
echo "SRRIP baseline: qmm_thd_rebaseline_20260605_2316/srrip"
