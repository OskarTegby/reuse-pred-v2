#!/bin/bash
set -euo pipefail

# History table size study with buf=128 fixed for both LLC and STLB.
# Each sweep varies one level's table size while the other is unbounded,
# isolating the effect of each level's capacity with a realistic buffer.
# Policy: IPV-Live, per-level optimal thresholds (LLC=4, STLB=1).

BASE=~/ChampSim-dev
TRACES="$BASE/trace-files/QMM"; EXT="champsimtrace.xz"
W=${WARMUP:-50000000}
S=${SIM:-100000000}
DATE=$(date +%Y%m%d_%H%M)
LABEL="qmm_size_buf128_${DATE}"

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

COMMON="LLC_MID_THD=4,LLC_LOW_THD=4,STLB_MID_THD=1,STLB_LOW_THD=1,BHIST_MODE=pc,SRRIP_LIVE_TARGET=both,REPL_HIST_BUF_CAP=128,REPL_HIST_REPL=lfu_doa"

echo "=== LLC size sweep (STLB unbounded, buf=128) ==="
for cap in 4096 2048 1024 512 256 128; do
  submit "$LABEL/llc_cap${cap}" champsim_both_ipv_live "llc_${cap}" \
    "${COMMON},REPL_HIST_LLC_CAP=${cap}"
done

echo ""
echo "=== STLB size sweep (LLC unbounded, buf=128) ==="
for cap in 1024 512 256 128; do
  submit "$LABEL/stlb_cap${cap}" champsim_both_ipv_live "stlb_${cap}" \
    "${COMMON},REPL_HIST_STLB_CAP=${cap}"
done

echo ""
echo "Submitted: 10 job arrays × 45 traces = 450 jobs"
echo "Label: $LABEL"
