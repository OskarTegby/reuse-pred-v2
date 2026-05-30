#!/usr/bin/env bash
# sweep_exp012.sh — Experiment 012: PC-indexed bHIST for bypass prediction only
#
# Test pure bypass prediction value using PC-aware indexing at same budget (4096 entries).
# PC-indexed bHIST (256 PC × 16 addr) used for bypass decisions.
# Replacement uses simple LRU (no guidance from bHIST).
#
# 4 configs × 45 traces = 180 tasks

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
BASE_LABEL="${token}_exp012_pcbhist_bypass_${DATE}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# Config: name  phist_main  phist_buf  threshold
# Note: BHIST_MODE=pc, BHIST_PC_WAYS=256, BHIST_ADDR_WAYS=16, BHIST_ADDR_BUF=0
# Total bHIST: 256×16 = 4096 (same budget as baseline flat bHIST)
configs=(
  "pcbhist_opt   1024  128  0"
  "pcbhist_def   1024  128  6"
)

echo "Suite         : ${token}"
echo "Traces        : ${N}  (tasks ${TASK_RANGE})"
echo "Configs       : ${#configs[@]}"
echo "Binary        : ${BINARY}"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "Results base  : results/${BASE_LABEL}/"
echo ""
echo "Note: PC-indexed bHIST (256×16=4096 entries) for bypass only"
echo "      Isolates pure bypass prediction value at fixed budget"
echo ""

for config in "${configs[@]}"; do
  read -r exp_name phist_main phist_buf thd <<< "$config"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "s12_${exp_name:0:14}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 \
             -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",\
DPPRED=1,CBPRED=1,PCONF_THD="$thd",BCONF_THD="$thd",\
BHIST_MODE=pc,BHIST_PC_WAYS=256,BHIST_ADDR_WAYS=16,BHIST_ADDR_BUF=0,\
PHIST_WAYS="$phist_main",PHIST_REPL=srrip,PHIST_BUF_CAP="$phist_buf" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}  (pHIST=${phist_main}+${phist_buf}buf, bHIST=pc 256×16, thd=$thd)"
done

finish_submission $(( ${#configs[@]} * N )) "${BASE_LABEL}"
