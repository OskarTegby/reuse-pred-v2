#!/usr/bin/env bash
# size_srrip_live_large.sh — Extended size sensitivity study.
#
# For existing suites (gap/gms/ligra/ml/qmm): add caps 8192 and 16384.
# For DPC3: full sweep across all caps (8-16384) plus unbounded reference.
# Same binary/config as size_srrip_live_small/extended:
#   champsim_srrip_live, SCORING_MODE=5, THD_DOA=6, THD_DEAD=10,
#   BHIST_MODE=pc, SRRIP_LIVE_TARGET=llc, REPL_HIST_REPL=tiered
set -euo pipefail
BASE=~/ChampSim-dev
W=50000000; S=100000000
LABEL="size_srrip_live_large_$(date +%Y%m%d_%H%M)"
LIVE_BASE="SCORING_MODE=5,THD_DOA=6,THD_DEAD=10,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"
SHARED=/home/users/shared/traces

mkdir -p "${BASE}/logs/${LABEL}"
echo "Label: ${LABEL}"

submit_caps() {
  local suite="$1" traces="$2" ext="$3" n="$4"
  shift 4
  local caps=("$@")
  for cap in "${caps[@]}"; do
    mkdir -p "${BASE}/results/${LABEL}/${suite}/tier_c${cap}"
    jid=$(qsub -t "1-${n}" -N "sz_${cap}_${suite:0:3}" \
      -o "${BASE}/logs/${LABEL}/" -e "${BASE}/logs/${LABEL}/" \
      -l h_rt=24:00:00 -l mem_free=4G -wd "${BASE}" \
      -v "WARMUP=${W},SIM=${S},TRACE_DIR=${traces},TRACE_EXT=${ext},\
RUN_LABEL=${LABEL}/${suite}/tier_c${cap},BINARY=champsim_srrip_live,\
${LIVE_BASE},REPL_HIST_LLC_CAP=${cap},REPL_HIST_REPL=tiered" \
      "${BASE}/scripts/submit/run_cs.sh" \
      | awk '/Your job/ {print $3}' | cut -d. -f1)
    echo "  [jid=${jid} cap=${cap}] ${suite}/tier_c${cap}  (n=${n})"
  done
}

submit_unbound() {
  local suite="$1" traces="$2" ext="$3" n="$4"
  mkdir -p "${BASE}/results/${LABEL}/${suite}/unbound"
  jid=$(qsub -t "1-${n}" -N "sz_unb_${suite:0:3}" \
    -o "${BASE}/logs/${LABEL}/" -e "${BASE}/logs/${LABEL}/" \
    -l h_rt=24:00:00 -l mem_free=4G -wd "${BASE}" \
    -v "WARMUP=${W},SIM=${S},TRACE_DIR=${traces},TRACE_EXT=${ext},\
RUN_LABEL=${LABEL}/${suite}/unbound,BINARY=champsim_srrip_live,${LIVE_BASE}" \
    "${BASE}/scripts/submit/run_cs.sh" \
    | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${suite}/unbound  (n=${n})"
}

LARGE_CAPS=(8192 16384)
ALL_CAPS=(8 16 32 64 128 256 512 1024 2048 4096 8192 16384)

echo "--- New large caps for existing suites ---"
submit_caps "gap"   "${BASE}/trace-files/gap"   "trace.gz"            9  "${LARGE_CAPS[@]}"
submit_caps "gms"   "${BASE}/trace-files/gms"   "champsimtrace.gz"   11  "${LARGE_CAPS[@]}"
submit_caps "ligra" "${BASE}/trace-files/ligra" "champsimtrace.xz"   18  "${LARGE_CAPS[@]}"
submit_caps "ml"    "${BASE}/trace-files/ml"    "champsimtrace.gz"   31  "${LARGE_CAPS[@]}"
submit_caps "qmm"   "${BASE}/trace-files/QMM"   "champsimtrace.xz"   45  "${LARGE_CAPS[@]}"

echo ""
echo "--- DPC3: full sweep + unbounded ---"
submit_caps   "dpc3" "${SHARED}/dpc3_traces" "champsimtrace.xz" 95  "${ALL_CAPS[@]}"
submit_unbound "dpc3" "${SHARED}/dpc3_traces" "champsimtrace.xz" 95
