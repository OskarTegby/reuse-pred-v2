#!/usr/bin/env bash
# sweep_exp011.sh — Experiment 011: Shrunk tables with larger buffers (same total capacity)
#
# Test whether buffers are mechanism-driven (not size-driven).
# Reduce main tables, increase buffers, keep total capacity constant.
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
BASE_LABEL="${token}_exp011_shrunk_${DATE}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# Config: name  phist_main  phist_buf  bhist_main  bhist_buf  threshold
# Total: pHIST 1024, bHIST 4096 (same as baseline exp008)
configs=(
  "shrunk_opt   512  512  2048  2048  0"
  "shrunk_def   512  512  2048  2048  6"
)

echo "Suite         : ${token}"
echo "Traces        : ${N}  (tasks ${TASK_RANGE})"
echo "Configs       : ${#configs[@]}"
echo "Binary        : ${BINARY}"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "Results base  : results/${BASE_LABEL}/"
echo ""
echo "Note: Shrunk main tables, enlarged buffers, same total capacity"
echo "      Tests mechanism value of buffers vs capacity"
echo ""

for config in "${configs[@]}"; do
  read -r exp_name phist_main phist_buf bhist_main bhist_buf thd <<< "$config"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "s11_${exp_name:0:14}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 \
             -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",\
DPPRED=1,CBPRED=1,PCONF_THD="$thd",BCONF_THD="$thd",\
BHIST_MODE=flat,\
PHIST_WAYS="$phist_main",PHIST_REPL=srrip,PHIST_BUF_CAP="$phist_buf",\
BHIST_WAYS="$bhist_main",BHIST_REPL=srrip,BHIST_BUF_CAP="$bhist_buf" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}  (pHIST=${phist_main}+${phist_buf}buf, bHIST=${bhist_main}+${bhist_buf}buf, thd=$thd)"
done

finish_submission $(( ${#configs[@]} * N )) "${BASE_LABEL}"
