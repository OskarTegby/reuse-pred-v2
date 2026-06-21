#!/bin/bash
set -euo pipefail
# IPV-Live config resubmit with corrected MD vector {0:1:1:2:2} (capped at RRPV=1).
# Replaces the cancelled jobs from lru_ipv_cfg_20260621_0035 which used {0:0:1:2:2}.
#
# Configs (MA fixed at {0,0,0,0,2}; ceilings: DoA=2, MD=1, MA=0):
#   A: DoA={0:1:2:2:2} MD={0:1:1:2:2}  — 2→2 DoA, 2→1 MD (capped)
#   B: DoA={0:0:1:2:2} MD={0:1:1:2:2}  — DoA same first step as MD, MD capped
#   C: DoA={0:1:1:2:2} MD={0:1:1:2:2}  — DoA also capped at RRPV=1

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="ipv_cfg2_${DATE}"
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

echo "=== IPV-Live config resubmit (MD capped at RRPV=1) at THD_DOA=${THD_DOA} ==="
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

  # IPV-Live A: DoA={0:1:2:2:2} MD={0:1:1:2:2} — 2→2 DoA, MD capped at RRPV=1
  submit "${LABEL}/ipv_live/cfgA/${suite}" champsim_ipv_live \
    "ilA${s}" "${n}" "${tdir}" "${ext}" \
    "${base_env},IPV_DOA=0:1:2:2:2,IPV_MOSTLY_DEAD=0:1:1:2:2"

  # IPV-Live B: DoA={0:0:1:2:2} MD={0:1:1:2:2} — DoA earns RRPV=1 on first hit, MD capped
  submit "${LABEL}/ipv_live/cfgB/${suite}" champsim_ipv_live \
    "ilB${s}" "${n}" "${tdir}" "${ext}" \
    "${base_env},IPV_DOA=0:0:1:2:2,IPV_MOSTLY_DEAD=0:1:1:2:2"

  # IPV-Live C: DoA={0:1:1:2:2} MD={0:1:1:2:2} — both DoA and MD capped at RRPV=1
  submit "${LABEL}/ipv_live/cfgC/${suite}" champsim_ipv_live \
    "ilC${s}" "${n}" "${tdir}" "${ext}" \
    "${base_env},IPV_DOA=0:1:1:2:2,IPV_MOSTLY_DEAD=0:1:1:2:2"

  echo ""
done

echo "Arrays: 3 configs * 7 suites = 21 arrays"
echo "Total tasks: ~756"
