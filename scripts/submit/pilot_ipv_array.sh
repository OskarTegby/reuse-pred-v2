#!/bin/bash
set -euo pipefail

BASE=~/ChampSim-dev
TRACES="$BASE/trace-files/QMM"
EXT="champsimtrace.xz"
W=${WARMUP:-50000000}
S=${SIM:-100000000}
DATE=$(date +%Y%m%d_%H%M)

submit() {
  local label="$1" binary="$2" jobname="$3"; shift 3
  mkdir -p "$BASE/results/$label" "$BASE/logs/$label"
  local jid=$(qsub -t 1-10 -N "$jobname" \
       -o "$BASE/logs/$label/" -e "$BASE/logs/$label/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "$BASE" \
       -v WARMUP=$W,SIM=$S,TRACE_DIR="$TRACES",TRACE_EXT="$EXT",\
RUN_LABEL="$label",BINARY="$binary",$* \
       "$BASE/scripts/submit/run_cs.sh" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=$jid] $label (10 traces)"
}

echo "=== IPV-Live LLC Size Pilot ($DATE) ==="
submit "llc_ipv_pilot_${DATE}/unbounded" "champsim_ipv_live" "ipv_llc_ub" \
  "MID_THD=4,LOW_THD=4,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"

for cap in 4096 1024 256 128; do
  submit "llc_ipv_pilot_${DATE}/cap${cap}" "champsim_ipv_live" "ipv_llc_${cap}" \
    "MID_THD=4,LOW_THD=4,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,REPL_HIST_LLC_CAP=${cap},REPL_HIST_BUF_CAP=32,REPL_HIST_REPL=lfu_doa"
done

echo ""
echo "=== IPV-Live STLB Size Pilot ($DATE) ==="
submit "stlb_ipv_pilot_${DATE}/unbounded" "champsim_stlb_ipv_live" "ipv_stlb_ub" \
  "MID_THD=1,LOW_THD=1,BHIST_MODE=pc,SRRIP_LIVE_TARGET=stlb"

for cap in 1024 256 128; do
  submit "stlb_ipv_pilot_${DATE}/cap${cap}" "champsim_stlb_ipv_live" "ipv_stlb_${cap}" \
    "MID_THD=1,LOW_THD=1,BHIST_MODE=pc,SRRIP_LIVE_TARGET=stlb,REPL_HIST_STLB_CAP=${cap},REPL_HIST_BUF_CAP=8,REPL_HIST_REPL=lfu_doa"
done

echo ""
echo "Submitted: 9 job arrays × 10 traces = 90 jobs (proper arrays this time)"
