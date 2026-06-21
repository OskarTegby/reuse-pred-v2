#!/bin/bash
set -euo pipefail
# Insert@3 hit-promotion sweep at THD_DOA=6.
#
# Fixes the original false-positive problem (insert@3, hit→2 oscillates)
# by keeping insert@3 (bypass benefit) but varying the hit target.
#
# SRRIP-Live (SRRIP_DOA_INS_RRPV=3; hit→2 already in phase2 data):
#   SL-A: hit→0  (full recovery on first hit)
#   SL-B: hit→1  (partial recovery, one step)
#
# IPV-Live (all DoA insert@3, i.e. ipv[4]=3; MD fixed at {0:1:1:2:2}):
#   IL-A: DoA={0:0:0:0:3}  3→0        (full recovery, 1 hit)
#   IL-B: DoA={0:1:2:2:3}  3→2        (one step, capped at RRPV=2)
#   IL-C: DoA={0:1:1:1:3}  3→1        (skip RRPV=2, capped at RRPV=1)
#   IL-D: DoA={0:1:1:2:3}  3→2→1      (two steps, capped at RRPV=1)
#
# Submission order: config-first.
#   Phase 1: for each config, submit its priority suites (gap, ligra, gms).
#   Phase 2: for each config, submit its remaining suites (ml, qmm, dpc3, google).
# This ensures each config's most discriminating results land before any config
# starts its slower suites.
#
# THD_DEAD fixed at Phase 1 per-suite optimal. THD_DOA=6.

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="ins3_hit_${DATE}"
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

# Submit one config across a list of suites.
# Args: cfg_path  binary  jobname_prefix  extra_env  suite_specs...
submit_config_suites() {
  local cfg_path="$1" binary="$2" jname_pfx="$3" extra="$4"
  shift 4
  for suite_spec in "$@"; do
    IFS=: read -r suite tdir ext n <<< "${suite_spec}"
    local s="${suite:0:3}"
    local sl_dead="${SRRIP_THD_DEAD[$suite]}"
    local base_env="SCORING_MODE=5,THD_DOA=${THD_DOA},THD_DEAD=${sl_dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"
    submit "${LABEL}/${cfg_path}/${suite}" "${binary}" "${jname_pfx}${s}" \
           "${n}" "${tdir}" "${ext}" "${base_env},${extra}"
  done
}

PRIO_SUITES=(
  "gap:trace-files/gap:trace.gz:9"
  "ligra:trace-files/ligra:champsimtrace.xz:18"
  "gms:trace-files/gms:champsimtrace.gz:11"
)
REST_SUITES=(
  "ml:trace-files/ml:champsimtrace.gz:31"
  "qmm:trace-files/QMM:champsimtrace.xz:45"
  "dpc3:/home/users/shared/traces/dpc3_traces:champsimtrace.xz:95"
  "google:/home/users/shared/traces/Google_Traces_v2:champsim.gz:43"
)

echo "=== Insert@3 hit-promotion sweep at THD_DOA=${THD_DOA} ==="
echo "Label: ${LABEL}"
echo ""

echo "--- Phase 1: priority suites (gap, ligra, gms) per config ---"

echo "  [SL-A] insert@3, hit→0"
submit_config_suites "srrip_live/slA" champsim_srrip_live "slA3" \
  "SRRIP_DOA_INS_RRPV=3,SRRIP_DOA_HIT_RRPV=0,SRRIP_MD_INS_RRPV=2,SRRIP_MD_HIT_RRPV=1" \
  "${PRIO_SUITES[@]}"

echo "  [SL-B] insert@3, hit→1"
submit_config_suites "srrip_live/slB" champsim_srrip_live "slB3" \
  "SRRIP_DOA_INS_RRPV=3,SRRIP_DOA_HIT_RRPV=1,SRRIP_MD_INS_RRPV=2,SRRIP_MD_HIT_RRPV=1" \
  "${PRIO_SUITES[@]}"

echo "  [IL-A] DoA={0:0:0:0:3} 3→0"
submit_config_suites "ipv_live/ilA" champsim_ipv_live "ilA3" \
  "IPV_DOA=0:0:0:0:3,IPV_MOSTLY_DEAD=0:1:1:2:2" \
  "${PRIO_SUITES[@]}"

echo "  [IL-B] DoA={0:1:2:2:3} 3→2"
submit_config_suites "ipv_live/ilB" champsim_ipv_live "ilB3" \
  "IPV_DOA=0:1:2:2:3,IPV_MOSTLY_DEAD=0:1:1:2:2" \
  "${PRIO_SUITES[@]}"

echo "  [IL-C] DoA={0:1:1:1:3} 3→1"
submit_config_suites "ipv_live/ilC" champsim_ipv_live "ilC3" \
  "IPV_DOA=0:1:1:1:3,IPV_MOSTLY_DEAD=0:1:1:2:2" \
  "${PRIO_SUITES[@]}"

echo "  [IL-D] DoA={0:1:1:2:3} 3→2→1"
submit_config_suites "ipv_live/ilD" champsim_ipv_live "ilD3" \
  "IPV_DOA=0:1:1:2:3,IPV_MOSTLY_DEAD=0:1:1:2:2" \
  "${PRIO_SUITES[@]}"

echo ""
echo "--- Phase 2: remaining suites (ml, qmm, dpc3, google) per config ---"

echo "  [SL-A] insert@3, hit→0"
submit_config_suites "srrip_live/slA" champsim_srrip_live "slA3" \
  "SRRIP_DOA_INS_RRPV=3,SRRIP_DOA_HIT_RRPV=0,SRRIP_MD_INS_RRPV=2,SRRIP_MD_HIT_RRPV=1" \
  "${REST_SUITES[@]}"

echo "  [SL-B] insert@3, hit→1"
submit_config_suites "srrip_live/slB" champsim_srrip_live "slB3" \
  "SRRIP_DOA_INS_RRPV=3,SRRIP_DOA_HIT_RRPV=1,SRRIP_MD_INS_RRPV=2,SRRIP_MD_HIT_RRPV=1" \
  "${REST_SUITES[@]}"

echo "  [IL-A] DoA={0:0:0:0:3} 3→0"
submit_config_suites "ipv_live/ilA" champsim_ipv_live "ilA3" \
  "IPV_DOA=0:0:0:0:3,IPV_MOSTLY_DEAD=0:1:1:2:2" \
  "${REST_SUITES[@]}"

echo "  [IL-B] DoA={0:1:2:2:3} 3→2"
submit_config_suites "ipv_live/ilB" champsim_ipv_live "ilB3" \
  "IPV_DOA=0:1:2:2:3,IPV_MOSTLY_DEAD=0:1:1:2:2" \
  "${REST_SUITES[@]}"

echo "  [IL-C] DoA={0:1:1:1:3} 3→1"
submit_config_suites "ipv_live/ilC" champsim_ipv_live "ilC3" \
  "IPV_DOA=0:1:1:1:3,IPV_MOSTLY_DEAD=0:1:1:2:2" \
  "${REST_SUITES[@]}"

echo "  [IL-D] DoA={0:1:1:2:3} 3→2→1"
submit_config_suites "ipv_live/ilD" champsim_ipv_live "ilD3" \
  "IPV_DOA=0:1:1:2:3,IPV_MOSTLY_DEAD=0:1:1:2:2" \
  "${REST_SUITES[@]}"

echo ""
echo "Arrays: 6 configs * 7 suites = 42 arrays"
echo "Total tasks: ~1512"
