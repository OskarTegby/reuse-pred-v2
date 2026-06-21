#!/usr/bin/env bash
# sweep_scoring_modes_allsuites.sh — Compare four scoring modes across all 6 suites.
#
# Modes compared (modes 1 and 2 excluded: pathological stickiness / coupling bugs):
#   mode0_ref   : SCORING_MODE=0, THD_DEAD=0  — flat two-class (MA/DoA only)
#   mode0_flat3 : SCORING_MODE=0, THD_DEAD=2  — flat three-class (new best on QMM)
#   mode3_decoup: SCORING_MODE=3, THD_DEAD=2  — decoupled confirmatory δ (1/2/3)
#   mode4_cal   : SCORING_MODE=4, THD_DEAD=6  — calibrated inverted δ (3/2/1)
#
# All modes: THD_DOA=4, BHIST_MODE=pc, SRRIP_LIVE_TARGET=llc, unbounded history.
#
# Suites: dpc3 (71/95), gap (9), gms (11), ligra (17), ml (31), qmm (45) = 184 traces
# Total : 4 modes x 184 = 736 jobs
# Uses trace_pressure_filter.sh to skip LLC-inert traces (< 10K LLC misses).

set -euo pipefail
BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
SHARED=/home/users/shared/traces

source "$BASE/scripts/submit/trace_pressure_filter.sh"

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

total=0

submit() {
  local suite="$1" runlabel="$2" name="$3" extra="$4"
  local ids="${PRESSURE_IDS[$suite]}"
  local n="${PRESSURE_N[$suite]}"
  local tdir="${SUITE_TRACES[$suite]}"
  local ext="${SUITE_EXT[$suite]}"
  mkdir -p "$BASE/results/$runlabel" "$BASE/logs/$runlabel"
  local raw
  raw=$(qsub -t "${ids}" \
             -N "${name:0:15}" \
             -o "$BASE/logs/$runlabel/" \
             -e "$BASE/logs/$runlabel/" \
             -l h_rt=24:00:00 \
             -l mem_free=1G \
             -wd "$BASE" \
             -v WARMUP=$W,SIM=$S,TRACE_DIR="$tdir",TRACE_EXT="$ext",\
RUN_LABEL="$runlabel",BINARY=champsim_srrip_live,\
BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,THD_DOA=4,${extra} \
             "$BASE/scripts/submit/run_cs.sh")
  local jid
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${runlabel}  (n=${n})"
  total=$((total + n))
}

echo "=== Scoring mode sweep — all 6 suites (LLC-pressure traces only) ==="

echo ""

for suite in dpc3 gap gms ligra ml qmm; do
  LABEL="${suite}_scoring_modes_${DATE}"
  echo "--- ${suite} ---"
  submit "$suite" "$LABEL/mode0_ref"    "sm_${suite:0:3}_m0r" "SCORING_MODE=0,THD_DEAD=0"
  submit "$suite" "$LABEL/mode0_flat3"  "sm_${suite:0:3}_m0f" "SCORING_MODE=0,THD_DEAD=2"
  submit "$suite" "$LABEL/mode3_decoup" "sm_${suite:0:3}_m3d" "SCORING_MODE=3,THD_DEAD=2"
  submit "$suite" "$LABEL/mode4_cal"    "sm_${suite:0:3}_m4c" "SCORING_MODE=4,THD_DEAD=6"
  echo ""
done

echo "Total jobs submitted: ${total}"
echo "Label pattern: {suite}_scoring_modes_${DATE}"
