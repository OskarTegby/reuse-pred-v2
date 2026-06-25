#!/bin/bash
set -euo pipefail
# Clean re-evaluation of set dueling vs the hard-coded IPVs at the fixed
# threshold (THD_DOA=6) originally used to evaluate the duel.
#
# ALL three arms use the bugfixed binary champsim_ipv_live_fixed (commit 488746c)
# so the comparison is apples-to-apples on one consistent build:
#   cfgA : fixed ins@2  {0:1:2:2:2}   (hard-coded, non-dueling)
#   ilB  : fixed ins@3  {0:1:2:2:3}   (hard-coded, non-dueling)
#   duel : 2-way cfgA-vs-ilB, DUEL_N_SAMPLERS=32  (hit-based, default metric)
# MD shared {0:1:1:2:2}. Per-suite THD_DEAD as in the ins3_hit reference.
#
# (The earlier cfgA/ilB references used older binaries; the buggy non-dueling
#  path also made fixed-IPV runs ignore IPV_DOA. This rerun fixes both.)

BASE=/home/users/otegby/ChampSim-dev
BIN=champsim_ipv_live_fixed
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="eval_theta6_fixed_${DATE}"

declare -A THD_DEAD=([gap]=4 [ligra]=16 [gms]=4 [ml]=2 [qmm]=2 [dpc3]=4 [google]=8)

SUITES=(
  "gap:trace-files/gap:trace.gz:9"
  "ligra:trace-files/ligra:champsimtrace.xz:18"
  "gms:trace-files/gms:champsimtrace.gz:11"
  "ml:trace-files/ml:champsimtrace.gz:31"
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
       -v "WARMUP=${W},SIM=${S},TRACE_DIR=${trace_dir},TRACE_EXT=${ext},RUN_LABEL=${label},BINARY=${BIN},${extra}" \
       "${BASE}/scripts/submit/run_cs.sh" \
    | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${label} (${n} tasks)"
}

CFGA="IPV_DOA=0:1:2:2:2,IPV_MOSTLY_DEAD=0:1:1:2:2"
ILB="IPV_DOA=0:1:2:2:3,IPV_MOSTLY_DEAD=0:1:1:2:2"
DUEL="DUEL_N_CONFIGS=2,DUEL_N_SAMPLERS=32,IPV_DOA_0=0:1:2:2:2,IPV_DOA_1=0:1:2:2:3,IPV_MOSTLY_DEAD=0:1:1:2:2"

echo "=== theta=6 re-eval (cfgA vs ilB vs duel) on fixed binary ==="
echo "Label: ${LABEL}"
echo ""
for arm in cfgA ilB duel; do
  case "$arm" in
    cfgA) arm_env="$CFGA" ;;
    ilB)  arm_env="$ILB" ;;
    duel) arm_env="$DUEL" ;;
  esac
  echo "--- Arm: ${arm} ---"
  for suite_spec in "${SUITES[@]}"; do
    IFS=: read -r suite tdir ext n <<< "${suite_spec}"
    dead="${THD_DEAD[$suite]}"
    base_env="SCORING_MODE=5,THD_DOA=6,THD_DEAD=${dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"
    submit "${LABEL}/ipv_live/${arm}/${suite}" "e6${arm:0:1}${suite:0:2}" \
           "${n}" "${tdir}" "${ext}" "${base_env},${arm_env}"
  done
  echo ""
done
echo "Arrays: 3 arms * 7 suites = 21.  Total tasks: 3 * 252 = 756"
