#!/bin/bash
# sweep_three_policies.sh — submit threshold sweeps for three LLC replacement policies
# 1. champsim_lru (baseline: standard LRU)
# 2. champsim_srrip (control: standard SRRIP, no liveness guidance)
# 3. champsim_srrip_live (test: SRRIP with liveness guidance in LLC only)
#
# Usage: ./sweep_three_policies.sh {dpc3|google|qmm|gap|gms|ligra|ml} [--debug]

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
BASE_LABEL="${token}_policy_sweep_pc_${DATE}${DEBUG_TAG}"

LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# ── Define three policies ──────────────────────────────────────────────────────
declare -a POLICIES=(
  "champsim_lru:lru_baseline"
  "champsim_srrip:srrip_default"
  "champsim_srrip_live:srrip_live_llc"
)

echo "Suite         : ${token}"
echo "Traces        : ${N}  (tasks ${TASK_RANGE})"
echo "Policies      : ${#POLICIES[@]}"
echo "Date          : ${DATE}"
echo "Results base  : results/${BASE_LABEL}/"
echo "Logs          : logs/${BASE_LABEL}/"
echo ""

# ── Submit all policies ────────────────────────────────────────────────────────
for policy_spec in "${POLICIES[@]}"; do
  IFS=":" read -r BINARY POLICY_NAME <<< "$policy_spec"

  RUN_LABEL="${BASE_LABEL}/${POLICY_NAME}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "pol_${token}_${POLICY_NAME}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 \
             -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$BINARY" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${POLICY_NAME} (${BINARY})"
done

finish_submission $(( ${#POLICIES[@]} * N )) "${BASE_LABEL}"
