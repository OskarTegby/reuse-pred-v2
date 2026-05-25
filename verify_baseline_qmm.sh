#!/usr/bin/env bash
# verify_baseline_qmm.sh — submit dpPred+cbPred (PCONF_THD=0, BCONF_THD=0) on
# all 45 QMM traces using the first dpPred/cbPred implementation
# (fb719b249e65, 2026-03-15) to verify the threshold-study result.
#
# Config: DPPRED=1, CBPRED=1, PCONF_THD=0, BCONF_THD=0
#   Both predictors enabled at threshold=0 (bypass as aggressively as possible).
#   This is the optimal point from the threshold heatmap.
#
# Binary: champsim_verify (built locally from verify-threshold-study branch,
#         transferred to ~/reuse-pred/bin/ on the cluster before submission).
#
# Usage: ./verify_baseline_qmm.sh [--debug]
#   --debug   run only the first trace (quick sanity check)

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINARY="champsim_verify"
BIN="${PROJECT_ROOT}/bin/${BINARY}"

if [ ! -x "$BIN" ]; then
  echo "ERROR: binary not found at ${BIN}" >&2
  echo "Transfer bin/champsim_verify from local machine first." >&2
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
RUN_LABEL="qmm_dppred_cbpred_verify_${DATE}${MODE_TAG}"
LOG_DIR="${PROJECT_ROOT}/logs/${RUN_LABEL}"
mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}" "${LOG_DIR}"

raw=$(qsub -t "$TASK_RANGE" \
           -N "dppred_cbpred_verify" \
           -o "${LOG_DIR}/" \
           -e "${LOG_DIR}/" \
           -l h_rt=24:00:00 \
           -l mem_free=1G \
           -wd "$PROJECT_ROOT" \
           -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",\
DPPRED=1,CBPRED=1,PCONF_THD=0,BCONF_THD=0,\
MID_THD=0,MID_KEY=0,MID_PROMOTE=0 \
           "${PROJECT_ROOT}/verify_worker.sh")

jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
echo "Submitted jid=${jid} (${TASK_RANGE})"
echo "Results: results/${RUN_LABEL}/"
echo "Monitor: qstat -u \$USER"
