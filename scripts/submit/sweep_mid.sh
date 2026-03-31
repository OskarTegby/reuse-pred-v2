#!/usr/bin/env bash
# sweep_mid.sh — sweep mid_thd (mid-insertion threshold) from 1 to MAX_N.
#
# Usage: ./sweep_mid.sh {maz|qmm} [--max-n N] [--pthd N] [--bthd N] [--debug] [--warmup N] [--sim N]
#
# Submits one job array per mid_thd value plus a baseline.  Each run uses
# dppred=1, cbpred=1 with the given pconf_thd/bconf_thd (default 6/6) so the
# history tables are populated.  mid_thd controls how many consecutive DoA or
# mostly-dead evictions are required before the lru_mid policy inserts a new
# block at the set midpoint rather than MRU.
#
# Configurations submitted:
#   baseline              : dppred=0, cbpred=0, mid_thd=1
#   mid_thd{1..MAX_N}     : dppred=1, cbpred=1, pconf_thd=PTHD, bconf_thd=BTHD, mid_thd=1..MAX_N
# Total: 1 + MAX_N configs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── Argument parsing ──────────────────────────────────────────────────────────
token=""
DEBUG=0
MAX_N=5
PTHD=6
BTHD=6
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    maz|mazumdar|qmm|dpc3|google|test) token="${1,,}"; shift ;;
    --max-n)   MAX_N="$2"; shift 2 ;;
    --pthd)    PTHD="$2";  shift 2 ;;
    --bthd)    BTHD="$2";  shift 2 ;;
    --debug)   DEBUG=1; shift ;;
    --warmup)  WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)     SIM_OVERRIDE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {maz|qmm} [--max-n N] [--pthd N] [--bthd N] [--debug] [--warmup N] [--sim N]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {maz|qmm} [--max-n N] [--pthd N] [--bthd N] [--debug] [--warmup N] [--sim N]" >&2
  exit 2
fi

SHARED_TRACES=/home/users/shared/traces

# ── Trace-set settings ────────────────────────────────────────────────────────
case "$token" in
  maz|mazumdar)
    WARMUP=100000000
    SIM=1000000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/MAZUMDAR"
    TRACE_EXT="champsimtrace.xz"
    ;;
  qmm)
    WARMUP=50000000
    SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM"
    TRACE_EXT="champsimtrace.xz"
    ;;
  dpc3)
    WARMUP=50000000
    SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/dpc3_traces"
    TRACE_EXT="champsimtrace.xz"
    ;;
  google)
    WARMUP=50000000
    SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/Google_Traces_v2"
    TRACE_EXT="champsim.gz"
    ;;
  test)
    WARMUP=1000000
    SIM=5000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/TEST"
    TRACE_EXT="champsimtrace.xz"
    ;;
esac

[ -n "$WARMUP_OVERRIDE" ] && WARMUP="$WARMUP_OVERRIDE"
[ -n "$SIM_OVERRIDE" ]    && SIM="$SIM_OVERRIDE"

# ── Resolve trace list ────────────────────────────────────────────────────────
mapfile -t TRACES < <(ls -1 "${TRACE_DIR}"/*.${TRACE_EXT} 2>/dev/null | sort)
N=${#TRACES[@]}
if [ "$N" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2
  exit 2
fi

if [ "$DEBUG" -eq 1 ]; then
  TASK_RANGE=""
  for i in "${!TRACES[@]}"; do
    if [[ "${TRACES[$i]}" == *srv_128* ]]; then
      TASK_RANGE="$((i+1))-$((i+1))"
      break
    fi
  done
  if [ -z "$TASK_RANGE" ]; then
    echo "WARNING: srv_128 not found in ${TRACE_DIR} — using task 1 instead" >&2
    TASK_RANGE="1-1"
  fi
  MODE_TAG="_debug"
else
  TASK_RANGE="1-${N}"
  MODE_TAG=""
fi

DATE=$(date +%Y%m%d_%H%M)
BASE_LABEL="${token}_mid_${DATE}${MODE_TAG}"

LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# ── Build config list: (exp_name dppred cbpred pconf_thd bconf_thd mid_thd) ──
configs=()
configs+=("baseline 0 0 0 0 1")
for mthd in $(seq 1 "$MAX_N"); do
  configs+=("mid_thd${mthd} 1 1 ${PTHD} ${BTHD} ${mthd}")
done

echo "Submitting ${#configs[@]} configurations × ${N} traces (tasks ${TASK_RANGE})"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "pconf_thd     : ${PTHD}    bconf_thd: ${BTHD}"
echo "mid_thd sweep : 1..${MAX_N}"
echo "Results base  : results/${BASE_LABEL}/"
echo "Logs          : logs/${BASE_LABEL}/"
echo ""

# ── Submit all configs ────────────────────────────────────────────────────────
for config in "${configs[@]}"; do
  read -r exp_name dppred cbpred pconf_thd bconf_thd mid_thd <<< "$config"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "cs_${exp_name}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "\$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",RUN_LABEL="$RUN_LABEL",DPPRED="$dppred",CBPRED="$cbpred",PCONF_THD="$pconf_thd",BCONF_THD="$bconf_thd",MID_THD="$mid_thd" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}"
done

echo ""
echo "All configs submitted. Monitor with: qstat -u \$USER"
echo "Results will appear under: results/${BASE_LABEL}/"
echo ""
echo "Plot with:"
echo "  python3 plot_heatmap.py results/${BASE_LABEL}/ --mid-thd --max-n ${MAX_N}"
