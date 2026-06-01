#!/bin/bash
# sweep_three_policies_stlb.sh — submit STLB replacement policy comparison
# Same as LLC study but tests STLB instead:
# 1. champsim_lru (baseline: standard LRU) — 1 job
# 2. champsim_srrip (control: standard SRRIP) — 1 job
# 3. champsim_srrip_live (test: SRRIP with liveness in STLB) — 5 jobs at thresholds {1,2,4,8,16}
#
# Usage: ./sweep_three_policies_stlb.sh {dpc3|google|qmm|gap|gms|ligra|ml} [--debug]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_lib.sh"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SHARED_TRACES=/home/users/shared/traces

# ── Argument parsing ──────────────────────────────────────────────────────────
token=""
DEBUG=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    dpc3|google|qmm|gap|gms|ligra|ml) token="${1,,}"; shift ;;
    --debug) DEBUG=1; shift ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 {dpc3|google|qmm|gap|gms|ligra|ml} [--debug]" >&2
      exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {dpc3|google|qmm|gap|gms|ligra|ml} [--debug]" >&2
  exit 2
fi

# ── Trace-set settings ────────────────────────────────────────────────────────
WARMUP=50000000
SIM=100000000

case "$token" in
  dpc3)
    TRACE_DIR="${SHARED_TRACES}/dpc3_traces"
    TRACE_EXT="champsimtrace.xz"
    ;;
  google)
    TRACE_DIR="${SHARED_TRACES}/Google_Traces_v2"
    TRACE_EXT="champsim.gz"
    ;;
  qmm)
    TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM"
    TRACE_EXT="champsimtrace.xz"
    ;;
  gap)
    TRACE_DIR="${PROJECT_ROOT}/trace-files/gap"
    TRACE_EXT="trace.gz"
    ;;
  gms)
    TRACE_DIR="${PROJECT_ROOT}/trace-files/gms"
    TRACE_EXT="champsimtrace.gz"
    ;;
  ligra)
    TRACE_DIR="${PROJECT_ROOT}/trace-files/ligra"
    TRACE_EXT="champsimtrace.xz"
    ;;
  ml)
    TRACE_DIR="${PROJECT_ROOT}/trace-files/ml"
    TRACE_EXT="champsimtrace.gz"
    ;;
esac

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
BASE_LABEL="${token}_policy_sweep_stlb_${DATE}${DEBUG_TAG}"

LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# ── Thresholds for SRRIP-Live only ─────────────────────────────────────────────
SRRIP_LIVE_THRESHOLDS=(1 2 4 8 16)

echo "Suite             : ${token} (STLB study)"
echo "Traces            : ${N}  (tasks ${TASK_RANGE})"
echo "Total job arrays  : 7 (1 LRU + 1 SRRIP + 5 SRRIP-Live thresholds)"
echo "Date              : ${DATE}"
echo "Results base      : results/${BASE_LABEL}/"
echo "Logs              : logs/${BASE_LABEL}/"
echo ""

# ── Submit LRU baseline (1 job, no threshold) ──────────────────────────────────
echo "Submitting baseline and control (STLB):"
RUN_LABEL="${BASE_LABEL}/lru_baseline"
mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

raw=$(qsub -t "$TASK_RANGE" \
           -N "stlb_${token}_lru_baseline" \
           -o "${LOG_DIR}/" \
           -e "${LOG_DIR}/" \
           -l h_rt=24:00:00 \
           -l mem_free=1G \
           -wd "$PROJECT_ROOT" \
           -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="champsim_lru" \
           "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
echo "  [jid=${jid}] lru_baseline (champsim_lru)"

# ── Submit SRRIP default (1 job, no threshold) ─────────────────────────────────
RUN_LABEL="${BASE_LABEL}/srrip_default"
mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

raw=$(qsub -t "$TASK_RANGE" \
           -N "stlb_${token}_srrip_default" \
           -o "${LOG_DIR}/" \
           -e "${LOG_DIR}/" \
           -l h_rt=24:00:00 \
           -l mem_free=1G \
           -wd "$PROJECT_ROOT" \
           -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="champsim_srrip" \
           "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
echo "  [jid=${jid}] srrip_default (champsim_srrip)"

# ── Submit SRRIP-Live with threshold sweep for STLB (5 jobs) ─────────────────
echo ""
echo "Submitting SRRIP-Live STLB threshold sweep:"
for thd in "${SRRIP_LIVE_THRESHOLDS[@]}"; do
  RUN_LABEL="${BASE_LABEL}/srrip_live_stlb/thd${thd}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "stlb_${token}_srrip_live_thd${thd}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 \
             -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="champsim_srrip_live",\
MID_THD="$thd",SRRIP_LIVE_TARGET="stlb",BHIST_MODE="pc" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] srrip_live_stlb thd=${thd} (SRRIP_LIVE_TARGET=stlb)"
done

finish_submission $(( 7 * N )) "${BASE_LABEL}"
