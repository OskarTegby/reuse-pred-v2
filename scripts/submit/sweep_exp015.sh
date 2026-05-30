#!/usr/bin/env bash
# sweep_exp015.sh — Experiment 015: PC/address allocation trade-off study
#
# For fixed 4096-entry budget, vary PC ways vs address ways to find optimal split.
# Tests: 512×8, 512×4, 256×16, 256×8
# Uses PC-indexed bHIST for bypass prediction (DoA-LFU per-address replacement).
# Both (0,0) and (6,6) thresholds.
#
# 4 splits × 2 thresholds × 45 traces = 360 tasks

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${SCRIPT_DIR}/_lib.sh"

token=${SUITE_TOKEN:-qmm}
TRACE_DIR=${TRACE_DIR:-/home/users/otegby/ChampSim-dev/trace-files/QMM}
TRACE_EXT=${TRACE_EXT:-champsimtrace.xz}
WARMUP=${WARMUP:-50000000}
SIM=${SIM:-100000000}
BINARY=${BINARY:-champsim_verify}

N=$(find "$TRACE_DIR" -name "*.${TRACE_EXT}" | wc -l)
TASK_RANGE="1-${N}"
DATE=$(date +%Y%m%d_%H%M)
BASE_LABEL="${token}_exp015_pcsplit_${DATE}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# Config: name  pc_ways  addr_ways  threshold
# All total to 4096 entries
configs=(
  "512x8_opt    512  8   0"
  "512x8_def    512  8   6"
  "512x4_opt    512  4   0"
  "512x4_def    512  4   6"
  "256x16_opt   256  16  0"
  "256x16_def   256  16  6"
  "256x8_opt    256  8   0"
  "256x8_def    256  8   6"
)

echo "Suite         : ${token}"
echo "Traces        : ${N}  (tasks ${TASK_RANGE})"
echo "Configs       : ${#configs[@]}"
echo "Binary        : ${BINARY}"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "Results base  : results/${BASE_LABEL}/"
echo ""
echo "Study: PC/address allocation for fixed 4096-entry budget"
echo "       Tests: 512×8, 512×4, 256×16, 256×8 at (0,0) and (6,6)"
echo ""

for config in "${configs[@]}"; do
  read -r exp_name pc_ways addr_ways thd <<< "$config"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "s15_${exp_name:0:14}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 \
             -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",\
DPPRED=1,CBPRED=1,PCONF_THD="$thd",BCONF_THD="$thd",\
BHIST_MODE=pc,BHIST_PC_WAYS="$pc_ways",BHIST_ADDR_WAYS="$addr_ways",BHIST_ADDR_BUF=0,\
BHIST_REPL=lfu_doa,BHIST_BUF_CAP=0,\
PHIST_WAYS=1024,PHIST_REPL=srrip,PHIST_BUF_CAP=128 \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}  (${pc_ways}×${addr_ways}, thd=$thd)"
done

finish_submission $(( ${#configs[@]} * N )) "${BASE_LABEL}"
