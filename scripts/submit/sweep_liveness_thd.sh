#!/usr/bin/env bash
# sweep_liveness_thd.sh — mid_thd threshold sweep for any liveness-based policy.
#
# Runs the given binary at mid_thd = 1, 2, 4, 8, 16.
# Per-token MID_KEY defaults: pc for Google/Qualcomm, addr for DPC3/test.
#
# Usage:
#   ./sweep_liveness_thd.sh {dpc3|google|qmm|test} {srrip_live|ipv_live|pacipv} \
#       [--mid-key addr|pc] [--debug] [--warmup N] [--sim N]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── Argument parsing ──────────────────────────────────────────────────────────
token=""
policy=""
DEBUG=0
TEST=0
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""
MID_KEY_STR=""
MID_KEY_VAL=""
THD_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    dpc3|google|qmm|test)        token="${1,,}"; shift ;;
    srrip_live|ipv_live|stlb_ipv_live|ipv_live_both|pacipv|srrip_live_both)  policy="$1";   shift ;;
    --test)    TEST=1; shift ;;
    --debug)   DEBUG=1; shift ;;
    --warmup)  WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)     SIM_OVERRIDE="$2";    shift 2 ;;
    --mid-key)
      case "$2" in
        addr) MID_KEY_STR="addr"; MID_KEY_VAL=0 ;;
        pc)   MID_KEY_STR="pc";   MID_KEY_VAL=1 ;;
        *) echo "Unknown --mid-key value: $2 (expected addr or pc)" >&2; exit 2 ;;
      esac
      shift 2 ;;
    --thd)   THD_OVERRIDE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {dpc3|google|qmm|test} {srrip_live|ipv_live|stlb_ipv_live|ipv_live_both|pacipv|srrip_live_both} [--mid-key addr|pc] [--thd N] [--test] [--debug] [--warmup N] [--sim N]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ] || [ -z "$policy" ]; then
  echo "Usage: $0 {dpc3|google|qmm|test} {srrip_live|ipv_live|stlb_ipv_live|ipv_live_both|pacipv|srrip_live_both} [--mid-key addr|pc] [--test] [--debug] [--warmup N] [--sim N]" >&2
  exit 2
fi

SHARED_TRACES=/home/users/shared/traces

# ── Trace-set settings + per-token MID_KEY default ────────────────────────────
case "$token" in
  dpc3)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/dpc3_traces"; TRACE_EXT="champsimtrace.xz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="addr"; MID_KEY_VAL=0; } ;;
  google)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/Google_Traces_v2"; TRACE_EXT="champsim.gz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="pc"; MID_KEY_VAL=1; } ;;
  qmm)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM"; TRACE_EXT="champsimtrace.xz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="pc"; MID_KEY_VAL=1; } ;;
  test)
    WARMUP=25000000; SIM=50000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/TEST"; TRACE_EXT="champsimtrace.xz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="addr"; MID_KEY_VAL=0; } ;;
esac

[ -n "$WARMUP_OVERRIDE" ] && WARMUP="$WARMUP_OVERRIDE"
[ -n "$SIM_OVERRIDE" ]    && SIM="$SIM_OVERRIDE"
[ "$TEST" -eq 1 ] && { WARMUP=25000000; SIM=50000000; }

BINARY="champsim_${policy}"
if [ ! -x "${PROJECT_ROOT}/bin/${BINARY}" ]; then
  echo "ERROR: binary not found: bin/${BINARY}" >&2
  echo "Run ./build_all.sh first." >&2
  exit 2
fi

# ── Resolve trace list ────────────────────────────────────────────────────────
mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N=${#TRACES[@]}
if [ "$N" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2; exit 2
fi

if   [ "$TEST"  -eq 1 ]; then TASK_RANGE="1-$(( N < 5 ? N : 5 ))"
elif [ "$DEBUG" -eq 1 ]; then TASK_RANGE="1-1"
else                          TASK_RANGE="1-${N}"
fi

DATE=$(date +%Y%m%d_%H%M)
TEST_TAG=$( [ "$TEST" -eq 1 ] && echo "_test" || echo "" )
BASE_LABEL="${token}_${policy}_thd_${MID_KEY_STR}_${DATE}${TEST_TAG}"

LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"
source "${SCRIPT_DIR}/_manifest.sh"
write_manifest

THD_VALUES=(1 2 4 8 16)
[ -n "$THD_OVERRIDE" ] && THD_VALUES=("$THD_OVERRIDE")

echo "Submitting ${#THD_VALUES[@]} mid_thd values × ${N} traces (tasks ${TASK_RANGE})"
echo "Binary        : ${BINARY}"
echo "mid_key       : ${MID_KEY_STR} (MID_KEY=${MID_KEY_VAL})"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "Results base  : results/${BASE_LABEL}/"
echo ""

for thd in "${THD_VALUES[@]}"; do
  exp_name="${policy}_thd${thd}"
  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "${policy:0:8}_t${thd}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",DPPRED=0,CBPRED=0,PCONF_THD=6,BCONF_THD=6,MID_THD="$thd",MID_KEY="$MID_KEY_VAL",MID_PROMOTE=0 \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}"
done

echo ""
echo "Monitor with: qstat -u \$USER"
echo "Results under: results/${BASE_LABEL}/"
