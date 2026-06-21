#!/usr/bin/env bash
# test_lifespan.sh — Lifespan measurement: modes 0 and 4 on 5 QMM traces.
#
# mode0_base : SCORING_MODE=0 (two-counter flat, THD_DEAD=0) — lifespan baseline
# mode4_inv  : SCORING_MODE=4 (inverted δ 3/2/1, THD_DEAD=2) — surprise-weighted scoring

set -euo pipefail
BASE=~/ChampSim-dev
TRACES="$BASE/trace-files/QMM"; EXT="champsimtrace.xz"
W=50000000; S=100000000
N=5
DATE=$(date +%Y%m%d_%H%M)
LABEL="qmm_lifespan_${DATE}"

submit() {
  local name="$1" extra="$2"
  local rl="${LABEL}/${name}"
  mkdir -p "$BASE/results/$rl" "$BASE/logs/$LABEL"
  local raw
  raw=$(qsub -t "1-${N}" \
             -N "ls_${name:0:12}" \
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

echo "=== Lifespan measurement: 2 modes x ${N} QMM traces ==="
submit "mode0_base" "SCORING_MODE=0,THD_DOA=4,THD_DEAD=0"
submit "mode4_inv"  "SCORING_MODE=4,THD_DOA=4,THD_DEAD=2"
echo ""
echo "Label : $LABEL"
echo "Jobs  : 2 x ${N} = $((2 * N))"
