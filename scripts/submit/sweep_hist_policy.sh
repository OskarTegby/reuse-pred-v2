#!/usr/bin/env bash
# sweep_hist_policy.sh — Experiment 005: DoA-LFU, promotion buffer, PC-partitioned bHIST.
#
# Groups:
#   1. Policy comparison at default sizes (flat bHIST, 4096 entries):
#        lfu_opt         — LFU, no buffer        (reference, matches exp004 lfu_full_opt)
#        lfu_doa_opt     — LFU_DOA, no buffer
#        lfu_buf_opt     — LFU + buffer(256)
#        lfu_doa_buf_opt — LFU_DOA + buffer(256)
#
#   2. PC-partitioned bHIST at default capacity (256 PC × 16 addr = 4096 total):
#        pc_opt          — no addr buffer
#        pc_buf_opt      — addr buffer(8) per PC
#
#   3. Flat bHIST size sweep with LFU_DOA (pHIST fixed at 1024):
#        flat_doa_{2048,1024,512,256,128}         — no buffer
#        flat_doa_buf_{2048,1024,512,256,128}     — buffer(256)
#
#   4. PC-partitioned size sweep (vary addr_ways with pc_ways fixed at 256):
#        pc_a8, pc_a4, pc_a2    — addr_ways=8,4,2  no buffer
#        pc_a8_buf, pc_a4_buf   — addr_ways=8,4    buffer(8)
#
# All configs: DPPRED=1, CBPRED=1, THD=(0,0), QMM 45 traces,
#              HIST_REPL=lfu_doa or lfu as noted, 50M warmup + 100M sim.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${SCRIPT_DIR}/_lib.sh"

# ── Parameters ────────────────────────────────────────────────────────────────

token=${SUITE_TOKEN:-qmm}
TRACE_DIR=${TRACE_DIR:-/home/users/otegby/ChampSim-dev/trace-files/QMM}
TRACE_EXT=${TRACE_EXT:-champsimtrace.xz}
WARMUP=${WARMUP:-50000000}
SIM=${SIM:-100000000}
BINARY=${BINARY:-champsim_verify}
DEBUG=${DEBUG:-0}
DEBUG_TAG=$( [ "$DEBUG" = "1" ] && echo "_debug" || echo "" )

N=$(find "$TRACE_DIR" -name "*.${TRACE_EXT}" | wc -l)
TASK_RANGE="1-${N}"

DATE=$(date +%Y%m%d_%H%M)
BASE_LABEL="${token}_hist_policy_${DATE}${DEBUG_TAG}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# Config columns:
#   name  bhist_mode  hist_repl  bhist_ways  bhist_buf_cap  bhist_pc_ways  bhist_addr_ways  bhist_addr_buf
configs=(
  # Group 1 — flat bHIST policy comparison at 4096 entries
  "lfu_opt          flat  lfu     4096  0    256  16  0"
  "lfu_doa_opt      flat  lfu_doa 4096  0    256  16  0"
  "lfu_buf_opt      flat  lfu     4096  256  256  16  0"
  "lfu_doa_buf_opt  flat  lfu_doa 4096  256  256  16  0"

  # Group 2 — PC-partitioned bHIST (256 PC × 16 addr)
  # Note: HIST_REPL=lfu here so pHIST matches the exp004/lfu_opt baseline.
  # bhist_pc (PCPartitionedTable) always uses DoA-LFU internally regardless.
  "pc_opt           pc    lfu     4096  0    256  16  0"
  "pc_buf_opt       pc    lfu     4096  0    256  16  8"

  # Group 3a — flat LFU_DOA size sweep, no buffer
  "flat_doa_2048    flat  lfu_doa 2048  0    256  16  0"
  "flat_doa_1024    flat  lfu_doa 1024  0    256  16  0"
  "flat_doa_512     flat  lfu_doa  512  0    256  16  0"
  "flat_doa_256     flat  lfu_doa  256  0    256  16  0"
  "flat_doa_128     flat  lfu_doa  128  0    256  16  0"

  # Group 3b — flat LFU_DOA size sweep, with buffer(256)
  "flat_doa_buf_2048  flat  lfu_doa 2048  256  256  16  0"
  "flat_doa_buf_1024  flat  lfu_doa 1024  256  256  16  0"
  "flat_doa_buf_512   flat  lfu_doa  512  256  256  16  0"
  "flat_doa_buf_256   flat  lfu_doa  256  256  256  16  0"
  "flat_doa_buf_128   flat  lfu_doa  128  256  256  16  0"

  # Group 4a — PC-partitioned addr_ways sweep (pc_ways=256 fixed), no buffer
  "pc_a8            pc    lfu     4096  0    256   8  0"
  "pc_a4            pc    lfu     4096  0    256   4  0"
  "pc_a2            pc    lfu     4096  0    256   2  0"

  # Group 4b — PC-partitioned addr_ways sweep with addr buffer(8)
  "pc_a8_buf        pc    lfu     4096  0    256   8  8"
  "pc_a4_buf        pc    lfu     4096  0    256   4  8"
)

echo "Suite         : ${token}"
echo "Traces        : ${N}  (tasks ${TASK_RANGE})"
echo "Configs       : ${#configs[@]}"
echo "Binary        : ${BINARY}"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "Results base  : results/${BASE_LABEL}/"
echo "Logs          : logs/${BASE_LABEL}/"
echo ""

for config in "${configs[@]}"; do
  read -r exp_name bhist_mode hist_repl bhist_ways bhist_buf_cap \
           bhist_pc_ways bhist_addr_ways bhist_addr_buf <<< "$config"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "hp_${exp_name:0:12}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 \
             -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",\
DPPRED=1,CBPRED=1,PCONF_THD=0,BCONF_THD=0,\
HIST_REPL="$hist_repl",\
BHIST_MODE="$bhist_mode",\
BHIST_WAYS="$bhist_ways",\
BHIST_BUF_CAP="$bhist_buf_cap",\
BHIST_PC_WAYS="$bhist_pc_ways",\
BHIST_ADDR_WAYS="$bhist_addr_ways",\
BHIST_ADDR_BUF="$bhist_addr_buf" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}  (mode=${bhist_mode}, repl=${hist_repl}, ways=${bhist_ways}, buf=${bhist_buf_cap})"
done

finish_submission $(( ${#configs[@]} * N )) "${BASE_LABEL}"
