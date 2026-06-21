#!/usr/bin/env bash
# Unbounded reference runs for the SRRIP-Live size sensitivity study.
# Uses the same binary and config as size_srrip_live_small/extended but WITHOUT
# REPL_HIST_LLC_CAP — omitting the var leaves the history table in unbounded mode.
set -euo pipefail
BASE=~/ChampSim-dev
W=50000000; S=100000000
LABEL="size_srrip_live_unbound_$(date +%Y%m%d_%H%M)"
LIVE_BASE="SCORING_MODE=5,THD_DOA=6,THD_DEAD=10,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"

mkdir -p "${BASE}/logs/${LABEL}"
echo "Label: ${LABEL}"

submit_suite() {
  local suite="$1" traces="$2" ext="$3" n="$4"
  mkdir -p "${BASE}/results/${LABEL}/${suite}/unbound"
  jid=$(qsub -t "1-${n}" -N "sz_unb_${suite:0:3}" \
    -o "${BASE}/logs/${LABEL}/" -e "${BASE}/logs/${LABEL}/" \
    -l h_rt=24:00:00 -l mem_free=4G -wd "${BASE}" \
    -v "WARMUP=${W},SIM=${S},TRACE_DIR=${traces},TRACE_EXT=${ext},RUN_LABEL=${LABEL}/${suite}/unbound,BINARY=champsim_srrip_live,${LIVE_BASE}" \
    "${BASE}/scripts/submit/run_cs.sh" \
    | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${suite}/unbound (n=${n})"
}

submit_suite "gap"   "${BASE}/trace-files/gap"   "trace.gz"           9
submit_suite "gms"   "${BASE}/trace-files/gms"   "champsimtrace.gz"  11
submit_suite "ligra" "${BASE}/trace-files/ligra" "champsimtrace.xz"  18
submit_suite "ml"    "${BASE}/trace-files/ml"    "champsimtrace.gz"  31
submit_suite "qmm"   "${BASE}/trace-files/QMM"   "champsimtrace.xz"  45
