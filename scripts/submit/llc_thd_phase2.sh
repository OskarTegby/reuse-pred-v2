#!/bin/bash
set -euo pipefail
# Phase 2 threshold study: sweep THD_DOA with per-suite optimal THD_DEAD from Phase 1.
# LLC only (SRRIP_LIVE_TARGET=llc), SCORING_MODE=5, BHIST_MODE=pc.
# Policies: srrip_live, lru_live. No STLB section (deferred).
# No baselines — reuse lru/ and srrip/ from allsuites_thd_phase1_*.
#
# Submission order (most likely optimal first): 6, 8, 4, 16, 2
# Rationale: prior mode-5 optimum was θ_doa=6; mode-5 scoring bias favours
# higher scores, so 8 is checked before 4; extremes (16, 2) come last.
#
# Per-suite optimal THD_DEAD from Phase 1 (SRRIP-Live):
#   gap=4  gms=4  ligra=16  ml=2  qmm=2  dpc3=4  google=8
# Per-suite optimal THD_DEAD from Phase 1 (LRU-Live):
#   gap=2  gms=16  ligra=16  ml=2  qmm=2  dpc3=8  google=16

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="allsuites_thd_phase2_${DATE}"

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

echo "=== Phase 2: sweep THD_DOA, per-suite THD_DEAD fixed at Phase 1 optimal ==="
echo "=== Submission order: 6, 8, 4, 16, 2 ==="
echo ""

for thd_doa in 6 8 4 16 2; do
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
echo "Arrays: 5 (doa values) * 2 (policies) * 7 (suites) = 70 arrays"
echo "Traces/suite: gap=9 gms=11 ligra=18 ml=31 qmm=45 dpc3=95 google=43 (252 per config)"
echo "Total tasks: 70 * 252 / 7 = ~2520"
