#!/usr/bin/env bash
# sweep_oldcfg_bypass.sh — submit baseline + bypass(0,0) for one suite under the old config.
#
# Uses champsim_verify (old config: LLC=20 cycles, L2C=10 cycles, STLB=12 ways).
# Submits two configurations:
#   baseline   : DPPRED=0, CBPRED=0
#   bypass_00  : DPPRED=1, CBPRED=1, PCONF_THD=0, BCONF_THD=0
#
# Usage: ./sweep_oldcfg_bypass.sh {qmm|dpc3|google|gap|gms|ligra|ml} [--debug]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_lib.sh"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SHARED_TRACES=/home/users/shared/traces

token=""
DEBUG=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    qmm|dpc3|google|gap|gms|ligra|ml) token="${1,,}"; shift ;;
    --debug) DEBUG=1; shift ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 {qmm|dpc3|google|gap|gms|ligra|ml} [--debug]" >&2
      exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {qmm|dpc3|google|gap|gms|ligra|ml} [--debug]" >&2
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

SWEEP_BINARY="champsim_verify"
DATE=$(date +%Y%m%d_%H%M)
BASE_LABEL="${token}_oldcfg_bypass_${DATE}${DEBUG_TAG}"

LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

configs=(
  "baseline 0 0 0 0"
  "bypass_00 1 1 0 0"
)

echo "Suite         : ${token}"
echo "Traces        : ${N}  (tasks ${TASK_RANGE})"
echo "Configs       : ${#configs[@]}  (baseline + bypass_00)"
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
             -N "byp_${token}_${exp_name}" \
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
