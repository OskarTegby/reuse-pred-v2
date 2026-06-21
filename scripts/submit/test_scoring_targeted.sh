#!/usr/bin/env bash
# test_scoring_targeted.sh — Run the overnight-sweep best contenders
# (mode0_ref, mode0_flat3, mode4_cal) on the same high-spread targeted traces
# as test_mode5_targeted.sh. Reuses the symlink dirs from that run.
#
# Pass the targeted_<DATE> directory name as $1, e.g.:
#   bash test_scoring_targeted.sh targeted_20260609_1058
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <targeted_DATE_dir>"
  exit 1
fi

BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL=mode_sweep_targeted_${DATE}
SYMLINK_BASE="$BASE/trace-files/$1"

declare -A EXT
EXT[dpc3]="champsimtrace.xz"
EXT[gap]="trace.gz"
EXT[gms]="champsimtrace.gz"
EXT[ligra]="champsimtrace.xz"
EXT[ml]="champsimtrace.gz"
EXT[qmm]="champsimtrace.xz"

total=0

echo "=== Scoring mode sweep on targeted traces ==="
echo "Symlink dir: $SYMLINK_BASE"
echo "Label:       $LABEL"
echo ""

for suite in dpc3 gap gms ligra ml qmm; do
  symdir="$SYMLINK_BASE/$suite"
  ext="${EXT[$suite]}"
  n=$(ls "$symdir"/*."$ext" 2>/dev/null | wc -l)
  [ "$n" -eq 0 ] && echo "  $suite: no traces in $symdir, skipping" && continue

  echo "--- $suite ($n traces) ---"
  mkdir -p "$BASE/logs/$LABEL"

  for cfg in \
    "mode0_ref:SCORING_MODE=0,THD_DEAD=0,THD_DOA=4" \
    "mode0_flat3:SCORING_MODE=0,THD_DEAD=2,THD_DOA=4" \
    "mode4_cal:SCORING_MODE=4,THD_DEAD=6,THD_DOA=4"; do
    name="${cfg%%:*}"; extra="${cfg#*:}"
    runlabel="$LABEL/${suite}_${name}"
    mkdir -p "$BASE/results/$runlabel"
    raw=$(qsub -t "1-${n}" \
               -N "${name:0:15}" \
               -o "$BASE/logs/$LABEL/" \
               -e "$BASE/logs/$LABEL/" \
               -l h_rt=8:00:00 \
               -l mem_free=1G \
               -wd "$BASE" \
               -v WARMUP=$W,SIM=$S,TRACE_DIR="$symdir",TRACE_EXT="$ext",\
RUN_LABEL="$runlabel",BINARY=champsim_srrip_live,\
BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,${extra} \
               "$BASE/scripts/submit/run_cs.sh")
    jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
    echo "  [jid=$jid]  ${suite}/${name}  (n=$n)"
    total=$((total + n))
  done
  echo ""
done

echo "Total tasks: $total"
echo "Results:     $BASE/results/$LABEL/"
