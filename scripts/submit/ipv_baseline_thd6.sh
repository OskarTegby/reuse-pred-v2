#!/bin/bash
set -euo pipefail
# IPV-Live original vectors at THD_DOA=6 — baseline for comparison against new configs.
#
# Original vectors (before LRU-Live-inspired redesign):
#   DoA={0:0:1:2:3}  insert@3, progressive to RRPV=0
#   MD= {0:0:0:2:3}  insert@3, hit@3→2, hit@2→0
#   MA= {0:0:0:0:2}  unchanged (default)
#
# THD_DEAD fixed at Phase 1 per-suite optimal. THD_DOA=6.

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="ipv_orig_thd6_${DATE}"
THD_DOA=6

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

echo "=== IPV-Live original vectors at THD_DOA=${THD_DOA} ==="
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
  s="${suite:0:3}"
  sl_dead="${SRRIP_THD_DEAD[$suite]}"
  base_env="SCORING_MODE=5,THD_DOA=${THD_DOA},THD_DEAD=${sl_dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"

  submit "${LABEL}/ipv_live/orig/${suite}" champsim_ipv_live \
    "ilo${s}" "${n}" "${tdir}" "${ext}" \
    "${base_env},IPV_DOA=0:0:1:2:3,IPV_MOSTLY_DEAD=0:0:0:2:3"

  echo ""
done

echo "Arrays: 7 suites = 7 arrays"
echo "Total tasks: ~252"
