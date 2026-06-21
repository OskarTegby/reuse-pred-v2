#!/usr/bin/env bash
# test_mode5_recal.sh — Recalibrated mode5 debug run: THD_DOA=20 (4×δ_MA=5),
#   THD_DEAD=10 (2×δ_MA=5). Matches mode3's 4-eviction requirement on the pure
#   DoA path from MA state.
# Submits mode5_life for all 6 suites, 5 traces each, 8h wall time.
# Mode3 jobs for dpc3/gap/gms/ligra/ml are already running (keep them).
# QMM mode3 already finished; only mode5 needed for QMM.
set -euo pipefail
BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
SHARED=/home/users/shared/traces
N=5

declare -A SUITE_TRACES SUITE_EXT
SUITE_TRACES=(
  [dpc3]="${SHARED}/dpc3_traces"
  [gap]="${BASE}/trace-files/gap"
  [gms]="${BASE}/trace-files/gms"
  [ligra]="${BASE}/trace-files/ligra"
  [ml]="${BASE}/trace-files/ml"
  [qmm]="${BASE}/trace-files/QMM"
)
SUITE_EXT=(
  [dpc3]="champsimtrace.xz"
  [gap]="trace.gz"
  [gms]="champsimtrace.gz"
  [ligra]="champsimtrace.xz"
  [ml]="champsimtrace.gz"
  [qmm]="champsimtrace.xz"
)

LABEL=mode5_recal_${DATE}
echo "=== Mode5 recalibrated — all 6 suites, n=$N, THD_DEAD=10 THD_DOA=20 ==="
echo "Label: $LABEL"
echo ""

total=0
for suite in dpc3 gap gms ligra ml qmm; do
  runlabel=$BASE/results/$LABEL/${suite}_mode5
  mkdir -p "$runlabel" "$BASE/logs/$LABEL"
  raw=$(qsub -t "1-${N}" \
             -N "m5r_${suite:0:3}_m5l" \
             -o "$BASE/logs/$LABEL/" \
             -e "$BASE/logs/$LABEL/" \
             -l h_rt=8:00:00 \
             -l mem_free=1G \
             -wd "$BASE" \
             -v WARMUP=$W,SIM=$S,\
TRACE_DIR="${SUITE_TRACES[$suite]}",TRACE_EXT="${SUITE_EXT[$suite]}",\
RUN_LABEL="$runlabel",BINARY=champsim_srrip_live,\
BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,\
SCORING_MODE=5,THD_DEAD=10,THD_DOA=20 \
             "$BASE/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=$jid]  ${suite}_mode5  ($N traces)"
  total=$((total + N))
done

echo ""
echo "Total tasks: $total"
echo "Results: $BASE/results/$LABEL/"
