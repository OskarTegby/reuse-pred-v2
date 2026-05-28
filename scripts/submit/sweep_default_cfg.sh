#!/usr/bin/env bash
# sweep_default_cfg.sh — submit baseline, default_bypass, optimal_bypass, and dppred_only.
#
# Supports two LLC configs:
#   --llc 1mb   champsim_verify     (1MB LLC, 40-cycle)
#   --llc 2mb   champsim_verify_2mb (2MB LLC, 20-cycle, Mazumdar original)
#
# Submits four configurations:
#   baseline       : DPPRED=0, CBPRED=0
#   default_bypass : DPPRED=1, CBPRED=1, PCONF_THD=6, BCONF_THD=6
#   optimal_bypass : DPPRED=1, CBPRED=1, PCONF_THD=0, BCONF_THD=0
#   dppred_only    : DPPRED=1, CBPRED=0, PCONF_THD=6
#
# Usage: ./sweep_default_cfg.sh {gap|gms|ligra|ml|qmm|dpc3|google} --llc {1mb|2mb} [--debug]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_lib.sh"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SHARED_TRACES=/home/users/shared/traces

token=""
llc_size=""
DEBUG=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    gap|gms|ligra|ml|qmm|dpc3|google) token="${1,,}"; shift ;;
    --llc) llc_size="${2,,}"; shift 2 ;;
    --debug) DEBUG=1; shift ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 {gap|gms|ligra|ml|qmm|dpc3|google} --llc {1mb|2mb} [--debug]" >&2
      exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {gap|gms|ligra|ml|qmm|dpc3|google} --llc {1mb|2mb} [--debug]" >&2
  exit 2
fi

if [ -z "$llc_size" ]; then
  echo "ERROR: --llc {1mb|2mb} is required" >&2
  exit 2
fi

WARMUP=50000000
SIM=100000000

case "$token" in
  qmm)
    TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM"
    TRACE_EXT="champsimtrace.xz"
    ;;
  dpc3)
    TRACE_DIR="${SHARED_TRACES}/dpc3_traces"
    TRACE_EXT="champsimtrace.xz"
    ;;
  google)
    TRACE_DIR="${SHARED_TRACES}/Google_Traces_v2"
    TRACE_EXT="champsim.gz"
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

case "$llc_size" in
  1mb) SWEEP_BINARY="champsim_verify" ;;
  2mb) SWEEP_BINARY="champsim_verify_2mb" ;;
  *)
    echo "ERROR: --llc must be 1mb or 2mb, got: ${llc_size}" >&2
    exit 2 ;;
esac

DATE=$(date +%Y%m%d_%H%M)
BASE_LABEL="${token}_${llc_size}_${DATE}${DEBUG_TAG}"

LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# name  DPPRED CBPRED PCONF_THD BCONF_THD
configs=(
  "baseline        0 0 0 0"
  "default_bypass  1 1 6 6"
  "optimal_bypass  1 1 0 0"
  "dppred_only     1 0 6 0"
)

echo "Suite         : ${token}"
echo "Traces        : ${N}  (tasks ${TASK_RANGE})"
echo "Configs       : ${#configs[@]}  (baseline, default_bypass, optimal_bypass, dppred_only)"
echo "Binary        : ${SWEEP_BINARY}"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "Results base  : results/${BASE_LABEL}/"
echo "Logs          : logs/${BASE_LABEL}/"
echo ""

for config in "${configs[@]}"; do
  read -r exp_name dppred cbpred pconf_thd bconf_thd <<< "$config"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "dcfg_${token}_${exp_name}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 \
             -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$SWEEP_BINARY",\
DPPRED="$dppred",CBPRED="$cbpred",\
PCONF_THD="$pconf_thd",BCONF_THD="$bconf_thd" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}"
done

finish_submission $(( ${#configs[@]} * N )) "${BASE_LABEL}"
