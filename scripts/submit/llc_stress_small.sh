#!/bin/bash
set -euo pipefail
# LLC history table stress test: very small capacities (buf=0) to verify that
# performance converges to plain SRRIP as the table shrinks to near-zero.
#
# Design: STLB unbounded, LLC table swept {1..128} with NO promotion buffer
# (REPL_HIST_BUF_CAP not set → buf=0). buf=0 is essential here: with buf=128
# even cap=4 would have effective capacity 132, masking the degradation.
#
# Expected: at cap=1..2 classify() finds no history for almost every PC and
# returns mostly_alive (the default), which is identical to SRRIP. The geomean
# should converge to the SRRIP baseline (+0.00% vs SRRIP).
#
# Baselines (LRU, SRRIP) reused from qmm_thd_rebaseline_20260604_2307.
BASE=~/ChampSim-dev
TRACES="$BASE/trace-files/QMM"; EXT="champsimtrace.xz"
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="qmm_llc_stress_${DATE}"
COMMON="BHIST_MODE=pc,SRRIP_LIVE_TARGET=both,LLC_MID_THD=4,STLB_MID_THD=1"

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

echo "--- LLC stress (SRRIP-Live, buf=0, STLB unbounded) ---"
for cap in 8 32 64 128; do
  submit "$LABEL/cap${cap}" champsim_both_srrip_live "lss_${cap}" \
    "REPL_HIST_LLC_CAP=${cap},$COMMON"
done

echo ""
echo "Submitted: 4 arrays x 45 traces = 180 jobs"
echo "Label: $LABEL"
