#!/usr/bin/env bash
# test_scoring_modes.sh — Compare three liveness scoring approaches on 5 QMM traces.
#
# SCORING_MODE=0  Two-counter baseline: DoA→doa++, MD→md++, MA→reset both
# SCORING_MODE=1  Approach A (gradual):  symmetric state-depth-scaled ±, no hard resets
# SCORING_MODE=2  Approach B (reset):    state-depth-scaled +, hard resets on contradiction
#
# Mode 0 uses THD_DEAD=0 (no MD class, matching original two-counter jobs 1404940/1404941).
# Modes 1 and 2 use THD_DEAD=2, THD_DOA=4 to exercise the three-class FSM.
#
# Total: 3 modes × 5 traces = 15 jobs.

set -euo pipefail
BASE=~/ChampSim-dev
TRACES="$BASE/trace-files/QMM"; EXT="champsimtrace.xz"
W=50000000; S=100000000
N=5
DATE=$(date +%Y%m%d_%H%M)
LABEL="qmm_scoring_modes_${DATE}"

submit() {
  local name="$1" extra="$2"
  local run_label="${LABEL}/${name}"
  mkdir -p "$BASE/results/$run_label" "$BASE/logs/$LABEL"
  local raw
  raw=$(qsub -t "1-${N}" \
             -N "sm_${name:0:12}" \
             -o "$BASE/logs/$LABEL/" \
             -e "$BASE/logs/$LABEL/" \
             -l h_rt=4:00:00 \
             -l mem_free=1G \
             -wd "$BASE" \
             -v WARMUP=$W,SIM=$S,TRACE_DIR="$TRACES",TRACE_EXT="$EXT",\
RUN_LABEL="$run_label",BINARY=champsim_srrip_live,\
BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,${extra} \
             "$BASE/scripts/submit/run_cs.sh")
  local jid
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${name}"
}

echo "=== Scoring mode comparison: 5 QMM traces, SRRIP-Live LLC ==="

# Mode 0: flat two-counter baseline, no MD class (THD_DEAD=0)
submit "mode0_two_ctr" "SCORING_MODE=0,THD_DOA=4,THD_DEAD=0"

# Mode 1: Approach A — gradual, no resets, symmetric ±, three classes
submit "mode1_gradual" "SCORING_MODE=1,THD_DOA=4,THD_DEAD=2"

# Mode 2: Approach B — hard resets, state-dependent increments, three classes
submit "mode2_reset"   "SCORING_MODE=2,THD_DOA=4,THD_DEAD=2"

echo ""
echo "Label : $LABEL"
echo "Jobs  : 3 modes × ${N} traces = $((3 * N)) jobs"
echo "Geomean vs SRRIP baseline:"
echo "  awk -f /tmp/geomean.awk \$BASE/results/\$LABEL/mode*/champsim.out"
