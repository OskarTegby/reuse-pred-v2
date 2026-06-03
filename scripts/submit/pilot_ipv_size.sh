#!/bin/bash
set -euo pipefail

BASE=~/ChampSim-dev
TRACES="$BASE/trace-files/QMM"; EXT="champsimtrace.xz"
W=${WARMUP:-50000000}
S=${SIM:-100000000}
DATE=$(date +%Y%m%d_%H%M)

# Submit just the first 8 traces for a quick pilot
submit_trace() {
  local label="$1" binary="$2" jobname="$3" trace_idx="$4"; shift 4
  mkdir -p "$BASE/results/$label" "$BASE/logs/$label"
  local jid=$(qsub -t "$trace_idx" -N "$jobname" \
       -o "$BASE/logs/$label/" -e "$BASE/logs/$label/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "$BASE" \
       -v WARMUP=$W,SIM=$S,TRACE_DIR="$TRACES",TRACE_EXT="$EXT",\
RUN_LABEL="$label",BINARY="$binary",$* \
       "$BASE/scripts/submit/run_cs.sh" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=$jid] trace $trace_idx"
}

echo "=== IPV-Live LLC Size Pilot ($DATE) ==="
for cap in 0 4096 1024 256 128; do
  cap_label=$([ "$cap" = "0" ] && echo "unbounded" || echo "cap${cap}")
  cap_env=$([ "$cap" = "0" ] && echo "" || echo "REPL_HIST_LLC_CAP=${cap},REPL_HIST_BUF_CAP=32,")
  echo "  Size: $cap_label"
  for trace_idx in 1 5 10 15 20 25 30 35 40 45; do
    submit_trace "llc_ipv_size_pilot_${DATE}/${cap_label}" \
      "champsim_ipv_live" "ipv_llc_${cap_label}" "$trace_idx" \
      "MID_THD=4,LOW_THD=4,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,${cap_env}REPL_HIST_REPL=lfu_doa" | sed 's/^/    /'
  done
done

echo ""
echo "=== IPV-Live STLB Size Pilot ($DATE) ==="
for cap in 0 1024 256 128; do
  cap_label=$([ "$cap" = "0" ] && echo "unbounded" || echo "cap${cap}")
  cap_env=$([ "$cap" = "0" ] && echo "" || echo "REPL_HIST_STLB_CAP=${cap},REPL_HIST_BUF_CAP=32,")
  echo "  Size: $cap_label"
  for trace_idx in 1 5 10 15 20 25 30 35 40 45; do
    submit_trace "stlb_ipv_size_pilot_${DATE}/${cap_label}" \
      "champsim_stlb_ipv_live" "ipv_stlb_${cap_label}" "$trace_idx" \
      "MID_THD=1,LOW_THD=1,BHIST_MODE=pc,SRRIP_LIVE_TARGET=stlb,${cap_env}REPL_HIST_REPL=lfu_doa" | sed 's/^/    /'
  done
done

echo ""
echo "Submitted: 50 jobs (10 traces × 5 LLC sizes) + 40 jobs (10 traces × 4 STLB sizes) = 90 jobs"
