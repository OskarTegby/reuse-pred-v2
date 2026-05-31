#!/usr/bin/env bash
# sweep_exp017.sh — Experiment 017: LLC/STLB replacement guided by per-PC liveness (unbounded)
#
# Use srrip_live replacement policy guided by per-PC DoA/mostly-dead statistics.
# Unbounded per-PC liveness data collection (no fixed budget).
# Per-PC liveness data guides SRRIP RRPV insertion and promotion.
#
# Measures: theoretical maximum benefit when liveness data is unlimited.
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
BASE_LABEL="${token}_exp017_srrip_live_unbounded_${DATE}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

echo "Suite         : ${token}"
echo "Traces        : ${N}  (tasks ${TASK_RANGE})"
echo "Binary        : ${BINARY}"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "Results base  : results/${BASE_LABEL}/"
echo ""
echo "Config: srrip_live guided by per-PC liveness, UNBOUNDED budget"
echo ""

RUN_LABEL="${BASE_LABEL}/srrip_live_unbounded"
mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

raw=$(qsub -t "$TASK_RANGE" \
           -N "s17_srrip_unbdd" \
           -o "${LOG_DIR}/" \
           -e "${LOG_DIR}/" \
           -l h_rt=24:00:00 \
           -l mem_free=1G \
           -wd "$PROJECT_ROOT" \
           -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",\
DPPRED=1,CBPRED=1,PCONF_THD=6,BCONF_THD=6,\
CHARACTERIZATION=1,\
REPL_POL=srrip_live,MID_THD=1,MID_PROMOTE=0,\
PHIST_WAYS=1024,PHIST_REPL=lfu_doa,PHIST_BUF_CAP=128 \
           "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
echo "  [jid=${jid}] srrip_live_unbounded"

finish_submission $(( N )) "${BASE_LABEL}"
