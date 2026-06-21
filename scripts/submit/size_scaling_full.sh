#!/bin/bash
set -euo pipefail
BASE=~/ChampSim-dev
TRACES="$BASE/trace-files/QMM"; EXT="champsimtrace.xz"
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="qmm_size_scaling_full_${DATE}"

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

IPV_COMMON="MID_THD=4,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,REPL_HIST_BUF_CAP=128,REPL_HIST_REPL=lfu_doa"
SR_COMMON="MID_THD=4,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,REPL_HIST_BUF_CAP=128,REPL_HIST_REPL=lfu_doa"

echo "=== Size scaling, buf=128, 50M+100M, 45 traces ($DATE) ==="
echo "--- Baselines ---"
submit "$LABEL/lru"       champsim_lru        "fs_lru"
submit "$LABEL/ipv"       champsim_ipv_live   "fs_ipv"   "SRRIP_LIVE_TARGET=none"
submit "$LABEL/srrip"     champsim_srrip      "fs_srrip"

echo "--- IPV-Live ---"
for cap in 4096 2048 1024 512 256 128 64 32 16; do
  submit "$LABEL/ipv_cap${cap}" champsim_ipv_live "fi_${cap}" "${IPV_COMMON},REPL_HIST_LLC_CAP=${cap}"
done
submit "$LABEL/ipv_unbounded" champsim_ipv_live "fi_ub" "MID_THD=4,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"

echo "--- SRRIP-Live ---"
for cap in 4096 2048 1024 512 256 128 64 32 16; do
  submit "$LABEL/srrip_cap${cap}" champsim_srrip_live "fs_${cap}" "${SR_COMMON},REPL_HIST_LLC_CAP=${cap}"
done
submit "$LABEL/srrip_unbounded" champsim_srrip_live "fs_ub" "MID_THD=4,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"

echo ""
echo "Submitted: 23 arrays × 45 traces = 1035 jobs"
echo "Label: $LABEL"
