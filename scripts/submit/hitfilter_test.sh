#!/bin/bash
set -euo pipefail
# Test the duel hit-class filter (DUEL_HIT_FILTER) at THD_DOA=6.
# Hypothesis: excluding DoA-block hits realigns the duel signal with IPC,
# fixing qmm (where raw-hit count picked ins@2 on 44/45 traces, the wrong way).
#   alive : count only mostly-alive hits (cls==3)
#   live  : count MD+MA hits (cls!=1, exclude DoA)
# qmm = fix target; gap/ligra/ml = must-not-break (already duel wins).

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="hitfilter_test_${DATE}"

declare -A THD_DEAD=([gap]=4 [ligra]=16 [ml]=2 [qmm]=2)
DUEL="DUEL_N_CONFIGS=2,DUEL_N_SAMPLERS=32,IPV_DOA_0=0:1:2:2:2,IPV_DOA_1=0:1:2:2:3,IPV_MOSTLY_DEAD=0:1:1:2:2"

submit() {
  local label="$1" jobname="$2" n="$3" trace_dir="$4" ext="$5" extra="$6"
  mkdir -p "${BASE}/results/${label}" "${BASE}/logs/${label}"
  local jid
  jid=$(qsub -t "1-${n}" -N "${jobname}" \
       -o "${BASE}/logs/${label}/" -e "${BASE}/logs/${label}/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "${BASE}" \
       -v "WARMUP=${W},SIM=${S},TRACE_DIR=${trace_dir},TRACE_EXT=${ext},RUN_LABEL=${label},BINARY=champsim_ipv_live_hf,${extra}" \
       "${BASE}/scripts/submit/run_cs.sh" \
    | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${label} (${n} tasks)"
}

run_one() {  # filter suite tdir ext n
  local filt="$1" suite="$2" tdir="$3" ext="$4" n="$5"
  local dead="${THD_DEAD[$suite]}"
  local env="SCORING_MODE=5,THD_DOA=6,THD_DEAD=${dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,${DUEL},DUEL_HIT_FILTER=${filt}"
  submit "${LABEL}/${filt}/${suite}" "hf${filt:0:1}${suite:0:2}" "${n}" "${tdir}" "${ext}" "${env}"
}

echo "=== Hit-filter test @ THD_DOA=6 ==="
echo "Label: ${LABEL}"
echo "--- alive filter (cls==3 only) ---"
run_one alive qmm   trace-files/QMM            champsimtrace.xz 45
run_one alive gap   trace-files/gap            trace.gz          9
run_one alive ligra trace-files/ligra          champsimtrace.xz 18
run_one alive ml    trace-files/ml             champsimtrace.gz 31
echo "--- live filter (exclude DoA) on qmm only ---"
run_one live  qmm   trace-files/QMM            champsimtrace.xz 45
echo ""
echo "Total tasks: 45+9+18+31 + 45 = 148"
