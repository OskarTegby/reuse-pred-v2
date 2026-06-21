#!/usr/bin/env bash
set -euo pipefail
# size_study_srrip_live.sh — History-table size study for SRRIP-Live with TIERED replacement.
#
# LLC policy : SRRIP-Live (champsim_srrip_live)
# Threshold  : SCORING_MODE=5, THD_DOA=6, THD_DEAD=8
# Hist repl  : TIERED, no buffer
# Cap sizes  : 256, 512, 1024, 2048, 4096
#
# Baselines (srrip, ref) already available from threshold study.

BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="size_srrip_live_${DATE}"

LIVE_BASE="SCORING_MODE=5,THD_DOA=6,THD_DEAD=8,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"

total=0

submit() {
  local label="$1" binary="$2" jobname="$3" n="$4" traces="$5" ext="$6"
  shift 6
  local extra="${1:-}"
  mkdir -p "${BASE}/results/${label}" "${BASE}/logs/${LABEL}"
  local jid
  jid=$(qsub -t "1-${n}" -N "${jobname}" \
       -o "${BASE}/logs/${LABEL}/" -e "${BASE}/logs/${LABEL}/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "${BASE}" \
       -v "WARMUP=${W},SIM=${S},TRACE_DIR=${traces},TRACE_EXT=${ext},RUN_LABEL=${label},BINARY=${binary}${extra:+,${extra}}" \
       "${BASE}/scripts/submit/run_cs.sh" \
    | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid} n=${n}] ${label}"
  total=$((total + n))
}

run_suite() {
  local suite="$1" traces="$2" ext="$3" n="$4"
  echo "--- ${suite} (${n} traces) ---"
  for cap in 256 512 1024 2048 4096; do
    submit "${LABEL}/${suite}/tier_c${cap}" champsim_srrip_live "sz_ti${cap}_${suite:0:3}" "${n}" "${traces}" "${ext}" \
      "${LIVE_BASE},REPL_HIST_LLC_CAP=${cap},REPL_HIST_REPL=tiered"
  done
  echo ""
}

echo "=== SRRIP-Live size study: TIERED, no buffer, caps 256–4096 ==="
echo "Label: ${LABEL}"
echo ""

run_suite "dpc3"   "/home/users/shared/traces/dpc3_traces"      "champsimtrace.xz" 95
run_suite "gap"    "${BASE}/trace-files/gap"                     "trace.gz"          9
run_suite "gms"    "${BASE}/trace-files/gms"                     "champsimtrace.gz" 11
run_suite "google" "/home/users/shared/traces/Google_Traces_v2" "champsim.gz"      43
run_suite "ligra"  "${BASE}/trace-files/ligra"                   "champsimtrace.xz" 18
run_suite "ml"     "${BASE}/trace-files/ml"                      "champsimtrace.gz" 31
run_suite "qmm"    "${BASE}/trace-files/QMM"                     "champsimtrace.xz" 45

echo "Total tasks submitted: ${total}"
echo "Results: ${BASE}/results/${LABEL}/"
