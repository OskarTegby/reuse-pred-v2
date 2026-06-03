#!/bin/bash
set -euo pipefail

# Promotion buffer size sweep: history table sizes fixed at small values to put
# genuine pressure on the promotion buffer (LLC=256, STLB=256 — past the knee
# in the STLB size study). Buffer size varied jointly from 0 to 128.
# Policy: IPV-Live, per-level optimal thresholds.
# Goal: quantify how much the promotion buffer contributes under real pressure.

BASE=~/ChampSim-dev
TRACES="$BASE/trace-files/QMM"; EXT="champsimtrace.xz"
W=${WARMUP:-50000000}
S=${SIM:-100000000}
DATE=$(date +%Y%m%d_%H%M)
LABEL="qmm_buf_size_${DATE}"

LLC_CAP=256
STLB_CAP=256

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

echo "=== Promotion buffer size sweep ($DATE) ==="
echo "  Fixed: LLC=${LLC_CAP} entries, STLB=${STLB_CAP} entries, lfu_doa"
echo "  Policy: IPV-Live, LLC_MID_THD=4, STLB_MID_THD=1"
echo ""

# buf=0: no promotion buffer — baseline for this study
submit "$LABEL/buf0" champsim_both_ipv_live "buf_0" \
  "LLC_MID_THD=4,LLC_LOW_THD=4,STLB_MID_THD=1,STLB_LOW_THD=1,BHIST_MODE=pc,SRRIP_LIVE_TARGET=both,\
REPL_HIST_LLC_CAP=${LLC_CAP},REPL_HIST_STLB_CAP=${STLB_CAP},REPL_HIST_BUF_CAP=0,REPL_HIST_REPL=lfu_doa"

for buf in 4 8 16 32 64 128; do
  submit "$LABEL/buf${buf}" champsim_both_ipv_live "buf_${buf}" \
    "LLC_MID_THD=4,LLC_LOW_THD=4,STLB_MID_THD=1,STLB_LOW_THD=1,BHIST_MODE=pc,SRRIP_LIVE_TARGET=both,\
REPL_HIST_LLC_CAP=${LLC_CAP},REPL_HIST_STLB_CAP=${STLB_CAP},REPL_HIST_BUF_CAP=${buf},REPL_HIST_REPL=lfu_doa"
done

echo ""
echo "Submitted: 7 job arrays × 45 traces = 315 jobs"
echo "Label: $LABEL"
