#!/bin/bash
# sweep_mazumdar_threshold.sh — LLC + STLB threshold sweep for Mazumdar config
#
# Runs LRU baseline, LLC SRRIP-Live, LLC IPV-Live, STLB SRRIP-Live, STLB IPV-Live
# at thresholds {1,2,4,8,16} for one suite.
#
# Config: 2 MB LLC (2048x16), 1024-entry STLB (128x8), BHIST_MODE=pc
#
# Usage: ./sweep_mazumdar_threshold.sh {qmm|google} [--debug]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_lib.sh"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SHARED_TRACES=/home/users/shared/traces

# ── Argument parsing ──────────────────────────────────────────────────────────
SUITE=""
DEBUG=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    qmm|google) SUITE="$1"; shift ;;
    --debug) DEBUG=1; shift ;;
    *)
      echo "Usage: $0 {qmm|google} [--debug]" >&2
      exit 2 ;;
  esac
done

if [ -z "$SUITE" ]; then
  echo "Usage: $0 {qmm|google} [--debug]" >&2
  exit 2
fi

# ── Trace configuration ───────────────────────────────────────────────────────
case "$SUITE" in
  qmm)
    TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM"
    TRACE_EXT="champsimtrace.xz"
    ;;
  google)
    TRACE_DIR="${SHARED_TRACES}/Google_Traces_v2"
    TRACE_EXT="champsim.gz"
    ;;
esac

WARMUP=50000000
SIM=100000000

mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N=${#TRACES[@]}
[ "$N" -eq 0 ] && { echo "ERROR: no traces in ${TRACE_DIR}" >&2; exit 2; }

TASK_RANGE="1-${N}"
DEBUG_TAG=""
if [ "$DEBUG" -eq 1 ]; then
  TASK_RANGE="1-1"
  DEBUG_TAG="_debug"
fi

DATE=$(date +%Y%m%d_%H%M)
BASE_LABEL="${SUITE}_maz_thd_${DATE}${DEBUG_TAG}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

THRESHOLDS=(1 2 4 8 16)

echo "Suite       : ${SUITE}"
echo "Config      : 2MB LLC, 1024-entry STLB (Mazumdar)"
echo "Traces      : ${N}  (tasks ${TASK_RANGE})"
echo "Jobs        : 1 LRU + 10 LLC + 10 STLB = 21 arrays x ${N} tasks"
echo "Results dir : results/${BASE_LABEL}/"
echo ""

# ── LRU baseline (shared for LLC and STLB comparisons) ───────────────────────
echo "Submitting LRU baseline..."
RUN_LABEL="${BASE_LABEL}/lru"
mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"
raw=$(qsub -t "$TASK_RANGE" \
           -N "maz_${SUITE}_lru" \
           -o "${LOG_DIR}/" -e "${LOG_DIR}/" \
           -l h_rt=24:00:00 -l mem_free=1G \
           -wd "$PROJECT_ROOT" \
           -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="champsim_lru" \
           "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
echo "  [jid=${jid}] lru"

# ── LLC SRRIP-Live (5 thresholds) ────────────────────────────────────────────
echo "Submitting LLC SRRIP-Live..."
for thd in "${THRESHOLDS[@]}"; do
  RUN_LABEL="${BASE_LABEL}/llc_srrip_live/thd${thd}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"
  raw=$(qsub -t "$TASK_RANGE" \
             -N "maz_${SUITE}_llc_srrip_${thd}" \
             -o "${LOG_DIR}/" -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="champsim_srrip_live",\
MID_THD="$thd",BHIST_MODE="pc" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] llc_srrip_live thd=${thd}"
done

# ── LLC IPV-Live (5 thresholds) ──────────────────────────────────────────────
echo "Submitting LLC IPV-Live..."
for thd in "${THRESHOLDS[@]}"; do
  RUN_LABEL="${BASE_LABEL}/llc_ipv_live/thd${thd}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"
  raw=$(qsub -t "$TASK_RANGE" \
             -N "maz_${SUITE}_llc_ipv_${thd}" \
             -o "${LOG_DIR}/" -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="champsim_ipv_live",\
MID_THD="$thd",BHIST_MODE="pc" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] llc_ipv_live thd=${thd}"
done

# ── STLB SRRIP-Live (5 thresholds) ───────────────────────────────────────────
echo "Submitting STLB SRRIP-Live..."
for thd in "${THRESHOLDS[@]}"; do
  RUN_LABEL="${BASE_LABEL}/stlb_srrip_live/thd${thd}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"
  raw=$(qsub -t "$TASK_RANGE" \
             -N "maz_${SUITE}_stlb_srrip_${thd}" \
             -o "${LOG_DIR}/" -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="champsim_stlb_srrip_live",\
MID_THD="$thd",BHIST_MODE="pc",SRRIP_LIVE_TARGET="stlb" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] stlb_srrip_live thd=${thd}"
done

# ── STLB IPV-Live (5 thresholds) ─────────────────────────────────────────────
echo "Submitting STLB IPV-Live..."
for thd in "${THRESHOLDS[@]}"; do
  RUN_LABEL="${BASE_LABEL}/stlb_ipv_live/thd${thd}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"
  raw=$(qsub -t "$TASK_RANGE" \
             -N "maz_${SUITE}_stlb_ipv_${thd}" \
             -o "${LOG_DIR}/" -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="champsim_stlb_ipv_live",\
MID_THD="$thd",BHIST_MODE="pc",SRRIP_LIVE_TARGET="stlb" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] stlb_ipv_live thd=${thd}"
done

finish_submission $(( 21 * N )) "${BASE_LABEL}"
