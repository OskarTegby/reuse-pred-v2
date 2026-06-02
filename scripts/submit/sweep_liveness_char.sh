#!/bin/bash
# sweep_liveness_char.sh — per-PC liveness characterisation run for all 7 suites.
#
# Runs champsim_lru with LIVENESS_CHAR=1 on every trace in every suite.
# Output files contain LIVENESS_CHAR BEGIN/END blocks with per-PC DoA /
# mostly-dead / mostly-alive counts, classified using the halflife criterion.
#
# Usage: ./sweep_liveness_char.sh [--debug]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_lib.sh"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SHARED_TRACES=/home/users/shared/traces

DEBUG=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --debug) DEBUG=1; shift ;;
    *) echo "Usage: $0 [--debug]" >&2; exit 2 ;;
  esac
done

DATE=$(date +%Y%m%d_%H%M)
BASE_LABEL="liveness_char_${DATE}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

WARMUP=50000000
SIM=100000000

declare -A SUITE_DIRS=(
  [dpc3]="${SHARED_TRACES}/dpc3_traces"
  [gap]="${PROJECT_ROOT}/trace-files/gap"
  [gms]="${PROJECT_ROOT}/trace-files/gms"
  [google]="${SHARED_TRACES}/Google_Traces_v2"
  [ligra]="${PROJECT_ROOT}/trace-files/ligra"
  [ml]="${PROJECT_ROOT}/trace-files/ml"
  [qmm]="${PROJECT_ROOT}/trace-files/QMM"
)

declare -A SUITE_EXTS=(
  [dpc3]="champsimtrace.xz"
  [gap]="trace.gz"
  [gms]="champsimtrace.gz"
  [google]="champsim.gz"
  [ligra]="champsimtrace.xz"
  [ml]="champsimtrace.gz"
  [qmm]="champsimtrace.xz"
)

total_tasks=0

for SUITE in dpc3 gap gms google ligra ml qmm; do
  TRACE_DIR="${SUITE_DIRS[$SUITE]}"
  TRACE_EXT="${SUITE_EXTS[$SUITE]}"

  mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
  N=${#TRACES[@]}
  [ "$N" -eq 0 ] && { echo "WARNING: no traces for ${SUITE}, skipping" >&2; continue; }

  TASK_RANGE="1-${N}"
  [ "$DEBUG" -eq 1 ] && TASK_RANGE="1-1"

  RUN_LABEL="${BASE_LABEL}/${SUITE}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "char_${SUITE}" \
             -o "${LOG_DIR}/" -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="champsim_lru",\
LIVENESS_CHAR="1" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "[jid=${jid}] ${SUITE}: ${N} traces"
  total_tasks=$((total_tasks + N))
done

[ "$DEBUG" -eq 1 ] && total_tasks=7
finish_submission "$total_tasks" "$BASE_LABEL"
