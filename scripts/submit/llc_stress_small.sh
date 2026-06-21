#!/bin/bash
set -euo pipefail
# LLC history table stress test: very small capacities (buf=0).
#
# Design: STLB unbounded liveness (STLB_MID_THD=1), LLC table swept {8,32,64,128}
# with NO promotion buffer (REPL_HIST_BUF_CAP not set → buf=0).
#
# Proper baseline: SRRIP_LIVE_TARGET=stlb — STLB guided + LLC plain SRRIP
# (use_liveness=false → mostly_alive → SRRIP). This is the zero-LLC-contribution
# reference. As the LLC cap shrinks, the test points converge to this baseline
# and the speedup vs this baseline should approach zero.
#
# LRU + plain SRRIP baselines reused from qmm_thd_rebaseline_20260604_2307.
BASE=~/ChampSim-dev
TRACES="$BASE/trace-files/QMM"; EXT="champsimtrace.xz"
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="qmm_llc_stress_${DATE}"
BOTH_COMMON="BHIST_MODE=pc,SRRIP_LIVE_TARGET=both,LLC_MID_THD=4,STLB_MID_THD=1"
STLB_ONLY="BHIST_MODE=pc,SRRIP_LIVE_TARGET=stlb,STLB_MID_THD=1"

submit() {
  local label="$1" binary="$2" jobname="$3"; shift 3
  mkdir -p "$BASE/results/$label" "$BASE/logs/$label"
  local jid=$(qsub -t 1-45 -N "$jobname" \
       -o "$BASE/logs/$label/" -e "$BASE/logs/$label/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "$BASE" \
       -v WARMUP=$W,SIM=$S,TRACE_DIR="$TRACES",TRACE_EXT="$EXT",\
RUN_LABEL="$label",BINARY="$binary",$* \
       "$BASE/scripts/submit/run_cs.sh" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=$jid] $label"
}

# Baseline: STLB fully guided + LLC plain SRRIP (use_liveness=false → mostly_alive).
# This is the zero-LLC-contribution reference. Cap runs are compared against this;
# at cap→0 the speedup should converge to 0 (not to plain SRRIP which would include
# STLB contribution).
echo "--- Baseline: STLB guided + LLC SRRIP ---"
submit "$LABEL/stlb_only_baseline" champsim_both_srrip_live "lss_base" \
  "$STLB_ONLY"

echo "--- LLC stress: STLB guided + LLC liveness at varying cap ---"
for cap in 8 32 64 128; do
  submit "$LABEL/cap${cap}" champsim_both_srrip_live "lss_${cap}" \
    "REPL_HIST_LLC_CAP=${cap},$BOTH_COMMON"
done

echo ""
echo "Submitted: 5 arrays x 45 traces = 225 jobs"
echo "Label: $LABEL"
