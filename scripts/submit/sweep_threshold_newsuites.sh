#!/usr/bin/env bash
# sweep_threshold_newsuites.sh — submit 57-config dpPred/cbPred threshold sweep
# for suites not covered by the original sweep_cs.sh (Google, GAP, GMS, Ligra, ML).
#
# Uses champsim_verify (old dpPred/cbPred code, standard 40-cycle LLC config).
#
# Usage: ./sweep_threshold_newsuites.sh {google|gap|gms|ligra|ml} [--debug]
#
# --debug    Run only the first trace (task 1) as a sanity check.
#
# Configurations submitted (57 total):
#   baseline               : dppred=0, cbpred=0
#   pthd{0..6}             : dppred=1, cbpred=0, pconf_thd=0..6
#   pthd{0..6}_bthd{0..6}  : dppred=1, cbpred=1, pconf_thd=0..6, bconf_thd=0..6

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
    google|gap|gms|ligra|ml) token="${1,,}"; shift ;;
    --debug) DEBUG=1; shift ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 {google|gap|gms|ligra|ml} [--debug]" >&2
      exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {google|gap|gms|ligra|ml} [--debug]" >&2
  exit 2
fi

# ── Trace-set settings ────────────────────────────────────────────────────────
WARMUP=50000000
SIM=100000000

case "$token" in
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

SWEEP_BINARY="champsim_verify"
DATE=$(date +%Y%m%d_%H%M)
BASE_LABEL="${token}_threshold_verify_${DATE}${DEBUG_TAG}"

LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# ── Build config list: (exp_name dppred cbpred pconf_thd bconf_thd) ──────────
configs=()
configs+=("baseline 0 0 0 0")
for thd in $(seq 0 6); do
  configs+=("pthd${thd} 1 0 ${thd} 0")
done
for pthd in $(seq 0 6); do
  for bthd in $(seq 0 6); do
    configs+=("pthd${pthd}_bthd${bthd} 1 1 ${pthd} ${bthd}")
  done
done

echo "Suite         : ${token}"
echo "Traces        : ${N}  (tasks ${TASK_RANGE})"
echo "Configs       : ${#configs[@]}"
echo "Binary        : ${SWEEP_BINARY}"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "Results base  : results/${BASE_LABEL}/"
echo "Logs          : logs/${BASE_LABEL}/"
echo ""

# ── Submit all configs ────────────────────────────────────────────────────────
for config in "${configs[@]}"; do
  read -r exp_name dppred cbpred pconf_thd bconf_thd <<< "$config"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "thd_${token}_${exp_name}" \
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
