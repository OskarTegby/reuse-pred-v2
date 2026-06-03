#!/bin/bash
set -euo pipefail

# Size study: sweep history table capacity from unbounded down to 128 entries.
# LLC: 4096 → 2048 → 1024 → 512 → 256 → 128
# STLB: 1024 → 512 → 256 → 128

BASE=~/ChampSim-dev
TRACES="$BASE/trace-files/QMM"; EXT="champsimtrace.xz"
W=${WARMUP:-50000000}
S=${SIM:-100000000}
DATE=$(date +%Y%m%d_%H%M)

usage() {
  echo "Usage: $0 [--llc-only|--stlb-only]"
  echo "  Default: run both LLC and STLB size studies"
  echo "  Metrics tracked: miss rate, activation count, IPC"
  exit 1
}

llc_only=0
stlb_only=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --llc-only)  llc_only=1; shift ;;
    --stlb-only) stlb_only=1; shift ;;
    *) usage ;;
  esac
done

if [ "$llc_only" = "1" ] && [ "$stlb_only" = "1" ]; then
  echo "Cannot specify both --llc-only and --stlb-only"
  exit 1
fi

submit() {
  local label="$1" binary="$2" jobname="$3" policy="$4" cap="$5" n="$6"; shift 6
  mkdir -p "$BASE/results/$label" "$BASE/logs/$label"
  local jid=$(qsub -t "1-${n}" -N "$jobname" \
       -o "$BASE/logs/$label/" -e "$BASE/logs/$label/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "$BASE" \
       -v WARMUP=$W,SIM=$S,TRACE_DIR="$TRACES",TRACE_EXT="$EXT",\
RUN_LABEL="$label",BINARY="$binary",$* \
       "$BASE/scripts/submit/run_cs.sh" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=$jid] $label"
}

if [ "$stlb_only" != "1" ]; then
  echo "=== LLC History Size Study ($DATE) ==="
  for policy in srrip_live ipv_live lru_live; do
    binary="champsim_${policy}"
    echo "  Policy: $policy"
    # Unbounded baseline (capacity 0)
    submit "llc_size_${policy}_${DATE}/unbounded" "$binary" "llc_sz_${policy}_ub" \
      "$policy" "0" 45 \
      "MID_THD=4,LOW_THD=4,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"
    # Bounded sizes: 4096, 2048, 1024, 512, 256, 128
    for cap in 4096 2048 1024 512 256 128; do
      submit "llc_size_${policy}_${DATE}/cap${cap}" "$binary" "llc_sz_${policy}_${cap}" \
        "$policy" "$cap" 45 \
        "MID_THD=4,LOW_THD=4,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,\
REPL_HIST_LLC_CAP=${cap},REPL_HIST_BUF_CAP=32,REPL_HIST_REPL=lfu_doa"
    done
  done
fi

if [ "$llc_only" != "1" ]; then
  echo "=== STLB History Size Study ($DATE) ==="
  for policy in srrip_live ipv_live lru_live; do
    binary="champsim_stlb_${policy}"
    echo "  Policy: $policy"
    # Unbounded baseline (capacity 0)
    submit "stlb_size_${policy}_${DATE}/unbounded" "$binary" "stlb_sz_${policy}_ub" \
      "$policy" "0" 45 \
      "MID_THD=1,LOW_THD=1,BHIST_MODE=pc,SRRIP_LIVE_TARGET=stlb"
    # Bounded sizes: 1024, 512, 256, 128
    for cap in 1024 512 256 128; do
      submit "stlb_size_${policy}_${DATE}/cap${cap}" "$binary" "stlb_sz_${policy}_${cap}" \
        "$policy" "$cap" 45 \
        "MID_THD=1,LOW_THD=1,BHIST_MODE=pc,SRRIP_LIVE_TARGET=stlb,\
REPL_HIST_STLB_CAP=${cap},REPL_HIST_BUF_CAP=32,REPL_HIST_REPL=lfu_doa"
    done
  done
fi

echo ""
echo "Submitted size study jobs"
