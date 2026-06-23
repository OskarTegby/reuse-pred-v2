#!/bin/bash
set -euo pipefail
# Adds the UPDATED set-dueling arm (DUEL_METRIC=latency) to the theta=6 re-eval.
# Runs on champsim_ipv_live_latency (branch duel-miss-latency, commit 7b3bf80).
# Compared against the cfgA / ilB hard-coded arms (same label) and the existing
# hit-based duel (duel_allsuites_20260623_0007).
#   duel_lat : 2-way cfgA-vs-ilB, DUEL_N_SAMPLERS=32, DUEL_METRIC=latency
#              (followers pick the config with the LOWEST total miss latency)

BASE=/home/users/otegby/ChampSim-dev
BIN=champsim_ipv_live_latency
W=50000000; S=100000000
LABEL="eval_theta6_fixed_20260623_1440"   # same label as cfgA/ilB arms

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
DUEL_LAT="DUEL_N_CONFIGS=2,DUEL_N_SAMPLERS=32,IPV_DOA_0=0:1:2:2:2,IPV_DOA_1=0:1:2:2:3,IPV_MOSTLY_DEAD=0:1:1:2:2,DUEL_METRIC=latency"

echo "=== latency-duel arm @ theta=6 (label ${LABEL}) ==="
for suite_spec in "${SUITES[@]}"; do
  IFS=: read -r suite tdir ext n <<< "${suite_spec}"
  dead="${THD_DEAD[$suite]}"
  env="SCORING_MODE=5,THD_DOA=6,THD_DEAD=${dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,${DUEL_LAT}"
  label="${LABEL}/ipv_live/duel_lat/${suite}"
  mkdir -p "${BASE}/results/${label}" "${BASE}/logs/${label}"
  jid=$(qsub -t "1-${n}" -N "e6L${suite:0:2}" \
       -o "${BASE}/logs/${label}/" -e "${BASE}/logs/${label}/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "${BASE}" \
       -v "WARMUP=${W},SIM=${S},TRACE_DIR=${tdir},TRACE_EXT=${ext},RUN_LABEL=${label},BINARY=${BIN},${env}" \
       "${BASE}/scripts/submit/run_cs.sh" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${label} (${n} tasks)"
done
echo "latency-duel arm: 7 suites, 252 tasks"
