#!/usr/bin/env bash
# sweep_exp011.sh — Experiment 011: Baseline confirmation at default (6,6) threshold
#
# Confirm reference design with standard sizes and default threshold.
# pHIST: 1024+128buf, bHIST: 4096+128buf, SRRIP+buf both, threshold: (6,6)
#
# 4 variants × 45 traces = 180 tasks

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
BASE_LABEL="${token}_exp011_baseline_${DATE}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

configs=(
  "baseline_flat         flat   srrip  srrip  128   128"
)

echo "Suite         : ${token}"
echo "Traces        : ${N}  (tasks ${TASK_RANGE})"
echo "Configs       : ${#configs[@]}"
echo "Binary        : ${BINARY}"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "Threshold     : (6,6) default"
echo "Results base  : results/${BASE_LABEL}/"
echo ""

for config in "${configs[@]}"; do
  read -r exp_name bhist_mode phist_repl bhist_repl phist_buf bhist_buf <<< "$config"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  # Determine bHIST config based on mode
  if [ "$bhist_mode" = "pc" ]; then
    bhist_vars="BHIST_MODE=pc,BHIST_PC_WAYS=512,BHIST_ADDR_WAYS=8,BHIST_ADDR_BUF=0"
  else
    bhist_vars="BHIST_MODE=flat,BHIST_WAYS=4096"
  fi

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
DPPRED=1,CBPRED=1,PCONF_THD=6,BCONF_THD=6,\
PHIST_WAYS=1024,PHIST_REPL="$phist_repl",PHIST_BUF_CAP="$phist_buf",\
BHIST_REPL="$bhist_repl",BHIST_BUF_CAP="$bhist_buf",$bhist_vars \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}"
done

finish_submission $(( ${#configs[@]} * N )) "${BASE_LABEL}"
