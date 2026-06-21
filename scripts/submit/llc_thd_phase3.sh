#!/bin/bash
set -euo pipefail
# Phase 3 threshold study: extend THD_DOA sweep to {20, 25, 30}.
# With current '>' comparison and delta=5 from MA state, these correspond to
# 5, 6, and 7 consecutive DoA evictions from MA state (equivalent to doa25,
# doa30, doa35 under '>=' semantics).
#
# Per-suite optimal THD_DEAD fixed at Phase 1 winners (same as Phase 2).
# No baselines needed — reuse srrip/ from allsuites_thd_phase1_*.
#
# Submission order: 20, 25, 30 (monotonic trend still rising at doa16, so
# doa20 is the most likely next winner).

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="allsuites_thd_phase3_${DATE}"

# Per-suite optimal THD_DEAD from Phase 1
declare -A SRRIP_THD_DEAD=([gap]=4  [gms]=4  [ligra]=16 [ml]=2  [qmm]=2  [dpc3]=4  [google]=8)
declare -A LRU_THD_DEAD=(  [gap]=2  [gms]=16 [ligra]=16 [ml]=2  [qmm]=2  [dpc3]=8  [google]=16)

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
  echo "  [jid=${jid}] ${label}"
}

echo "=== Phase 3: THD_DOA in {20,25,30} (5,6,7 MA evictions with '>' comparison) ==="
echo "=== Submission order: 20, 25, 30 ==="
echo ""

for thd_doa in 20 25 30; do
  echo "--- THD_DOA=${thd_doa} ---"
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

    common_sl="SCORING_MODE=5,THD_DOA=${thd_doa},THD_DEAD=${sl_dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"
    common_ll="SCORING_MODE=5,THD_DOA=${thd_doa},THD_DEAD=${ll_dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"

    submit "${LABEL}/llc/srrip_live/doa${thd_doa}/${suite}" champsim_srrip_live \
      "sl${thd_doa}${s}" "${n}" "${tdir}" "${ext}" "${common_sl}"
    submit "${LABEL}/llc/lru_live/doa${thd_doa}/${suite}"  champsim_lru_live  \
      "ll${thd_doa}${s}" "${n}" "${tdir}" "${ext}" "${common_ll},LRU_LIVE_HIT_INIT=2"
  done
  echo ""
done

echo "Label: ${LABEL}"
echo "Arrays: 3 (doa values) * 2 (policies) * 7 (suites) = 42 arrays"
echo "Traces/suite: gap=9 gms=11 ligra=18 ml=31 qmm=45 dpc3=95 google=43 (252 per config)"
echo "Total tasks: 42 * 252 / 7 = ~1512"
