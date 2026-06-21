#!/bin/bash
set -euo pipefail
# SRRIP-Live DoA threshold sweep with full-promotion fix (SRRIP_DOA_HIT_RRPV=0 default).
#
# Binary: champsim_srrip_live rebuilt with DoA-hit RRPV=0 (mirrors LRU-Live MRU promotion).
# Per-suite THD_DEAD fixed at Phase 1 optimal (same as llc_thd_phase2.sh).
# Sweep THD_DOA in {25,30,16,20,8,6,4,2} — highest-probability thresholds first.
#
# No extra env var needed: new default is SRRIP_DOA_HIT_RRPV=0.
#
# Per-suite optimal THD_DEAD from Phase 1 (SRRIP-Live):
#   gap=4  gms=4  ligra=16  ml=2  qmm=2  dpc3=4  google=8

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="srrip_live_fix_${DATE}"

declare -A SRRIP_THD_DEAD=([gap]=4 [gms]=4 [ligra]=16 [ml]=2 [qmm]=2 [dpc3]=4 [google]=8)

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

echo "=== SRRIP-Live fix sweep: THD_DOA in {25,30,16,20,8,6,4,2}, SRRIP_DOA_HIT_RRPV=0 ==="
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
    sl_dead="${SRRIP_THD_DEAD[$suite]}"
    common="SCORING_MODE=5,THD_DOA=${thd_doa},THD_DEAD=${sl_dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"
    submit "${LABEL}/llc/srrip_live/doa${thd_doa}/${suite}" champsim_srrip_live \
      "sf${thd_doa}${s}" "${n}" "${tdir}" "${ext}" "${common}"
  done
  echo ""
done

echo "Arrays: 8 (doa) * 7 (suites) = 56 arrays"
echo "Traces/suite: gap=9 gms=11 ligra=18 ml=31 qmm=45 dpc3=95 google=43"
echo "Total tasks: 56 * 252 / 7 = ~2016"
