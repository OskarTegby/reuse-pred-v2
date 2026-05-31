#!/usr/bin/env bash
# sweep_srrip_live_thd.sh — submit srrip_live (or ipv_live) threshold sweep.
#
# Submits champsim_srrip_live (or --binary champsim_ipv_live) at mid_thd values
# of 1, 2, 4, 8, and 16.  Results land in a single dated directory with one
# subdirectory per threshold value.
#
# Usage: ./sweep_srrip_live_thd.sh {dpc3|google|qmm|test} [--mid-key addr|pc]
#          [--binary <name>] [--selected] [--debug] [--warmup N] [--sim N]
#
# --binary <name>   Override the default champsim_srrip_live binary.
# --selected        Run only the paper-figure workloads (top-4 by dead fraction).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── Argument parsing ──────────────────────────────────────────────────────────
token=""
DEBUG=0
TEST=0
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""
MID_KEY_STR=""   # set per-token below; overridable with --mid-key
MID_KEY_VAL=""
BINARY_OVERRIDE=""
SELECTED=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    dpc3|google|qmm|test) token="${1,,}"; shift ;;
    --test)       TEST=1; shift ;;
    --debug)      DEBUG=1; shift ;;
    --selected)   SELECTED=1; shift ;;
    --warmup)     WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)        SIM_OVERRIDE="$2"; shift 2 ;;
    --binary)     BINARY_OVERRIDE="$2"; shift 2 ;;
    --mid-key)
      case "$2" in
        addr) MID_KEY_STR="addr"; MID_KEY_VAL=0 ;;
        pc)   MID_KEY_STR="pc";   MID_KEY_VAL=1 ;;
        *) echo "Unknown --mid-key value: $2 (expected addr or pc)" >&2; exit 2 ;;
      esac
      shift 2 ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {dpc3|google|qmm|test} [--mid-key addr|pc] [--binary <name>] [--selected] [--test] [--debug] [--warmup N] [--sim N]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {dpc3|google|qmm|test} [--mid-key addr|pc] [--binary <name>] [--selected] [--test] [--debug] [--warmup N] [--sim N]" >&2
  exit 2
fi

SHARED_TRACES=/home/users/shared/traces

# ── Trace-set settings ────────────────────────────────────────────────────────
case "$token" in
  dpc3)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/dpc3_traces"; TRACE_EXT="champsimtrace.xz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="addr"; MID_KEY_VAL=0; }
    # top-4 by combined LLC+STLB dead fraction: bwaves, lbm, imagick, fotonik3d
    SELECTED_FILTER="603\.bwaves_s|619\.lbm_s|638\.imagick_s|649\.fotonik3d_s" ;;
  google)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/Google_Traces_v2"; TRACE_EXT="champsim.gz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="pc"; MID_KEY_VAL=1; }
    SELECTED_FILTER="charlie|merced|arizona|rapids" ;;
  qmm)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM"; TRACE_EXT="champsimtrace.xz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="pc"; MID_KEY_VAL=1; }
    SELECTED_FILTER="camera_photo|facebook|map_tiles|web_search" ;;
  test)
    WARMUP=25000000; SIM=50000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/TEST"; TRACE_EXT="champsimtrace.xz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="addr"; MID_KEY_VAL=0; }
    SELECTED_FILTER="" ;;
esac

[ -n "$WARMUP_OVERRIDE" ] && WARMUP="$WARMUP_OVERRIDE"
[ -n "$SIM_OVERRIDE" ]    && SIM="$SIM_OVERRIDE"
[ "$TEST" -eq 1 ] && { WARMUP=25000000; SIM=50000000; }

# ── Resolve trace list ────────────────────────────────────────────────────────
if [ "$SELECTED" -eq 1 ] && [ -n "${SELECTED_FILTER:-}" ]; then
  mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort | grep -E "${SELECTED_FILTER}")
else
  mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
fi
N=${#TRACES[@]}
if [ "$N" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2
  exit 2
fi

if [ "$TEST" -eq 1 ]; then
  TASK_RANGE="1-$(( N < 5 ? N : 5 ))"
elif [ "$DEBUG" -eq 1 ]; then
  TASK_RANGE="1-1"
else
  TASK_RANGE="1-${N}"
fi

BINARY="${BINARY_OVERRIDE:-champsim_srrip_live}"
if [ ! -x "${PROJECT_ROOT}/bin/${BINARY}" ]; then
  echo "ERROR: binary not found: bin/${BINARY}" >&2
  echo "Run ./build_all.sh first." >&2
  exit 2
fi

DATE=$(date +%Y%m%d_%H%M)
TEST_TAG=$( [ "$TEST" -eq 1 ] && echo "_test" || echo "" )
SEL_TAG=$( [ "$SELECTED" -eq 1 ] && echo "_sel" || echo "" )
KEY_TAG=$( [ "$MID_KEY_STR" = "pc" ] && echo "_pc" || echo "" )

# Derive label prefix from binary name: champsim_ipv_live → ipv_live_thd, else srrip_live_thd
case "${BINARY}" in
  *ipv_live*) LABEL_PREFIX="${token}_ipv_live_thd" ;;
  *)          LABEL_PREFIX="${token}_srrip_live_thd" ;;
esac
BASE_LABEL="${LABEL_PREFIX}${KEY_TAG}_${DATE}${TEST_TAG}${SEL_TAG}"

LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"
source "${SCRIPT_DIR}/_manifest.sh"
write_manifest

THD_VALUES=(1 2 4 8 16)

# Determine per-threshold subdir prefix from binary
case "${BINARY}" in
  *ipv_live*) THD_PREFIX="ipv_live_thd" ;;
  *)          THD_PREFIX="srrip_live_thd" ;;
esac

echo "Submitting ${#THD_VALUES[@]} mid_thd values × ${N} traces (tasks ${TASK_RANGE})"
echo "Binary        : ${BINARY}"
echo "mid_key       : ${MID_KEY_STR} (MID_KEY=${MID_KEY_VAL})"
echo "Selected      : $( [ "$SELECTED" -eq 1 ] && echo yes || echo no )"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "Results base  : results/${BASE_LABEL}/"
echo "Logs          : logs/${BASE_LABEL}/"
echo ""

TRACE_FILTER_VAL="$( [ "$SELECTED" -eq 1 ] && echo "${SELECTED_FILTER}" || echo "" )"

for thd in "${THD_VALUES[@]}"; do
  exp_name="${THD_PREFIX}${thd}"
  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  QSUB_VARS="WARMUP=$WARMUP,SIM=$SIM,TRACE_DIR=$TRACE_DIR,TRACE_EXT=$TRACE_EXT"
  QSUB_VARS+=",RUN_LABEL=$RUN_LABEL,BINARY=$BINARY"
  QSUB_VARS+=",DPPRED=0,CBPRED=0,PCONF_THD=6,BCONF_THD=6"
  QSUB_VARS+=",MID_THD=$thd,MID_KEY=$MID_KEY_VAL,MID_PROMOTE=0"
  [ -n "$TRACE_FILTER_VAL" ] && QSUB_VARS+=",TRACE_FILTER=${TRACE_FILTER_VAL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "${THD_PREFIX}${thd}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v "$QSUB_VARS" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}  (mid_thd=${thd})"
done

echo ""
echo "All configs submitted. Monitor with: qstat -u \$USER"
echo "Results will appear under: results/${BASE_LABEL}/"
