#!/usr/bin/env bash
# sweep_sizes_optimal.sh — Experiment 008: Size sensitivity at (0,0) threshold.
#
# Sweeps pHIST buffer sizes, pHIST table sizes, and bHIST table sizes
# to characterize how sensitive the SRRIP+buffer design is to capacity.
# All at the optimal (0,0) threshold.
#
# 14 configs × 45 traces = 630 tasks.

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
BASE_LABEL="${token}_sizes_optimal_${DATE}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# Config columns: name  phist_ways  phist_buf  bhist_ways  bhist_buf
# All use SRRIP+buf: PHIST_REPL=srrip, BHIST_REPL=srrip
configs=(
  # pHIST buffer sweep (1024 main, variable buf)
  "pbuf_0      1024  0    4096  128"
  "pbuf_32     1024  32   4096  128"
  "pbuf_64     1024  64   4096  128"
  "pbuf_128    1024  128  4096  128"
  "pbuf_256    1024  256  4096  128"
  "pbuf_512    1024  512  4096  128"
  # pHIST table size sweep (variable ways, 128 buf)
  "psize_256   256   128  4096  128"
  "psize_512   512   128  4096  128"
  "psize_1024  1024  128  4096  128"
  "psize_2048  2048  128  4096  128"
  # bHIST table size sweep (4096 main, 128 buf pHIST, variable bHIST)
  "bsize_1024  1024  128  1024  128"
  "bsize_2048  1024  128  2048  128"
  "bsize_4096  1024  128  4096  128"
  "bsize_8192  1024  128  8192  128"
)

echo "Suite         : ${token}"
echo "Traces        : ${N}  (tasks ${TASK_RANGE})"
echo "Configs       : ${#configs[@]}"
echo "Threshold     : (0,0) — OPTIMAL"
echo "Sweeps        : pHIST buffer (6), pHIST size (4), bHIST size (4)"
echo "Binary        : ${BINARY}"
echo "Results base  : results/${BASE_LABEL}/"
echo ""

for config in "${configs[@]}"; do
  read -r exp_name phist_ways phist_buf bhist_ways bhist_buf <<< "$config"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "sz_${exp_name:0:14}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 \
             -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",\
DPPRED=1,CBPRED=1,PCONF_THD=0,BCONF_THD=0,\
BHIST_MODE=flat,\
PHIST_WAYS="$phist_ways",PHIST_REPL=srrip,PHIST_BUF_CAP="$phist_buf",\
BHIST_WAYS="$bhist_ways",BHIST_REPL=srrip,BHIST_BUF_CAP="$bhist_buf" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}  (phist=${phist_ways}+${phist_buf}buf, bhist=${bhist_ways}+${bhist_buf}buf)"
done

finish_submission $(( ${#configs[@]} * N )) "${BASE_LABEL}"
