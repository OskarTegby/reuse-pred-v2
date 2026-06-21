#!/bin/bash
set -euo pipefail
# Phase 1 threshold study: sweep THD_DEAD with fixed THD_DOA=6, SCORING_MODE=5.
# Covers all 7 suites: GAP, GMS, Ligra, ML, QMM, DPC3, Google.
# LLC section: SRRIP_LIVE_TARGET=llc, STLB stays on default LRU.
# STLB section: SRRIP_LIVE_TARGET=stlb, LLC falls back to plain policy.
# Phase 2 (sweep THD_DOA) runs after optimal THD_DEAD is identified.

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="allsuites_thd_phase1_${DATE}"

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

THD_DOA_FIXED=6

echo "=== Baselines (LRU, SRRIP — once per suite) ==="

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
  submit "${LABEL}/lru/${suite}"   champsim_lru   "bl_l_${s}" "${n}" "${tdir}" "${ext}"
  submit "${LABEL}/srrip/${suite}" champsim_srrip "bl_s_${s}" "${n}" "${tdir}" "${ext}"
done

echo ""
echo "=== LLC Phase 1: sweep THD_DEAD, fixed THD_DOA=${THD_DOA_FIXED}, SCORING_MODE=5 ==="

for thd_dead in 4 6 8 10 12 16; do
  echo "--- THD_DEAD=${thd_dead} ---"
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
    common="SCORING_MODE=5,THD_DOA=${THD_DOA_FIXED},THD_DEAD=${thd_dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"

    submit "${LABEL}/llc/srrip_live/thd${thd_dead}/${suite}" champsim_srrip_live "sl${thd_dead}${s}" "${n}" "${tdir}" "${ext}" \
      "${common}"
    submit "${LABEL}/llc/lru_live/thd${thd_dead}/${suite}"  champsim_lru_live  "ll${thd_dead}${s}" "${n}" "${tdir}" "${ext}" \
      "${common},LRU_LIVE_HIT_INIT=2"
    submit "${LABEL}/llc/ipv_live/thd${thd_dead}/${suite}"  champsim_ipv_live  "il${thd_dead}${s}" "${n}" "${tdir}" "${ext}" \
      "${common}"
  done
done

echo ""
echo "=== STLB Phase 1: sweep THD_DEAD, fixed THD_DOA=${THD_DOA_FIXED}, SCORING_MODE=5 ==="

for thd_dead in 4 6 8 10 12 16; do
  echo "--- THD_DEAD=${thd_dead} ---"
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
    common="SCORING_MODE=5,THD_DOA=${THD_DOA_FIXED},THD_DEAD=${thd_dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=stlb"

    submit "${LABEL}/stlb/srrip_live/thd${thd_dead}/${suite}" champsim_stlb_srrip_live "ss${thd_dead}${s}" "${n}" "${tdir}" "${ext}" \
      "${common}"
    submit "${LABEL}/stlb/lru_live/thd${thd_dead}/${suite}"  champsim_stlb_lru_live  "ls${thd_dead}${s}" "${n}" "${tdir}" "${ext}" \
      "${common},LRU_LIVE_HIT_INIT=2"
    submit "${LABEL}/stlb/ipv_live/thd${thd_dead}/${suite}"  champsim_stlb_ipv_live  "is${thd_dead}${s}" "${n}" "${tdir}" "${ext}" \
      "${common}"
  done
done

echo ""
echo "Label: ${LABEL}"
echo "Arrays: 2 (baselines) + 6*3 (LLC) + 6*3 (STLB) = 38 configs x 7 suites = 266 arrays"
echo "Traces/suite: gap=9 gms=11 ligra=18 ml=31 qmm=45 dpc3=95 google=43 (total=252 per config)"
echo "Total jobs: 266 * 252 / 7 = estimated ~9576 jobs (varies by suite)"
