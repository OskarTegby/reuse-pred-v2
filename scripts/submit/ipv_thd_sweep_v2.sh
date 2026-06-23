#!/bin/bash
set -euo pipefail
# IPV-Live threshold sweep v2 — first complete THD_DOA sweep for IPV-Live.
# Three arms over grid {2,4,8,16}:
#   ins2     : fixed cfgA {0:1:2:2:2}  on champsim_ipv_live_fixed
#   ins3     : fixed ilB  {0:1:2:2:3}  on champsim_ipv_live_fixed
#   duel_lat : 2-way cfgA-vs-ilB, DUEL_METRIC=latency, on champsim_ipv_live_latency
#
# Suites: ligra/ml/gms/google/qmm (those showing regression or duel weakness).
# Gap and dpc3 excluded: gap is a clean ins@3 winner; dpc3 deferred to later.
# Per-suite THD_DEAD matches the ins3_hit reference.
# Submission order: ligra first (largest ins@2 vs ins@3 swing).

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="ipv_thd_sweep_v2_${DATE}"

THDS=(2 4 8 16)
declare -A THD_DEAD=([ligra]=16 [ml]=2 [gms]=4 [google]=8 [qmm]=2)

SUITES_ORDERED=(
  "ligra:trace-files/ligra:champsimtrace.xz:18"
  "ml:trace-files/ml:champsimtrace.gz:31"
  "gms:trace-files/gms:champsimtrace.gz:11"
  "google:/home/users/shared/traces/Google_Traces_v2:champsim.gz:43"
  "qmm:trace-files/QMM:champsimtrace.xz:45"
)

submit() {
  local label="$1" bin="$2" jobname="$3" n="$4" tdir="$5" ext="$6" extra="$7"
  mkdir -p "${BASE}/results/${label}" "${BASE}/logs/${label}"
  local jid
  jid=$(qsub -t "1-${n}" -N "${jobname}" \
       -o "${BASE}/logs/${label}/" -e "${BASE}/logs/${label}/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "${BASE}" \
       -v "WARMUP=${W},SIM=${S},TRACE_DIR=${tdir},TRACE_EXT=${ext},RUN_LABEL=${label},BINARY=${bin},${extra}" \
       "${BASE}/scripts/submit/run_cs.sh" \
    | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${label} (${n} tasks)"
}

INS2="IPV_DOA=0:1:2:2:2,IPV_MOSTLY_DEAD=0:1:1:2:2"
INS3="IPV_DOA=0:1:2:2:3,IPV_MOSTLY_DEAD=0:1:1:2:2"
DUEL="DUEL_N_CONFIGS=2,DUEL_N_SAMPLERS=32,IPV_DOA_0=0:1:2:2:2,IPV_DOA_1=0:1:2:2:3,IPV_MOSTLY_DEAD=0:1:1:2:2,DUEL_METRIC=latency"

echo "=== IPV-Live threshold sweep v2 (ins2/ins3/duel_lat), grid {2,4,8,16} ==="
echo "Label: ${LABEL}"
echo ""

for T in "${THDS[@]}"; do
  echo "--- THD_DOA=${T} ---"
  for suite_spec in "${SUITES_ORDERED[@]}"; do
    IFS=: read -r suite tdir ext n <<< "${suite_spec}"
    dead="${THD_DEAD[$suite]}"
    base_env="SCORING_MODE=5,THD_DOA=${T},THD_DEAD=${dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"
    jsfx="${T}${suite:0:2}"
    submit "${LABEL}/ins2/doa${T}/${suite}" champsim_ipv_live_fixed  "ti2${jsfx}" "${n}" "${tdir}" "${ext}" "${base_env},${INS2}"
    submit "${LABEL}/ins3/doa${T}/${suite}" champsim_ipv_live_fixed  "ti3${jsfx}" "${n}" "${tdir}" "${ext}" "${base_env},${INS3}"
    submit "${LABEL}/duel/doa${T}/${suite}" champsim_ipv_live_latency "tdl${jsfx}" "${n}" "${tdir}" "${ext}" "${base_env},${DUEL}"
  done
done

echo ""
echo "Arrays: 3 arms * 4 thresholds * 5 suites = 60"
echo "Total tasks: 3 * 4 * (18+31+11+43+45) = 1776"
