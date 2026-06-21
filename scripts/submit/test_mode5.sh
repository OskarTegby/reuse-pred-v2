#!/usr/bin/env bash
# test_mode5.sh — Debug run for SCORING_MODE=5 (lifespan-scaled δ=5/3/1)
#   vs mode3_decoup as reference, on 5 QMM traces.
#
# Mode 5 calibration:
#   δ_MA=5, δ_MD=3, δ_DoA=1
#   THD_DEAD=10 (2 × δ_MA=5), THD_DOA=6 (2 × δ_MD=3)
#   => N=2 consecutive evictions from any state saturate that counter.
#
# Mode 3 reference (same thresholds as mode5_cal for fair comparison):
#   SCORING_MODE=3, THD_DEAD=2, THD_DOA=4
#
set -euo pipefail
BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL=qmm_mode5_${DATE}
TDIR=$BASE/trace-files/QMM
EXT=champsimtrace.xz
N=5

echo "=== Mode 5 debug run — QMM, n=$N traces ==="
echo "Label: $LABEL"
echo ""

submit() {
  local name="$1" extra="$2"
  local runlabel=$LABEL/$name
  mkdir -p "$BASE/results/$runlabel" "$BASE/logs/$runlabel"
  local raw
  raw=$(qsub -t "1-${N}" \
             -N "${name:0:15}" \
             -o "$BASE/logs/$runlabel/" \
             -e "$BASE/logs/$runlabel/" \
             -l h_rt=24:00:00 \
             -l mem_free=1G \
             -wd "$BASE" \
             -v WARMUP=$W,SIM=$S,TRACE_DIR="$TDIR",TRACE_EXT="$EXT",\
RUN_LABEL="$runlabel",BINARY=champsim_srrip_live,\
BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,${extra} \
             "$BASE/scripts/submit/run_cs.sh")
  local jid
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=$jid]  $name  ($N traces)"
}

submit "mode3_decoup" "SCORING_MODE=3,THD_DEAD=2,THD_DOA=4"
submit "mode5_life"   "SCORING_MODE=5,THD_DEAD=10,THD_DOA=6"

echo ""
echo "Results: $BASE/results/$LABEL/"
