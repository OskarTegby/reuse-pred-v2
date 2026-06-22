#!/bin/bash
set -euo pipefail
# Full set-dueling study: 2-way cfgA vs ilB across all 7 suites.
#
# Duel configs (only the DoA IPV differs; MD shared):
#   config_0 = cfgA = {0:1:2:2:2}  (ins@2)
#   config_1 = ilB  = {0:1:2:2:3}  (ins@3 step recovery)
#   DUEL_N_SAMPLERS=32 sampler sets per config (production density).
#
# Matches the ins3_hit reference exactly (THD_DOA=6, per-suite THD_DEAD,
# SCORING_MODE=5, BHIST_MODE=pc, SRRIP_LIVE_TARGET=llc) so the duel is directly
# comparable to the fixed-cfgA and fixed-ilB baselines.

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="duel_allsuites_${DATE}"
THD_DOA=6

declare -A SRRIP_THD_DEAD=([gap]=4 [gms]=4 [ligra]=16 [ml]=2 [qmm]=2 [dpc3]=4 [google]=8)

DUEL_ENV="DUEL_N_CONFIGS=2,DUEL_N_SAMPLERS=32,IPV_DOA_0=0:1:2:2:2,IPV_DOA_1=0:1:2:2:3,IPV_MOSTLY_DEAD=0:1:1:2:2"

submit() {
  local label="$1" binary="$2" jobname="$3" n="$4" trace_dir="$5" ext="$6"
  shift 6
  local extra="${1:-}"
  mkdir -p "${BASE}/results/${label}" "${BASE}/logs/${label}"
  local jid
  jid=$(qsub -t "1-${n}" -N "${jobname}" \
       -o "${BASE}/logs/${label}/" -e "${BASE}/logs/${label}/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "${BASE}" \
       -v "WARMUP=${W},SIM=${S},TRACE_DIR=${trace_dir},TRACE_EXT=${ext},RUN_LABEL=${label},BINARY=${binary}${extra:+,${extra}}" \
       "${BASE}/scripts/submit/run_cs.sh" \
    | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${label} (${n} tasks)"
}

submit_duel_suites() {
  for suite_spec in "$@"; do
    IFS=: read -r suite tdir ext n <<< "${suite_spec}"
    local s="${suite:0:3}"
    local sl_dead="${SRRIP_THD_DEAD[$suite]}"
    local base_env="SCORING_MODE=5,THD_DOA=${THD_DOA},THD_DEAD=${sl_dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"
    submit "${LABEL}/ipv_live/duel/${suite}" champsim_ipv_live "dl${s}" \
           "${n}" "${tdir}" "${ext}" "${base_env},${DUEL_ENV}"
  done
}

PRIO_SUITES=(
  "gap:trace-files/gap:trace.gz:9"
  "ligra:trace-files/ligra:champsimtrace.xz:18"
  "gms:trace-files/gms:champsimtrace.gz:11"
)
REST_SUITES=(
  "ml:trace-files/ml:champsimtrace.gz:31"
  "qmm:trace-files/QMM:champsimtrace.xz:45"
  "dpc3:/home/users/shared/traces/dpc3_traces:champsimtrace.xz:95"
  "google:/home/users/shared/traces/Google_Traces_v2:champsim.gz:43"
)

echo "=== Full set-dueling study (2-way cfgA vs ilB), THD_DOA=${THD_DOA} ==="
echo "Label: ${LABEL}"
echo "Duel env: ${DUEL_ENV}"
echo ""
echo "--- Phase 1: priority suites (gap, ligra, gms) ---"
submit_duel_suites "${PRIO_SUITES[@]}"
echo ""
echo "--- Phase 2: remaining suites (ml, qmm, dpc3, google) ---"
submit_duel_suites "${REST_SUITES[@]}"
echo ""
echo "Arrays: 7 suites.  Total tasks: 9+18+11+31+45+95+43 = 252"
