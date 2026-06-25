#!/bin/bash
set -euo pipefail
# Threshold re-study for IPV-Live, testing whether the optimal THD_DOA shifts
# once insertion position is accounted for.
#
# Two arms, both sweeping THD_DOA in {2,4,8,16} (paper grid):
#   ins2 : fixed cfgA  {0:1:2:2:2}  (ins@2)              -- the alternative IPV
#   duel : 2-way cfgA-vs-ilB, DUEL_N_SAMPLERS=32         -- ins@2 vs ins@3 per-PC
#          config_0 = cfgA {0:1:2:2:2}, config_1 = ilB {0:1:2:2:3}
#
# (ins@3 / ilB single-threshold data already exists at THD_DOA=6; the duel arm
#  carries ins@3 across the sweep.)
#
# Suites: gap (strongest ins@3 win), ml (most diagnostic: bark/biogpt + vit),
#         ligra (control: ins@2 is better here).
# MD shared {0:1:1:2:2}. Env otherwise matches the ins3_hit reference.

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="ipv_thd_sweep_${DATE}"

THDS=(2 4 8 16)
declare -A THD_DEAD=([gap]=4 [ligra]=16 [ml]=2)

# suite:trace_dir:ext:n_traces
SUITES=(
  "gap:trace-files/gap:trace.gz:9"
  "ligra:trace-files/ligra:champsimtrace.xz:18"
  "ml:trace-files/ml:champsimtrace.gz:31"
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

echo "=== IPV-Live threshold re-study (ins2 vs duel), grid {2,4,8,16} ==="
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

echo "Arrays: 2 arms * 4 thresholds * 3 suites = 24"
echo "Total tasks: 2 * 4 * (9+18+31) = 464"
