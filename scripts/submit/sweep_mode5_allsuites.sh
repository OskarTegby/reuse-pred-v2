#!/usr/bin/env bash
# sweep_mode5_allsuites.sh — SCORING_MODE=5 (lifespan-scaled δ=5/3/1) across all 6 suites.
#
# Mode 5 calibration: δ_MA=5, δ_MD=3, δ_DoA=1
#   THD_DEAD=10 (2×δ_MA), THD_DOA=6 (2×δ_MD) → 2 consecutive evictions saturate each counter.
#
# Binary: champsim_srrip_live_hrp (latest, with bypass-probe changes; HRP inactive here).
# DPC3: all 95 traces (shared dir) — matches the 95-trace scoring_modes sweep for comparison.
# Other suites: all traces.
#
# mode3_decoup NOT included — existing results in {suite}_scoring_modes_20260608_2350/mode3_decoup.
# Run mode3 later on the same traces if needed.
#
# Total: 1 mode × (95+9+11+17+31+45) = 208 jobs

set -euo pipefail
BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
SHARED=/home/users/shared/traces

declare -A SUITE_TRACES SUITE_EXT SUITE_N
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
SUITE_N=(
  [dpc3]=95 [gap]=9 [gms]=11 [ligra]=17 [ml]=31 [qmm]=45
)

total=0

submit() {
  local suite="$1" runlabel="$2" name="$3"
  local n="${SUITE_N[$suite]}"
  local tdir="${SUITE_TRACES[$suite]}"
  local ext="${SUITE_EXT[$suite]}"
  mkdir -p "$BASE/results/$runlabel" "$BASE/logs/$runlabel"
  local raw
  raw=$(qsub -t "1-${n}" \
             -N "${name:0:15}" \
             -o "$BASE/logs/$runlabel/" \
             -e "$BASE/logs/$runlabel/" \
             -l h_rt=24:00:00 \
             -l mem_free=1G \
             -wd "$BASE" \
             -v WARMUP=$W,SIM=$S,TRACE_DIR="$tdir",TRACE_EXT="$ext",\
RUN_LABEL="$runlabel",BINARY=champsim_srrip_live_hrp,\
BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,SCORING_MODE=5,THD_DEAD=10,THD_DOA=6 \
             "$BASE/scripts/submit/run_cs.sh")
  local jid
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${runlabel}  (n=${n})"
  total=$((total + n))
}

echo "=== Mode 5 all-suites sweep ==="
echo "Binary: champsim_srrip_live_hrp"
echo "THD_DEAD=10, THD_DOA=6, SCORING_MODE=5"
echo ""

for suite in dpc3 gap gms ligra ml qmm; do
  LABEL="${suite}_mode5_${DATE}"
  echo "--- ${suite} (${SUITE_N[$suite]} traces) ---"
  submit "$suite" "$LABEL/mode5_life" "m5_${suite:0:3}"
  echo ""
done

echo "Total jobs submitted: ${total}"
echo "Label pattern: {suite}_mode5_${DATE}"
