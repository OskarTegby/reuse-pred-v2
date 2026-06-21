#!/usr/bin/env bash
set -euo pipefail
BASE=~/ChampSim-dev
W=50000000; S=100000000
LABEL="size_srrip_live_small_$(date +%Y%m%d_%H%M)"
LIVE_BASE="SCORING_MODE=5,THD_DOA=6,THD_DEAD=10,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"

mkdir -p "${BASE}/logs/${LABEL}"
echo "Label: ${LABEL}"

submit_suite() {
  local suite="$1" traces="$2" ext="$3" n="$4"
  echo "--- ${suite} (${n} traces) ---"
  for cap in 256 512 1024 2048 4096; do
    mkdir -p "${BASE}/results/${LABEL}/${suite}/tier_c${cap}"
    jid=$(qsub -t "1-${n}" -N "sz_ti${cap}_${suite:0:3}" \
      -o "${BASE}/logs/${LABEL}/" -e "${BASE}/logs/${LABEL}/" \
      -l h_rt=24:00:00 -l mem_free=4G -wd "${BASE}" \
      -v "WARMUP=${W},SIM=${S},TRACE_DIR=${traces},TRACE_EXT=${ext},RUN_LABEL=${LABEL}/${suite}/tier_c${cap},BINARY=champsim_srrip_live,${LIVE_BASE},REPL_HIST_LLC_CAP=${cap},REPL_HIST_REPL=tiered" \
      "${BASE}/scripts/submit/run_cs.sh" \
      | awk '/Your job/ {print $3}' | cut -d. -f1)
    echo "  [jid=${jid} cap=${cap}] ${suite}/tier_c${cap}"
  done
}

submit_suite "gap"   "${BASE}/trace-files/gap"   "trace.gz"           9
submit_suite "gms"   "${BASE}/trace-files/gms"   "champsimtrace.gz"  11
submit_suite "ligra" "${BASE}/trace-files/ligra" "champsimtrace.xz"  18
submit_suite "ml"    "${BASE}/trace-files/ml"    "champsimtrace.gz"  31
