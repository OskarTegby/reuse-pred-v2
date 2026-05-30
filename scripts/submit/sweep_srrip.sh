#!/usr/bin/env bash
# sweep_srrip.sh — Experiment 005b: fixed SRRIP evaluation and SRRIP + two-stage buffer.
#
# The SRRIP on_hit bug is fixed: dead eviction → rrpv=0 (protect),
# live eviction → rrpv=SRRIP_MAX (demote; entry re-enters buffer).
#
# Groups:
#   Standalone (no buffer) — compare fixed SRRIP against LFU_DOA baseline from 005a:
#     srrip_phist:     SRRIP pHIST, LFU_DOA bHIST  (ref: doa_phist_only +13.05%)
#     srrip_bhist:     LFU_DOA pHIST, SRRIP bHIST  (ref: doa_bhist_only  +7.06%)
#     srrip_both:      SRRIP both tables            (ref: doa_both        +12.07%)
#
#   Two-stage buffer (128-entry DoA-LFU buffer + re-entry on eviction):
#     srrip_buf_phist: SRRIP+buf pHIST, LFU_DOA bHIST
#     srrip_buf_bhist: LFU_DOA pHIST,   SRRIP+buf bHIST
#     srrip_buf_both:  SRRIP+buf both tables
#
# 6 configs × 45 traces = 270 tasks.
# All: DPPRED=1, CBPRED=1, THD=(0,0), BHIST_MODE=flat,
#      PHIST_WAYS=1024, BHIST_WAYS=4096, 50M warmup + 100M sim.

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
BASE_LABEL="${token}_srrip_${DATE}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# Config columns: name  phist_repl  bhist_repl  phist_buf  bhist_buf
configs=(
  "srrip_phist      srrip    lfu_doa  0    0"
  "srrip_bhist      lfu_doa  srrip    0    0"
  "srrip_both       srrip    srrip    0    0"
  "srrip_buf_phist  srrip    lfu_doa  128  0"
  "srrip_buf_bhist  lfu_doa  srrip    0    128"
  "srrip_buf_both   srrip    srrip    128  128"
)

echo "Suite         : ${token}"
echo "Traces        : ${N}  (tasks ${TASK_RANGE})"
echo "Configs       : ${#configs[@]}"
echo "Binary        : ${BINARY}"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "Results base  : results/${BASE_LABEL}/"
echo ""

for config in "${configs[@]}"; do
  read -r exp_name phist_repl bhist_repl phist_buf bhist_buf <<< "$config"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "sr_${exp_name:0:14}" \
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
PHIST_REPL="$phist_repl",BHIST_REPL="$bhist_repl",\
PHIST_BUF_CAP="$phist_buf",BHIST_BUF_CAP="$bhist_buf" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}  (phist=${phist_repl}+${phist_buf}buf, bhist=${bhist_repl}+${bhist_buf}buf)"
done

finish_submission $(( ${#configs[@]} * N )) "${BASE_LABEL}"
