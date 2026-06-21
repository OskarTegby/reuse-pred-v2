#!/usr/bin/env bash
# test_flat_and_calibrated.sh — Two controlled experiments:
#
# mode0_flat3  : SCORING_MODE=0 (flat δ=1), THD_DEAD=2, THD_DOA=4
#   Three-class but uniform δ. MD after 2 MD evictions, DoA after 4 DoA evictions.
#   Matches mode0_ref eviction counts; isolates whether the δ scaling matters at all.
#
# mode4_cal    : SCORING_MODE=4 (inverted δ=3/2/1), THD_DEAD=6, THD_DOA=4
#   Calibrated thresholds so MD still requires 2 MD evictions (2×δ_MA=3 → thd_dead=6)
#   and DoA from MD still requires 2 DoA evictions (2×δ_MD=2 → thd_doa=4).

set -euo pipefail
BASE=~/ChampSim-dev
TRACES="$BASE/trace-files/QMM"; EXT="champsimtrace.xz"
W=50000000; S=100000000
N=5
DATE=$(date +%Y%m%d_%H%M)
LABEL="qmm_calibrated_${DATE}"

submit() {
  local name="$1" extra="$2"
  local rl="${LABEL}/${name}"
  mkdir -p "$BASE/results/$rl" "$BASE/logs/$LABEL"
  local raw
  raw=$(qsub -t "1-${N}" \
             -N "cal_${name:0:12}" \
             -o "$BASE/logs/$LABEL/" \
             -e "$BASE/logs/$LABEL/" \
             -l h_rt=4:00:00 \
             -l mem_free=1G \
             -wd "$BASE" \
             -v WARMUP=$W,SIM=$S,TRACE_DIR="$TRACES",TRACE_EXT="$EXT",\
RUN_LABEL="$rl",BINARY=champsim_srrip_live,\
BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,${extra} \
             "$BASE/scripts/submit/run_cs.sh")
  local jid
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${name}"
}

echo "=== Calibration experiments: 2 modes x ${N} QMM traces ==="
submit "mode0_flat3" "SCORING_MODE=0,THD_DOA=4,THD_DEAD=2"
submit "mode4_cal"   "SCORING_MODE=4,THD_DOA=4,THD_DEAD=6"
echo ""
echo "Label : $LABEL"
echo "Jobs  : 2 x ${N} = $((2 * N))"
