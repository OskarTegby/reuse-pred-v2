#!/usr/bin/env bash
# sweep_exp_validate.sh — Validation: srrip_live on Qualcomm with optimal thresholds
#
# Test srrip_live replacement policy guided by PC-indexed bHIST on Qualcomm (QMM) benchmarks.
# Compare against liveness-replacement branch to verify implementation correctness.
# Tests both MID_THD=4 and MID_THD=8 (commonly optimal from prior work).
#
# 45 traces × 2 thresholds = 90 tasks

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
BASE_LABEL="${token}_validate_srrip_live_${DATE}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

echo "Suite         : ${token}"
echo "Traces        : ${N}  (tasks ${TASK_RANGE})"
echo "Binary        : ${BINARY}"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "Results base  : results/${BASE_LABEL}/"
echo ""
echo "Config: srrip_live validation with MID_THD=4 and MID_THD=8"
echo "        PC-indexed bHIST, liveness-guided replacement"
echo ""

for thd in 4 8; do
  RUN_LABEL="${BASE_LABEL}/srrip_live_mid${thd}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "val_srrip_mid${thd}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 \
             -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",\
DPPRED=1,CBPRED=1,PCONF_THD=6,BCONF_THD=6,\
REPL_POL=srrip_live,MID_THD="$thd",MID_PROMOTE=0,\
PHIST_WAYS=1024,PHIST_REPL=lfu_doa,PHIST_BUF_CAP=128 \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] srrip_live_mid${thd}"
done

finish_submission $(( N * 2 )) "${BASE_LABEL}"
