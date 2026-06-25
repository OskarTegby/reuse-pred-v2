#!/bin/bash
set -euo pipefail
# Threshold re-study for IPV-Live — remaining suites (gms, qmm, dpc3, google).
# Companion to ipv_thd_sweep_20260623_0131 (gap, ligra, ml).
#
# Two arms, both sweeping THD_DOA in {2,4,8,16}:
#   ins2 : fixed cfgA  {0:1:2:2:2}  (ins@2)
#   duel : 2-way cfgA-vs-ilB, DUEL_N_SAMPLERS=32
#          config_0 = cfgA {0:1:2:2:2}, config_1 = ilB {0:1:2:2:3}
# MD shared {0:1:1:2:2}. Env matches the ins3_hit reference.

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="ipv_thd_sweep_rest_${DATE}"

THDS=(2 4 8 16)
declare -A THD_DEAD=([gms]=4 [qmm]=2 [dpc3]=4 [google]=8)

# suite:trace_dir:ext:n_traces
SUITES=(
  "gms:trace-files/gms:champsimtrace.gz:11"
  "qmm:trace-files/QMM:champsimtrace.xz:45"
  "dpc3:/home/users/shared/traces/dpc3_traces:champsimtrace.xz:95"
  "google:/home/users/shared/traces/Google_Traces_v2:champsim.gz:43"
)

submit() {
  local label="$1" jobname="$2" n="$3" trace_dir="$4" ext="$5" extra="$6"
  mkdir -p "${BASE}/results/${label}" "${BASE}/logs/${label}"
  local jid
  jid=$(qsub -t "1-${n}" -N "${jobname}" \
       -o "${BASE}/logs/${label}/" -e "${BASE}/logs/${label}/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "${BASE}" \
       -v "WARMUP=${W},SIM=${S},TRACE_DIR=${trace_dir},TRACE_EXT=${ext},RUN_LABEL=${label},BINARY=champsim_ipv_live,${extra}" \
       "${BASE}/scripts/submit/run_cs.sh" \
    | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${label} (${n} tasks)"
}

INS2_IPV="IPV_DOA=0:1:2:2:2,IPV_MOSTLY_DEAD=0:1:1:2:2"
DUEL_IPV="DUEL_N_CONFIGS=2,DUEL_N_SAMPLERS=32,IPV_DOA_0=0:1:2:2:2,IPV_DOA_1=0:1:2:2:3,IPV_MOSTLY_DEAD=0:1:1:2:2"

echo "=== IPV-Live threshold re-study (rest: gms,qmm,dpc3,google), grid {2,4,8,16} ==="
echo "Label: ${LABEL}"
echo ""

for arm in ins2 duel; do
  case "$arm" in
    ins2) arm_env="$INS2_IPV" ;;
    duel) arm_env="$DUEL_IPV" ;;
  esac
  echo "--- Arm: ${arm} ---"
  for T in "${THDS[@]}"; do
    for suite_spec in "${SUITES[@]}"; do
      IFS=: read -r suite tdir ext n <<< "${suite_spec}"
      local_dead="${THD_DEAD[$suite]}"
      base_env="SCORING_MODE=5,THD_DOA=${T},THD_DEAD=${local_dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"
      submit "${LABEL}/ipv_live/${arm}/doa${T}/${suite}" \
             "t${arm:0:1}${T}${suite:0:2}" "${n}" "${tdir}" "${ext}" \
             "${base_env},${arm_env}"
    done
  done
  echo ""
done

echo "Arrays: 2 arms * 4 thresholds * 4 suites = 32"
echo "Total tasks: 2 * 4 * (11+45+95+43) = 1552"
