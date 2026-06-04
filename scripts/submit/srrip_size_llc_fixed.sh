#!/bin/bash
set -euo pipefail
# SRRIP-Live LLC-only history-table size study, FIXED binary (write-hit guard removed).
# buf=128, sweep LLC history table from 4096 down to 128, plus unbounded reference.
# Baseline: plain SRRIP (== srrip_live cap=0 buf=0 after the fix) and LRU.
BASE=~/ChampSim-dev
TRACES="$BASE/trace-files/QMM"; EXT="champsimtrace.xz"
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="qmm_srrip_size_llc_fixed_${DATE}"

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

COMMON="MID_THD=4,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,REPL_HIST_BUF_CAP=128,REPL_HIST_REPL=lfu_doa"

echo "=== SRRIP-Live LLC size study (fixed binary, buf=128) ($DATE) ==="
echo "--- Baselines ---"
submit "$LABEL/lru"   champsim_lru   "sf_lru"
submit "$LABEL/srrip" champsim_srrip "sf_srrip"

echo "--- SRRIP-Live, sweep 4096 -> 128 ---"
for cap in 4096 2048 1024 512 256 128; do
  submit "$LABEL/cap${cap}" champsim_srrip_live "sf_${cap}" "${COMMON},REPL_HIST_LLC_CAP=${cap}"
done
submit "$LABEL/unbounded" champsim_srrip_live "sf_ub" "MID_THD=4,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"

echo ""
echo "Submitted: 9 arrays x 45 traces = 405 jobs"
echo "Label: $LABEL"
