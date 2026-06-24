#!/bin/bash
set -euo pipefail
# LRU-Live canonical theta=6 study — three arms across all 7 suites.
# No bypass: cfgB inserts DoA at LRU position (rank 0), not bypass-priority.
#   cfgA : 2n3  — DoA at 2N/3 from MRU (current default)
#   cfgB : lru  — DoA at LRU position (rank 0, evicted on next fill)
#   duel : DUEL_METRIC=latency, cfgA vs cfgB
#
# Binary: champsim_lru_live (built duel-miss-latency branch, 2026-06-24)
# Baseline for comparison: results/baselines/lru

BASE=/home/users/otegby/ChampSim-dev
BIN=champsim_lru_live
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="lru_live_theta6_${DATE}"

declare -A THD_DEAD=([gap]=4 [ligra]=16 [gms]=4 [ml]=2 [qmm]=2 [dpc3]=4 [google]=8)

SUITES=(
  "gap:trace-files/gap:trace.gz:9"
  "ligra:trace-files/ligra:champsimtrace.xz:18"
  "gms:trace-files/gms:champsimtrace.gz:11"
  "ml:trace-files/ml:champsimtrace.gz:31"
  "qmm:trace-files/QMM:champsimtrace.xz:45"
  "dpc3:/home/users/shared/traces/dpc3_traces:champsimtrace.xz:95"
  "google:/home/users/shared/traces/Google_Traces_v2:champsim.gz:43"
)

CFGA="LRU_LIVE_DOA_INS=2n3"
CFGB="LRU_LIVE_DOA_INS=lru"
DUEL="LRU_LIVE_DOA_INS=2n3,LRU_LIVE_DOA_INS_B=lru,DUEL_N_SAMPLERS=32,DUEL_METRIC=latency"

submit() {
  local label="$1" jobname="$2" n="$3" tdir="$4" ext="$5" extra="$6"
  mkdir -p "${BASE}/results/${label}" "${BASE}/logs/${label}"
  local jid
  jid=$(qsub -t "1-${n}" -N "${jobname}" \
       -o "${BASE}/logs/${label}/" -e "${BASE}/logs/${label}/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "${BASE}" \
       -v "WARMUP=${W},SIM=${S},TRACE_DIR=${tdir},TRACE_EXT=${ext},RUN_LABEL=${label},BINARY=${BIN},${extra}" \
       "${BASE}/scripts/submit/run_cs.sh" \
    | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${label} (${n} tasks)"
}

echo "=== LRU-Live theta=6 study (cfgA/cfgB/duel, all 7 suites) ==="
echo "Label: ${LABEL}"
echo ""

for suite_spec in "${SUITES[@]}"; do
  IFS=: read -r suite tdir ext n <<< "${suite_spec}"
  dead="${THD_DEAD[$suite]}"
  s="${suite:0:2}"
  base_env="SCORING_MODE=5,THD_DOA=6,THD_DEAD=${dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"
  echo "--- ${suite} ---"
  submit "${LABEL}/cfgA/${suite}" "lA${s}" "${n}" "${tdir}" "${ext}" "${base_env},${CFGA}"
  submit "${LABEL}/cfgB/${suite}" "lB${s}" "${n}" "${tdir}" "${ext}" "${base_env},${CFGB}"
  submit "${LABEL}/duel/${suite}" "lD${s}" "${n}" "${tdir}" "${ext}" "${base_env},${DUEL}"
done

echo ""
echo "Arrays: 3 arms * 7 suites = 21"
echo "Total tasks: 3 * (9+18+11+31+45+95+43) = 756"
