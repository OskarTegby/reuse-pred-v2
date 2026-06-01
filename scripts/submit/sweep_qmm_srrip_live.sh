#!/bin/bash
# sweep_qmm_srrip_live.sh — SRRIP-Live threshold sweep for QMM suite only
#
# Usage: ./sweep_qmm_srrip_live.sh [--debug]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_lib.sh"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── Argument parsing ──────────────────────────────────────────────────────────
DEBUG=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --debug) DEBUG=1; shift ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 [--debug]" >&2
      exit 2 ;;
  esac
done

# ── QMM suite configuration ───────────────────────────────────────────────────
SUITE="qmm"
TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM"
TRACE_EXT="champsimtrace.xz"

# ── Trace-set settings ────────────────────────────────────────────────────────
WARMUP=50000000
SIM=100000000

# ── Resolve trace list ────────────────────────────────────────────────────────
mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N=${#TRACES[@]}
if [ "$N" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR} (ext: ${TRACE_EXT})" >&2
  exit 2
fi

TASK_RANGE="1-${N}"
DEBUG_TAG=""
if [ "$DEBUG" -eq 1 ]; then
  TASK_RANGE="1-1"
  DEBUG_TAG="_debug"
fi

DATE=$(date +%Y%m%d_%H%M)
BASE_LABEL="${SUITE}_srrip_live_${DATE}${DEBUG_TAG}"

LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# ── Thresholds for SRRIP-Live ─────────────────────────────────────────────────
SRRIP_LIVE_THRESHOLDS=(1 2 4 8 16)

echo "Suite             : ${SUITE}"
echo "Policy            : SRRIP-Live (LLC-only, PC-indexed bHIST)"
echo "Traces            : ${N}  (tasks ${TASK_RANGE})"
echo "Total job arrays  : 5 (thresholds 1,2,4,8,16)"
echo "Date              : ${DATE}"
echo "Results base      : results/${BASE_LABEL}/"
echo "Logs              : logs/${BASE_LABEL}/"
echo ""

# ── Submit SRRIP-Live with threshold sweep (5 jobs) ───────────────────────────
echo "Submitting SRRIP-Live LLC threshold sweep:"
for thd in "${SRRIP_LIVE_THRESHOLDS[@]}"; do
  RUN_LABEL="${BASE_LABEL}/srrip_live_llc/thd${thd}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "qmm_srrip_live_thd${thd}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 \
             -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="champsim_srrip_live",\
MID_THD="$thd",BHIST_MODE="pc" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] srrip_live_llc thd=${thd}"
done

finish_submission $(( 5 * N )) "${BASE_LABEL}"
