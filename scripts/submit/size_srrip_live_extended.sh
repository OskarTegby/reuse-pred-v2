#!/usr/bin/env bash
set -euo pipefail
BASE=~/ChampSim-dev
W=50000000; S=100000000
LABEL="size_srrip_live_ext_$(date +%Y%m%d_%H%M)"
LIVE_BASE="SCORING_MODE=5,THD_DOA=6,THD_DEAD=10,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"

mkdir -p "${BASE}/logs/${LABEL}"
echo "Label: ${LABEL}"

submit_suite() {
  local suite="$1" traces="$2" ext="$3" n="$4"
  shift 4
  local caps=("$@")
  echo "--- ${suite} (${n} traces, caps: ${caps[*]}) ---"
  for cap in "${caps[@]}"; do
    mkdir -p "${BASE}/results/${LABEL}/${suite}/tier_c${cap}"
    jid=$(qsub -t "1-${n}" -N "sz_${cap}_${suite:0:3}" \
      -o "${BASE}/logs/${LABEL}/" -e "${BASE}/logs/${LABEL}/" \
      -l h_rt=24:00:00 -l mem_free=4G -wd "${BASE}" \
      -v "WARMUP=${W},SIM=${S},TRACE_DIR=${traces},TRACE_EXT=${ext},RUN_LABEL=${LABEL}/${suite}/tier_c${cap},BINARY=champsim_srrip_live,${LIVE_BASE},REPL_HIST_LLC_CAP=${cap},REPL_HIST_REPL=tiered" \
      "${BASE}/scripts/submit/run_cs.sh" \
      | awk '/Your job/ {print $3}' | cut -d. -f1)
    echo "  [jid=${jid} cap=${cap}] ${suite}/tier_c${cap}"
  done
}

SMALL_CAPS=(8 16 32 64 128)
ALL_CAPS=(8 16 32 64 128 256 512 1024 2048 4096)

# Small suites: only the new smaller caps (256-4096 already done)
submit_suite "gap"   "${BASE}/trace-files/gap"   "trace.gz"            9  "${SMALL_CAPS[@]}"
submit_suite "gms"   "${BASE}/trace-files/gms"   "champsimtrace.gz"   11  "${SMALL_CAPS[@]}"
submit_suite "ligra" "${BASE}/trace-files/ligra" "champsimtrace.xz"   18  "${SMALL_CAPS[@]}"
submit_suite "ml"    "${BASE}/trace-files/ml"    "champsimtrace.gz"   31  "${SMALL_CAPS[@]}"

# QMM: full sweep across all caps
submit_suite "qmm"   "${BASE}/trace-files/QMM"   "champsimtrace.xz"   45  "${ALL_CAPS[@]}"
