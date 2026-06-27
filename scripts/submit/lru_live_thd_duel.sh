#!/bin/bash
set -euo pipefail
# LRU-Live DoA threshold sweep WITH set dueling.
#
# Tests the hypothesis that set dueling lets LRU-Live tolerate a more aggressive
# THD_DOA than the fixed-config optimum: on sets where aggressive DoA insertion
# hurts, the duel falls back to the gentler arm, bounding the downside.
#
# Duel: LRU_LIVE_DOA_INS=2n3 (gentle) vs _B=lru (aggressive), latency metric, 32 samplers.
# THD_DEAD = min(per-suite, THD_DOA)  (clamped so the mostly-dead tier stays valid).
# Anchor THD_DOA=6 already exists (lru_live_theta6/duel) — not re-run here.
#
# Staged: edit THDS per group.
#   group 1: (2 4)        group 2: (8 16 20)        group 3: (25 30)
#
# Stable label so all groups accumulate in one results dir.
BASE=/home/users/otegby/ChampSim-dev
BIN=champsim_lru_live
W=50000000; S=100000000
LABEL="lru_live_thd_duel_20260627"

THDS=(2 4)

# per-suite mostly-dead threshold (same map as lru_live_theta6); clamped to <= THD_DOA below
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

echo "=== LRU-Live DoA threshold sweep (dueling) ==="
echo "Label: ${LABEL}   thresholds: ${THDS[*]}"
echo ""
total=0
for T in "${THDS[@]}"; do
  echo "--- THD_DOA=${T} ---"
  for spec in "${SUITES[@]}"; do
    IFS=: read -r suite tdir ext n <<< "${spec}"
    d="${DEAD[$suite]}"
    dead=$(( d < T ? d : T ))   # clamp THD_DEAD <= THD_DOA
    s2="${suite:0:2}"
    env="SCORING_MODE=5,THD_DOA=${T},THD_DEAD=${dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,${DUEL}"
    submit "${LABEL}/duel/doa${T}/${suite}" "ld${T}${s2}" "${n}" "${tdir}" "${ext}" "${env}"
    total=$((total+n))
  done
done
echo ""
echo "Total tasks: ${total}"
echo "Results: ${BASE}/results/${LABEL}/"
