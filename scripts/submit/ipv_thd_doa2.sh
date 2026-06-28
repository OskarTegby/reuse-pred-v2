#!/bin/bash
set -euo pipefail
# IPV-Live dueling threshold sweep — fill the missing aggressive point (THD_DOA=2).
# Mirrors ipv_thd_sweep_v2/ext exactly (duel arm only) so doa2 slots into that curve:
#   binary champsim_ipv_live_latency, latency duel cfgA(ins@2) vs ilB(ins@3),
#   per-suite THD_DEAD UNCLAMPED (same convention as the existing doa4/8/16/20/25/30).
BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
LABEL="ipv_thd_doa2_20260627"

THDS=(2)
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

DUEL="DUEL_N_CONFIGS=2,DUEL_N_SAMPLERS=32,IPV_DOA_0=0:1:2:2:2,IPV_DOA_1=0:1:2:2:3,IPV_MOSTLY_DEAD=0:1:1:2:2,DUEL_METRIC=latency"

echo "=== IPV-Live doa2 fill (dueling) ==="
echo "Label: ${LABEL}"; echo ""
total=0
for T in "${THDS[@]}"; do
  echo "--- THD_DOA=${T} ---"
  for spec in "${SUITES_ORDERED[@]}"; do
    IFS=: read -r suite tdir ext n <<< "${spec}"
    dead="${THD_DEAD[$suite]}"
    jsfx="${T}${suite:0:2}"
    env="SCORING_MODE=5,THD_DOA=${T},THD_DEAD=${dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,${DUEL}"
    submit "${LABEL}/duel/doa${T}/${suite}" champsim_ipv_live_latency "tdl${jsfx}" "${n}" "${tdir}" "${ext}" "${env}"
    total=$((total+n))
  done
done
echo ""
echo "Total tasks: ${total}"
echo "Results: ${BASE}/results/${LABEL}/"
