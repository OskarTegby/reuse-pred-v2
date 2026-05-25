#!/usr/bin/env bash
# verify_baseline_qmm.sh — submit a baseline (DPPRED=0, CBPRED=0) run on QMM
# traces using the first dpPred/cbPred implementation (fb719b249e65, 2026-03-15).
#
# This verifies that the original "no bypass" result is still reproducible with
# the early implementation before any threshold/PC/PFQ complexity was added.
#
# Usage: ./verify_baseline_qmm.sh [--debug]
#   --debug   run only the first trace (quick sanity check)
#
# Prerequisites (run on Castillo cluster):
#   1. git checkout verify-threshold-study
#   2. python3 config.sh champsim_config.json configs/lru.json
#   3. make static -j$(nproc)
#      → produces bin/champsim_lru
#   4. ./verify_baseline_qmm.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINARY="champsim_lru"
BIN="${PROJECT_ROOT}/bin/${BINARY}"

if [ ! -x "$BIN" ]; then
  echo "ERROR: binary not found at ${BIN}" >&2
  echo "Build first:" >&2
  echo "  python3 config.sh champsim_config.json configs/lru.json && make static -j\$(nproc)" >&2
  exit 1
fi

TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM"
TRACE_EXT="champsimtrace.xz"
WARMUP=50000000
SIM=100000000

DEBUG=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --debug) DEBUG=1; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N=${#TRACES[@]}
[ "$N" -eq 0 ] && { echo "ERROR: no traces in ${TRACE_DIR}" >&2; exit 2; }

if [ "$DEBUG" -eq 1 ]; then
  TASK_RANGE="1-1"
  MODE_TAG="_debug"
else
  TASK_RANGE="1-${N}"
  MODE_TAG=""
fi

DATE=$(date +%Y%m%d_%H%M)
RUN_LABEL="qmm_baseline_verify_${DATE}${MODE_TAG}"
LOG_DIR="${PROJECT_ROOT}/logs/${RUN_LABEL}"
mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}" "${LOG_DIR}"

raw=$(qsub -t "$TASK_RANGE" \
           -N "baseline_verify" \
           -o "${LOG_DIR}/" \
           -e "${LOG_DIR}/" \
           -l h_rt=24:00:00 \
           -l mem_free=1G \
           -wd "$PROJECT_ROOT" \
           -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",\
DPPRED=0,CBPRED=0,PCONF_THD=0,BCONF_THD=0,\
MID_THD=0,MID_KEY=0,MID_PROMOTE=0 \
           "${PROJECT_ROOT}/verify_worker.sh")

jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
echo "Submitted jid=${jid} (${TASK_RANGE})"
echo "Results: results/${RUN_LABEL}/"
echo "Monitor: qstat -u \$USER"
