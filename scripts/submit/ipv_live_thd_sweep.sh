#!/bin/bash
set -euo pipefail
# IPV-Live DoA threshold sweep.
#
# Sweeps THD_DOA in {2,4,6,8,16,20,25,30} with THD_DEAD fixed at a single
# best-guess value of 10 for all suites.  A follow-up MD sweep (vary THD_DEAD
# at the optimal THD_DOA per suite) will be run once results are in.
#
# No baselines submitted — reuse srrip/ from allsuites_thd_phase1_20260617_0020.
# Binary: champsim_ipv_live  (already on cluster from Phase 1).
# SCORING_MODE=5, BHIST_MODE=pc, SRRIP_LIVE_TARGET=llc (LLC-only guidance).

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="ipv_live_thd_sweep_${DATE}"
THD_DEAD=10

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

# Submission order: highest-probability thresholds first based on SRRIP-Live study.
# SRRIP-Live optima: DPC3=25, GMS=30, Ligra=25; ML=16, QMM=16; GAP=6.
# IPV-Live is more punishing for false positives (high-RRPV insertion), so
# stricter (higher) thresholds are more likely to win — start at 25/30, then 16/20,
# then lower values.

echo "=== IPV-Live THD_DOA sweep: {25,30,16,20,8,6,4,2}, THD_DEAD=${THD_DEAD} ==="
echo "Label: ${LABEL}"
echo ""

for thd_doa in 25 30 16 20 8 6 4 2; do
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
    common="SCORING_MODE=5,THD_DOA=${thd_doa},THD_DEAD=${THD_DEAD},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"
    submit "${LABEL}/llc/ipv_live/doa${thd_doa}/${suite}" champsim_ipv_live \
      "il${thd_doa}${s}" "${n}" "${tdir}" "${ext}" "${common}"
  done
  echo ""
done

echo "Arrays: 8 (doa) * 7 (suites) = 56 arrays"
echo "Traces/suite: gap=9 gms=11 ligra=18 ml=31 qmm=45 dpc3=95 google=43"
echo "Total tasks: ~2016"
