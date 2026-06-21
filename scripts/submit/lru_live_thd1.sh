#!/bin/bash
set -euo pipefail
# LRU-Live at THD_DOA=1 — exploring whether LRU-Live improves beyond theta=2.
# Per-suite THD_DEAD fixed at Phase 1 optimal (same as llc_thd_phase2.sh).
# Binary: champsim_lru_live  (already on cluster).

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="lru_live_thd1_${DATE}"
THD_DOA=1

declare -A LRU_THD_DEAD=([gap]=2 [gms]=16 [ligra]=16 [ml]=2 [qmm]=2 [dpc3]=8 [google]=16)

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

echo "=== LRU-Live THD_DOA=1 sweep ==="
echo "Label: ${LABEL}"
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
  ll_dead="${LRU_THD_DEAD[$suite]}"
  common="SCORING_MODE=5,THD_DOA=${THD_DOA},THD_DEAD=${ll_dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,LRU_LIVE_HIT_INIT=2"
  submit "${LABEL}/llc/lru_live/doa${THD_DOA}/${suite}" champsim_lru_live \
    "ll1${suite:0:3}" "${n}" "${tdir}" "${ext}" "${common}"
done

echo ""
echo "Arrays: 7 suites"
echo "Total tasks: gap=9 gms=11 ligra=18 ml=31 qmm=45 dpc3=95 google=43 = 252"
