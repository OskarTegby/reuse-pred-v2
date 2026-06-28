#!/bin/bash
set -euo pipefail
# SRRIP-Live DoA threshold sweep WITH set dueling.
#
# Mirrors the established SRRIP-Live duel (srrip_live_theta6): PSEL hit-count duel
# between cfgA (ins@2 hit@2, near-SRRIP) and cfgB (ins@3 hit@0, aggressive), 32 samplers.
# Sweeps THD_DOA; THD_DEAD = min(per-suite, THD_DOA) (clamped, as in the LRU sweep).
# Anchor THD_DOA=6 already exists (srrip_live_theta6/duel) — not re-run here.
#
# NOTE: SRRIP-Live duels on hit-count (PSEL), whereas the LRU/IPV sweeps used the
# miss-latency metric. This matches each policy's established config.
#
# Stable label so all groups accumulate in one results dir. Edit THDS to stage.
BASE=/home/users/otegby/ChampSim-dev
BIN=champsim_srrip_live
W=50000000; S=100000000
LABEL="srrip_live_thd_duel_20260627"

THDS=(2 4 8 16 20 25 30)

declare -A DEAD=([gap]=4 [ligra]=16 [gms]=4 [ml]=2 [qmm]=2 [dpc3]=4 [google]=8)

SUITES=(
  "gap:trace-files/gap:trace.gz:9"
  "ligra:trace-files/ligra:champsimtrace.xz:18"
  "gms:trace-files/gms:champsimtrace.gz:11"
  "ml:trace-files/ml:champsimtrace.gz:31"
  "qmm:trace-files/QMM:champsimtrace.xz:45"
  "dpc3:/home/users/shared/traces/dpc3_traces:champsimtrace.xz:95"
  "google:/home/users/shared/traces/Google_Traces_v2:champsim.gz:43"
)

DUEL="SRRIP_DOA_INS_RRPV=2,SRRIP_DOA_HIT_RRPV=2,SRRIP_DOA_INS_RRPV_B=3,SRRIP_DOA_HIT_RRPV_B=0,DUEL_N_SAMPLERS=32"

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

echo "=== SRRIP-Live DoA threshold sweep (dueling) ==="
echo "Label: ${LABEL}   thresholds: ${THDS[*]}"
echo ""
total=0
for T in "${THDS[@]}"; do
  echo "--- THD_DOA=${T} ---"
  for spec in "${SUITES[@]}"; do
    IFS=: read -r suite tdir ext n <<< "${spec}"
    d="${DEAD[$suite]}"
    dead=$(( d < T ? d : T ))
    s2="${suite:0:2}"
    env="SCORING_MODE=5,THD_DOA=${T},THD_DEAD=${dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,${DUEL}"
    submit "${LABEL}/duel/doa${T}/${suite}" "sd${T}${s2}" "${n}" "${tdir}" "${ext}" "${env}"
    total=$((total+n))
  done
done
echo ""
echo "Total tasks: ${total}"
echo "Results: ${BASE}/results/${LABEL}/"
