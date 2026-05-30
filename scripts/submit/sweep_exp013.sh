#!/usr/bin/env bash
# sweep_exp013.sh — Experiment 013: PC-indexed bHIST for replacement guidance only
#
# Test pure replacement policy value using bHIST dead_count signals.
# Bypass: disabled (no bypass decisions, all blocks allowed).
# Replacement: guided by bHIST dead_count signals via REPL_GUIDANCE.
#
# 45 traces = 45 tasks

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
BASE_LABEL="${token}_exp013_replguid_${DATE}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

echo "Suite         : ${token}"
echo "Traces        : ${N}  (tasks ${TASK_RANGE})"
echo "Binary        : ${BINARY}"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "Results base  : results/${BASE_LABEL}/"
echo ""
echo "Config: PC-indexed bHIST (512×8) for replacement guidance only"
echo ""

RUN_LABEL="${BASE_LABEL}/pc512x8_replguid"
mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

raw=$(qsub -t "$TASK_RANGE" \
           -N "s13_pc512x8_repl" \
           -o "${LOG_DIR}/" \
           -e "${LOG_DIR}/" \
           -l h_rt=24:00:00 \
           -l mem_free=1G \
           -wd "$PROJECT_ROOT" \
           -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",\
DPPRED=0,CBPRED=0,PCONF_THD=0,BCONF_THD=0,\
BHIST_MODE=pc,BHIST_PC_WAYS=512,BHIST_ADDR_WAYS=8,BHIST_ADDR_BUF=0,\
BHIST_REPL=lfu_doa,BHIST_BUF_CAP=0,\
REPL_GUIDANCE=1,REPL_GUIDANCE_THD=0,\
PHIST_WAYS=1024,PHIST_REPL=srrip,PHIST_BUF_CAP=128 \
           "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
echo "  [jid=${jid}] pc512x8_replguid"

finish_submission $(( N )) "${BASE_LABEL}"
