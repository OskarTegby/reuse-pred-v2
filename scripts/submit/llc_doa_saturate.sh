#!/bin/bash
set -euo pipefail
# DoA-saturate study: compare DOA_SATURATE_MD=1 vs baseline at the current
# best thresholds (THD_DOA=16, per-suite optimal THD_DEAD from Phase 1).
# Baseline (sat=0) is already available from allsuites_thd_phase2_*.
# Only the sat=1 variant is submitted here.

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="allsuites_doa_saturate_${DATE}"

declare -A SRRIP_THD_DEAD=([gap]=4  [gms]=4  [ligra]=16 [ml]=2  [qmm]=2  [dpc3]=4  [google]=8)
declare -A LRU_THD_DEAD=(  [gap]=2  [gms]=16 [ligra]=16 [ml]=2  [qmm]=2  [dpc3]=8  [google]=16)

submit() {
  local label="$1" binary="$2" jobname="$3" n="$4" trace_dir="$5" ext="$6" extra="$7"
  mkdir -p "${BASE}/results/${label}" "${BASE}/logs/${label}"
  local jid
  jid=$(qsub -t "1-${n}" -N "${jobname}" \
       -o "${BASE}/logs/${label}/" -e "${BASE}/logs/${label}/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "${BASE}" \
       -v "WARMUP=${W},SIM=${S},TRACE_DIR=${trace_dir},TRACE_EXT=${ext},RUN_LABEL=${label},BINARY=${binary},${extra}" \
       "${BASE}/scripts/submit/run_cs.sh" \
    | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${label}"
}

echo "=== DoA-saturate study: DOA_SATURATE_MD=1, THD_DOA=16, per-suite THD_DEAD ==="
echo ""

for suite_spec in \
  "gap:trace-files/gap:trace.gz:9" \
  "gms:trace-files/gms:champsimtrace.gz:11" \
  "ligra:trace-files/ligra:champsimtrace.xz:18" \
  "ml:trace-files/ml:champsimtrace.gz:31" \
  "qmm:trace-files/QMM:champsimtrace.xz:45" \
  "dpc3:/home/users/shared/traces/dpc3_traces:champsimtrace.xz:95" \
  "google:/home/users/shared/traces/Google_Traces_v2:champsim.gz:43"
do
  IFS=: read -r suite tdir ext n <<< "${suite_spec}"
  s="${suite:0:3}"

  sl_dead="${SRRIP_THD_DEAD[$suite]}"
  ll_dead="${LRU_THD_DEAD[$suite]}"

  sl_flags="SCORING_MODE=5,THD_DOA=16,THD_DEAD=${sl_dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,DOA_SATURATE_MD=1"
  ll_flags="SCORING_MODE=5,THD_DOA=16,THD_DEAD=${ll_dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,DOA_SATURATE_MD=1,LRU_LIVE_HIT_INIT=2"

  submit "${LABEL}/llc/srrip_live/${suite}" champsim_srrip_live "ss${s}" "${n}" "${tdir}" "${ext}" "${sl_flags}"
  submit "${LABEL}/llc/lru_live/${suite}"  champsim_lru_live  "ls${s}" "${n}" "${tdir}" "${ext}" "${ll_flags}"
done

echo ""
echo "Label: ${LABEL}"
echo "Arrays: 2 policies * 7 suites = 14 arrays"
echo "Traces: gap=9 gms=11 ligra=18 ml=31 qmm=45 dpc3=95 google=43 (252 per policy, 504 total)"
