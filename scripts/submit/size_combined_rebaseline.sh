#!/bin/bash
set -euo pipefail
# Post-fix size studies + combined run, both levels guided (LLC thd=4, STLB thd=1).
# - Combined: both levels unbounded -> measures additive LLC+STLB liveness gain.
# - LLC size study: scale LLC table {256..4096} w/ buf=128, STLB unbounded.
# - STLB size study: scale STLB table {256..1024} w/ buf=128, LLC unbounded
#   (smaller top than LLC: the STLB is a smaller structure; floor at 256).
# Baselines (LRU, SRRIP) are reused from qmm_thd_rebaseline_20260604_2307.
# Requires the per-level-cap-independence fix (champsim_both_* rebuilt 2026-06-05).
BASE=~/ChampSim-dev
TRACES="$BASE/trace-files/QMM"; EXT="champsimtrace.xz"
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="qmm_size_combined_${DATE}"
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

echo "=== Combined (both levels unbounded, LLC thd=4 + STLB thd=1) ==="
submit "$LABEL/combined/srrip_live" champsim_both_srrip_live "cb_sl" "$COMMON"
submit "$LABEL/combined/ipv_live"   champsim_both_ipv_live   "cb_il" "$COMMON"

echo "--- LLC size study (SRRIP-Live, buf=128, STLB unbounded) ---"
for cap in 256 512 1024 2048 4096; do
  submit "$LABEL/size_llc/cap${cap}" champsim_both_srrip_live "sl_${cap}" \
    "REPL_HIST_LLC_CAP=${cap},REPL_HIST_BUF_CAP=128,$COMMON"
done

echo "--- STLB size study (SRRIP-Live, buf=128, LLC unbounded) ---"
for cap in 256 512 1024; do
  submit "$LABEL/size_stlb/cap${cap}" champsim_both_srrip_live "ss_${cap}" \
    "REPL_HIST_STLB_CAP=${cap},REPL_HIST_BUF_CAP=128,$COMMON"
done

echo ""
echo "Submitted: 12 arrays x 45 traces = 540 jobs"
echo "Label: $LABEL"
