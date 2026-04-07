#!/usr/bin/env bash
# sweep_cs.sh - submit threshold sweep experiments across all configurations
# Usage: ./sweep_cs.sh {maz|qmm|dpc3|google|test} [--debug] [--baseline-only] [--warmup N] [--sim N]
#
# --debug          Run only srv_128 instead of all traces (quick sanity check)
# --baseline-only  Submit only the baseline config (dppred=0, cbpred=0) for
#                  liveness-only studies; skips all 56 threshold sweep configs
# --pref           Use champsim_lru_mid_pref (L1D=ip_stride, L2C=spp_dev) instead
#                  of champsim_lru_mid; requires ./build_all.sh --pref first
# --warmup N       Override warmup instructions (default: per trace-set)
# --sim    N       Override simulation instructions (default: per trace-set)
#
# Configurations submitted (default):
#   baseline             : dppred=0, cbpred=0
#   pthd{0..6}           : dppred=1, cbpred=0, pconf_thd=0..6
#   pthd{0..6}_bthd{0..6}: dppred=1, cbpred=1, pconf_thd=0..6, bconf_thd=0..6
# Total: 1 + 7 + 49 = 57 configs
# With --baseline-only: 1 config

set -euo pipefail

# Resolve the directory this script lives in so all paths are absolute
# regardless of where the caller invokes it from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── Argument parsing ──────────────────────────────────────────────────────────
token=""
DEBUG=0
BASELINE_ONLY=0
WITH_PREF=0
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    maz|mazumdar|qmm|dpc3|google|test) token="${1,,}"; shift ;;
    --debug)          DEBUG=1; shift ;;
    --baseline-only)  BASELINE_ONLY=1; shift ;;
    --pref)           WITH_PREF=1; shift ;;
    --warmup)         WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)            SIM_OVERRIDE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {maz|qmm|dpc3|google|test} [--debug] [--baseline-only] [--pref] [--warmup N] [--sim N]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {maz|qmm|dpc3|google|test} [--debug] [--baseline-only] [--pref] [--warmup N] [--sim N]" >&2
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

# Apply overrides after defaults are set
[ -n "$WARMUP_OVERRIDE" ] && WARMUP="$WARMUP_OVERRIDE"
[ -n "$SIM_OVERRIDE" ]    && SIM="$SIM_OVERRIDE"

# ── Resolve trace list ────────────────────────────────────────────────────────
mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N=${#TRACES[@]}
if [ "$N" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2
  exit 2
fi

if [ "$DEBUG" -eq 1 ]; then
  TASK_RANGE="1-1"
  MODE_TAG="_debug"
else
  TASK_RANGE="1-${N}"
  MODE_TAG=""
fi

SWEEP_BINARY="champsim_lru_mid"
PREF_TAG=""
if [ "${WITH_PREF}" -eq 1 ]; then
  SWEEP_BINARY="champsim_lru_mid_pref"
  PREF_TAG="_pref"
fi

DATE=$(date +%Y%m%d_%H%M)
BASE_LABEL="${token}${PREF_TAG}_${DATE}${MODE_TAG}"

LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# ── Build config list: (exp_name dppred cbpred pconf_thd bconf_thd) ──────────
configs=()
configs+=("baseline 0 0 0 0")
if [ "$BASELINE_ONLY" -eq 0 ]; then
  for thd in $(seq 0 6); do
    configs+=("pthd${thd} 1 0 ${thd} 0")
  done
  for pthd in $(seq 0 6); do
    for bthd in $(seq 0 6); do
      configs+=("pthd${pthd}_bthd${bthd} 1 1 ${pthd} ${bthd}")
    done
  done
fi

echo "Submitting ${#configs[@]} configurations × ${N} traces (tasks ${TASK_RANGE})"
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
             -N "cs_${exp_name}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",RUN_LABEL="$RUN_LABEL",BINARY="$SWEEP_BINARY",DPPRED="$dppred",CBPRED="$cbpred",PCONF_THD="$pconf_thd",BCONF_THD="$bconf_thd" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}"
done

echo ""
echo "All configs submitted. Monitor with: qstat -u \$USER"
echo "Results will appear under: results/${BASE_LABEL}/"
