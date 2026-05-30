#!/usr/bin/env bash
# sweep_buf_size.sh — Experiment 005b cont.: pHIST buffer size sweep.
#
# Sweeps the promotion buffer capacity for SRRIP pHIST (LFU_DOA bHIST, no bHIST buf).
# The 128-entry reference is already running as srrip_buf_phist (job 1403506).
# This script covers 64, 256, and 512 entries.
#
# 3 configs × 45 traces = 135 tasks.
# All: DPPRED=1, CBPRED=1, THD=(0,0), BHIST_MODE=flat,
#      PHIST_WAYS=1024, BHIST_WAYS=4096, PHIST_REPL=srrip, BHIST_REPL=lfu_doa,
#      BHIST_BUF_CAP=0, 50M warmup + 100M sim.

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
BASE_LABEL="${token}_buf_size_${DATE}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

configs=(
  "srrip_buf64_phist   64"
  "srrip_buf256_phist  256"
  "srrip_buf512_phist  512"
)

echo "Suite         : ${token}"
echo "Traces        : ${N}  (tasks ${TASK_RANGE})"
echo "Configs       : ${#configs[@]}  (buf sizes: 64, 256, 512; 128 = job 1403506)"
echo "Binary        : ${BINARY}"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "Results base  : results/${BASE_LABEL}/"
echo ""

for config in "${configs[@]}"; do
  read -r exp_name buf_cap <<< "$config"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "bs_${exp_name:0:14}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 \
             -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",\
DPPRED=1,CBPRED=1,PCONF_THD=0,BCONF_THD=0,\
BHIST_MODE=flat,PHIST_WAYS=1024,BHIST_WAYS=4096,\
PHIST_REPL=srrip,BHIST_REPL=lfu_doa,\
PHIST_BUF_CAP="$buf_cap",BHIST_BUF_CAP=0 \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}  (PHIST_BUF_CAP=${buf_cap})"
done

finish_submission $(( ${#configs[@]} * N )) "${BASE_LABEL}"
