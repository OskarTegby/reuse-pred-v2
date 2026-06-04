#!/bin/bash
set -euo pipefail
# Threshold reruns after the writeback fixes (replacement skip + liveness-label
# exclusion). Unbounded history. SRRIP-Live & IPV-Live, LLC and STLB in
# separation, plus recomputed default LRU/SRRIP/IPV baselines.
BASE=~/ChampSim-dev
TRACES="$BASE/trace-files/QMM"; EXT="champsimtrace.xz"
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="qmm_thd_rebaseline_${DATE}"

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

echo "=== Baselines (unbounded, recomputed with all fixes) ==="
submit "$LABEL/lru"   champsim_lru      "rb_lru"
submit "$LABEL/srrip" champsim_srrip    "rb_srrip"
submit "$LABEL/ipv"   champsim_ipv_live "rb_ipv" "SRRIP_LIVE_TARGET=none"

echo "--- SRRIP-Live LLC (unbounded) ---"
for thd in 1 2 4 8 16; do
  submit "$LABEL/srrip_live_llc/thd${thd}" champsim_srrip_live "rsl_${thd}" \
    "MID_THD=${thd},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"
done
echo "--- IPV-Live LLC (unbounded) ---"
for thd in 1 2 4 8 16; do
  submit "$LABEL/ipv_live_llc/thd${thd}" champsim_ipv_live "ril_${thd}" \
    "MID_THD=${thd},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"
done
echo "--- SRRIP-Live STLB (unbounded) ---"
for thd in 1 2 4 8 16; do
  submit "$LABEL/srrip_live_stlb/thd${thd}" champsim_stlb_srrip_live "rss_${thd}" \
    "MID_THD=${thd},BHIST_MODE=pc,SRRIP_LIVE_TARGET=stlb"
done
echo "--- IPV-Live STLB (unbounded) ---"
for thd in 1 2 4 8 16; do
  submit "$LABEL/ipv_live_stlb/thd${thd}" champsim_stlb_ipv_live "ris_${thd}" \
    "MID_THD=${thd},BHIST_MODE=pc,SRRIP_LIVE_TARGET=stlb"
done

echo ""
echo "Submitted: 23 arrays x 45 traces = 1035 jobs"
echo "Label: $LABEL"
