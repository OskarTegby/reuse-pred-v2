#!/bin/bash
set -euo pipefail
# LRU-Live-inspired config sweep at THD_DOA=6.
#
# All classes insert at RRPV=2 (no preferential insertion). Distinction is hit promotion:
#   DoA: 2→2 (no reward — LRU-Live mirror)
#   MD:  2→1 (one step — LRU-Live mirror)
#   MA:  2→0 (full on first hit — same as plain SRRIP)
#
# SRRIP-Live configs (A is the pure LRU-Live mirror / default):
#   A: DoA(hit=2) MD(hit=1)  — LRU-Like: no DoA reward, one-step MD
#   B: DoA(hit=1) MD(hit=1)  — mild DoA promotion (DoA earns RRPV=1, same as MD's first hit)
#   C: DoA(hit=2) MD(hit=0)  — strict DoA, MD gets full on first hit
#
# IPV-Live configs (MA fixed at {0,0,0,0,2}; DoA/MD vectors in [hit@0,..,hit@3,insert] format):
#   A: DoA={0:1:2:2:2} MD={0:0:1:2:2}  — 2→2 DoA, 2→1→0 MD (default / LRU-Like)
#   B: DoA={0:0:1:2:2} MD={0:0:1:2:2}  — DoA gets same first-hit step as MD (2→1)
#   C: DoA={0:1:2:2:2} MD={0:0:0:2:2}  — 2→2 DoA, MD full on second hit from aged pos
#   (note: ':' separator avoids qsub -v comma-parsing conflict)
#
# THD_DEAD fixed at Phase 1 per-suite optimal. THD_DOA=6.

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="lru_ipv_cfg_${DATE}"
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

echo "=== LRU-Live/IPV config sweep at THD_DOA=${THD_DOA} ==="
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

  # SRRIP-Live A: DoA(2→2) MD(2→1) — LRU-Like mirror, all defaults
  submit "${LABEL}/srrip_live/cfgA/${suite}" champsim_srrip_live \
    "slA${s}" "${n}" "${tdir}" "${ext}" \
    "${base_env},SRRIP_DOA_INS_RRPV=2,SRRIP_DOA_HIT_RRPV=2,SRRIP_MD_INS_RRPV=2,SRRIP_MD_HIT_RRPV=1"

  # SRRIP-Live B: DoA(2→1) MD(2→1) — mild DoA promotion
  submit "${LABEL}/srrip_live/cfgB/${suite}" champsim_srrip_live \
    "slB${s}" "${n}" "${tdir}" "${ext}" \
    "${base_env},SRRIP_DOA_INS_RRPV=2,SRRIP_DOA_HIT_RRPV=1,SRRIP_MD_INS_RRPV=2,SRRIP_MD_HIT_RRPV=1"

  # SRRIP-Live C: DoA(2→2) MD(2→0) — strict DoA, MD full on first hit
  submit "${LABEL}/srrip_live/cfgC/${suite}" champsim_srrip_live \
    "slC${s}" "${n}" "${tdir}" "${ext}" \
    "${base_env},SRRIP_DOA_INS_RRPV=2,SRRIP_DOA_HIT_RRPV=2,SRRIP_MD_INS_RRPV=2,SRRIP_MD_HIT_RRPV=0"

  # IPV-Live A: DoA={0:1:2:2:2} MD={0:0:1:2:2} — 2→2 DoA, 2→1→0 MD (default)
  submit "${LABEL}/ipv_live/cfgA/${suite}" champsim_ipv_live \
    "ilA${s}" "${n}" "${tdir}" "${ext}" \
    "${base_env},IPV_DOA=0:1:2:2:2,IPV_MOSTLY_DEAD=0:1:1:2:2"

  # IPV-Live B: DoA={0:0:1:2:2} MD={0:0:1:2:2} — DoA same first-hit step as MD (2→1)
  submit "${LABEL}/ipv_live/cfgB/${suite}" champsim_ipv_live \
    "ilB${s}" "${n}" "${tdir}" "${ext}" \
    "${base_env},IPV_DOA=0:0:1:2:2,IPV_MOSTLY_DEAD=0:1:1:2:2"

  # IPV-Live C: DoA={0:1:1:2:2} MD={0:0:1:2:2} — DoA earns RRPV=1 on first hit but capped there
  submit "${LABEL}/ipv_live/cfgC/${suite}" champsim_ipv_live \
    "ilC${s}" "${n}" "${tdir}" "${ext}" \
    "${base_env},IPV_DOA=0:1:1:2:2,IPV_MOSTLY_DEAD=0:1:1:2:2"

  echo ""
done

echo "Arrays: 6 configs * 7 suites = 42 arrays"
echo "Total tasks: ~1512"
