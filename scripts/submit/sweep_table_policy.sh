#!/usr/bin/env bash
# sweep_table_policy.sh — Experiment 005a: isolate DoA-LFU and promotion buffer
# per table (pHIST only, bHIST only, both).
#
# Buffer configs hold total storage constant: main + buffer = original capacity.
#   pHIST: 768 main + 256 buf = 1024  |  bHIST: 3840 main + 256 buf = 4096
# Reference: exp004 lfu_full_opt (+7.27% geomean, HIST_REPL=lfu, no buffer).

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
BASE_LABEL="${token}_table_policy_${DATE}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# Config columns: name  phist_repl  bhist_repl  phist_ways  phist_buf  bhist_ways  bhist_buf
# Buffer configs: main table is reduced so that main+buffer = original capacity
#   pHIST: 768 + 256 = 1024  bHIST: 3840 + 256 = 4096
configs=(
  "doa_phist_only   lfu_doa  lfu      1024  0    4096  0"
  "doa_bhist_only   lfu      lfu_doa  1024  0    4096  0"
  "doa_both         lfu_doa  lfu_doa  1024  0    4096  0"
  "buf_phist_only   lfu      lfu       768  256  4096  0"
  "buf_bhist_only   lfu      lfu      1024  0    3840  256"
  "buf_both         lfu      lfu       768  256  3840  256"
)

echo "Suite         : ${token}"
echo "Traces        : ${N}  (tasks ${TASK_RANGE})"
echo "Configs       : ${#configs[@]}"
echo "Binary        : ${BINARY}"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "Results base  : results/${BASE_LABEL}/"
echo ""

for config in "${configs[@]}"; do
  read -r exp_name phist_repl bhist_repl phist_ways phist_buf bhist_ways bhist_buf <<< "$config"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "tp_${exp_name:0:14}" \
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
PHIST_WAYS="$phist_ways",PHIST_REPL="$phist_repl",PHIST_BUF_CAP="$phist_buf",\
BHIST_WAYS="$bhist_ways",BHIST_REPL="$bhist_repl",BHIST_BUF_CAP="$bhist_buf" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}  (phist=${phist_ways}+${phist_buf}buf repl=${phist_repl}, bhist=${bhist_ways}+${bhist_buf}buf repl=${bhist_repl})"
done

finish_submission $(( ${#configs[@]} * N )) "${BASE_LABEL}"
