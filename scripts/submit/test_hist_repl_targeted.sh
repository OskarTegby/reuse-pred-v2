#!/usr/bin/env bash
# test_hist_repl_targeted.sh — Compare history table replacement policy variants
# on the high-spread targeted traces. All runs use SCORING_MODE=3 to isolate
# the replacement policy change from scoring mode effects.
#
# Configs compared:
#   old_repl  : champsim_srrip_live     — DoA-only LFU, no aging (baseline)
#   ma_neg2   : champsim_srrip_live_hrp — DoA×3 + MD×1, MA−2, aging (original new policy)
#   ma_neg1   : champsim_srrip_live_hrp — DoA×3 + MD×1, MA−1, aging (softer MA penalty)
#   ma_0      : champsim_srrip_live_hrp — DoA×3 + MD×1, MA=0, aging (neutral MA)
#
# evict_attr lines in champsim.out show: how much MA penalty and aging each
# contributed to the score reduction on every evicted history-table entry.
#
# Usage: $0 <targeted_DATE_dir> [cap]
#   targeted_DATE_dir : symlink dir under trace-files/ (e.g. targeted_20260609_1058)
#   cap               : REPL_HIST_LLC_CAP (default 64)
#
# Example:
#   bash test_hist_repl_targeted.sh targeted_20260609_1058 64
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <targeted_DATE_dir> [cap]"
  exit 1
fi

BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
CAP=${2:-64}
LABEL=hist_repl_targeted_cap${CAP}_${DATE}
SYMLINK_BASE="$BASE/trace-files/$1"

declare -A EXT
EXT[dpc3]="champsimtrace.xz"
EXT[gap]="trace.gz"
EXT[gms]="champsimtrace.gz"
EXT[ligra]="champsimtrace.xz"
EXT[ml]="champsimtrace.gz"
EXT[qmm]="champsimtrace.xz"

total=0

echo "=== History table replacement policy comparison ==="
echo "Symlink dir: $SYMLINK_BASE"
echo "Cap:         $CAP"
echo "Label:       $LABEL"
echo ""

for suite in dpc3 gap gms ligra ml qmm; do
  symdir="$SYMLINK_BASE/$suite"
  ext="${EXT[$suite]}"
  n=$(ls "$symdir"/*."$ext" 2>/dev/null | wc -l)
  [ "$n" -eq 0 ] && echo "  $suite: no traces in $symdir, skipping" && continue

  echo "--- $suite ($n traces) ---"
  mkdir -p "$BASE/logs/$LABEL"

  # cfg format: "label:binary:ma_penalty"  (ma_penalty empty → no HIST_MA_PENALTY set)
  for cfg in \
      "old_repl:champsim_srrip_live:" \
      "ma_neg2:champsim_srrip_live_hrp:-2" \
      "ma_neg1:champsim_srrip_live_hrp:-1" \
      "ma_0:champsim_srrip_live_hrp:0"; do
    name=$(echo "$cfg"   | cut -d: -f1)
    binary=$(echo "$cfg" | cut -d: -f2)
    ma_pen=$(echo "$cfg" | cut -d: -f3)

    ma_extra=""
    [[ -n "$ma_pen" ]] && ma_extra=",HIST_MA_PENALTY=${ma_pen}"

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
RUN_LABEL="$runlabel",BINARY="$binary",\
BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,SCORING_MODE=3,THD_DEAD=2,THD_DOA=4,\
REPL_HIST_LLC_CAP=${CAP},REPL_HIST_REPL=lfu_doa${ma_extra} \
               "$BASE/scripts/submit/run_cs.sh")
    jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
    echo "  [jid=$jid]  ${suite}/${name}  (n=$n)"
    total=$((total + n))
  done
  echo ""
done

echo "Total tasks: $total"
echo "Results:     $BASE/results/$LABEL/"
