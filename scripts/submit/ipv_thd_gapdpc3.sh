#!/bin/bash
set -euo pipefail
# IPV-Live dueling threshold sweep — fill the missing suites (gap, dpc3).
# Brings IPV-Live to 7-suite parity with the LRU/SRRIP dueling sweeps.
# Mirrors ipv_thd_sweep_v2/ext: champsim_ipv_live_latency, latency duel
# cfgA(ins@2) vs ilB(ins@3), per-suite THD_DEAD UNCLAMPED (IPV convention).
# doa6 already exists for gap/dpc3 via eval_theta6_fixed/duel_lat, so not re-run.
BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
LABEL="ipv_thd_gapdpc3_20260627"

THDS=(2 4 8 16 20 25 30)
declare -A THD_DEAD=([gap]=4 [dpc3]=4)

SUITES_ORDERED=(
  "gap:trace-files/gap:trace.gz:9"
  "dpc3:/home/users/shared/traces/dpc3_traces:champsimtrace.xz:95"
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

echo "=== IPV-Live gap+dpc3 fill (dueling) ==="
echo "Label: ${LABEL}   thresholds: ${THDS[*]}"; echo ""
total=0
for T in "${THDS[@]}"; do
  echo "--- THD_DOA=${T} ---"
  for spec in "${SUITES_ORDERED[@]}"; do
    IFS=: read -r suite tdir ext n <<< "${spec}"
    dead="${THD_DEAD[$suite]}"
    env="SCORING_MODE=5,THD_DOA=${T},THD_DEAD=${dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,${DUEL}"
    submit "${LABEL}/duel/doa${T}/${suite}" champsim_ipv_live_latency "td${T}${suite:0:2}" "${n}" "${tdir}" "${ext}" "${env}"
    total=$((total+n))
  done
done
echo ""
echo "Total tasks: ${total}"
echo "Results: ${BASE}/results/${LABEL}/"
