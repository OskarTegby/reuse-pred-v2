#!/usr/bin/env bash
# test_mode5_allsuites.sh — Mode 5 debug run across dpc3/gap/gms/ligra/ml (5 traces each).
# Uses 8h wall time to avoid long-running trace issues.
# Compares mode3_decoup (reference) vs mode5_life (lifespan-scaled δ=5/3/1).
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
)
SUITE_EXT=(
  [dpc3]="champsimtrace.xz"
  [gap]="trace.gz"
  [gms]="champsimtrace.gz"
  [ligra]="champsimtrace.xz"
  [ml]="champsimtrace.gz"
)

total=0

submit() {
  local suite="$1" runlabel="$2" name="$3" extra="$4"
  local tdir="${SUITE_TRACES[$suite]}"
  local ext="${SUITE_EXT[$suite]}"
  mkdir -p "$BASE/results/$runlabel" "$BASE/logs/$runlabel"
  local raw
  raw=$(qsub -t "1-${N}" \
             -N "${name:0:15}" \
             -o "$BASE/logs/$runlabel/" \
             -e "$BASE/logs/$runlabel/" \
             -l h_rt=8:00:00 \
             -l mem_free=1G \
             -wd "$BASE" \
             -v WARMUP=$W,SIM=$S,TRACE_DIR="$tdir",TRACE_EXT="$ext",\
RUN_LABEL="$runlabel",BINARY=champsim_srrip_live,\
BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,THD_DOA=4,${extra} \
             "$BASE/scripts/submit/run_cs.sh")
  local jid
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=$jid]  $name  ($N traces)"
  total=$((total + N))
}

echo "=== Mode 5 debug run — dpc3/gap/gms/ligra/ml, n=$N each, 8h wall ==="
LABEL=mode5_allsuites_${DATE}
echo "Label: $LABEL"
echo ""

for suite in dpc3 gap gms ligra ml; do
  echo "--- $suite ---"
  submit "$suite" "$BASE/results/$LABEL/${suite}_mode3" "m5_${suite:0:3}_m3d" "SCORING_MODE=3,THD_DEAD=2"
  submit "$suite" "$BASE/results/$LABEL/${suite}_mode5" "m5_${suite:0:3}_m5l" "SCORING_MODE=5,THD_DEAD=10,THD_DOA=6"
  echo ""
done

echo "Total tasks submitted: $total"
echo "Results: $BASE/results/$LABEL/"
