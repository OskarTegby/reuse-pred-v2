#!/usr/bin/env bash
# sweep_queue_size.sh — PFQ and shadow-table size scaling study.
#
# Both structures are FIFO queues; this script scales each independently
# from size 1 through 512 (powers of 2) plus an effectively infinite
# reference, keeping the other at its default size while sweeping.
#
#   PFQ sweep  (ST_SIZE=2 fixed):   pfq_1 … pfq_512, pfq_inf   (8 is default)
#   ST sweep   (PFQ_CAP=8 fixed):   st_1  … st_512,  st_inf    (2 is default)
#
# One additional baseline (no predictor) is included as an IPC floor.
# All configs use hashed history tables (PHIST_HASH=1, BHIST_HASH=1) at default sizes (phist=1024 ways, bhist=4096 ways).
#
# Total configs: 1 baseline + 10 PFQ + 1 pfq_inf + 10 ST + 1 st_inf = 23
#
# Usage: ./sweep_queue_size.sh {maz|qmm|dpc3|google|gap|ligra|gms|ml|test} [--debug] [--warmup N] [--sim N]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

token=""
DEBUG=0
TEST=0
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    maz|mazumdar|qmm|dpc3|google|gap|ligra|gms|ml|test) token="${1,,}"; shift ;;
    --test)    TEST=1; shift ;;
    --debug)   DEBUG=1; shift ;;
    --warmup)  WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)     SIM_OVERRIDE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {maz|qmm|dpc3|google|gap|ligra|gms|ml|test} [--test] [--debug] [--warmup N] [--sim N]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {maz|qmm|dpc3|google|gap|ligra|gms|ml|test} [--test] [--debug] [--warmup N] [--sim N]" >&2
  exit 2
fi

SHARED_TRACES=/home/users/shared/traces

case "$token" in
  maz|mazumdar)
    WARMUP=100000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/MAZUMDAR"
    TRACE_EXT="champsimtrace.xz"
    ;;
  qmm)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM"
    TRACE_EXT="champsimtrace.xz"
    ;;
  dpc3)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/dpc3_traces"
    TRACE_EXT="champsimtrace.xz"
    ;;
  google)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/Google_Traces_v2"
    TRACE_EXT="champsim.gz"
    ;;
  gap)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/gap"
    TRACE_EXT="trace.gz"
    ;;
  ligra)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/ligra"
    TRACE_EXT="champsimtrace.xz"
    ;;
  gms)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/gms"
    TRACE_EXT="gz"
    ;;
  ml)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/ml"
    TRACE_EXT="champsimtrace.gz"
    ;;
  test)
    WARMUP=25000000; SIM=50000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/TEST"
    TRACE_EXT="champsimtrace.xz"
    ;;
esac

[ -n "$WARMUP_OVERRIDE" ] && WARMUP="$WARMUP_OVERRIDE"
[ -n "$SIM_OVERRIDE" ]    && SIM="$SIM_OVERRIDE"
[ "$TEST" -eq 1 ] && { WARMUP=25000000; SIM=50000000; }

mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N_TRACES=${#TRACES[@]}
if [ "$N_TRACES" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2; exit 2
fi

if [ "$TEST" -eq 1 ]; then
  TASK_RANGE="1-$(( N_TRACES < 5 ? N_TRACES : 5 ))"
elif [ "$DEBUG" -eq 1 ]; then
  TASK_RANGE="1-1"
else
  TASK_RANGE="1-${N_TRACES}"
fi

DATE=$(date +%Y%m%d_%H%M)
TEST_TAG=$( [ "$TEST" -eq 1 ] && echo "_test" || echo "" )
BASE_LABEL="${token}_queue_size_${DATE}${TEST_TAG}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"
source "${SCRIPT_DIR}/_manifest.sh"
write_manifest

# Config format: exp_name binary dppred cbpred pconf_thd bconf_thd pfq_cap st_size
# History tables stay at default hashed mode throughout this study.
configs=()

# Baseline: no predictor, default queue sizes
configs+=("baseline champsim_lru 0 0 6 6 8 2")

# PFQ sweep: scale PFQ from 1 through 128, keep ST at default (2)
for log_pfq in 0 1 2 3 4 5 6 7; do
  pfq=$((1 << log_pfq))
  configs+=("pfq_${pfq} champsim_lru 1 1 6 6 ${pfq} 2")
done
configs+=("pfq_inf champsim_lru 1 1 6 6 1048576 2")

# ST sweep: scale ST from 1 through 128, keep PFQ at default (8)
for log_st in 0 1 2 3 4 5 6 7; do
  st=$((1 << log_st))
  configs+=("st_${st} champsim_lru 1 1 6 6 8 ${st}")
done
configs+=("st_inf champsim_lru 1 1 6 6 8 1048576")

echo "Submitting ${#configs[@]} configurations × ${N_TRACES} traces (tasks ${TASK_RANGE})"
echo "Warmup / Sim : ${WARMUP} / ${SIM}"
echo "Results base : results/${BASE_LABEL}/"
echo "Logs         : logs/${BASE_LABEL}/"
echo ""

for config in "${configs[@]}"; do
  read -r exp_name binary dppred cbpred pconf_thd bconf_thd pfq_cap st_size <<< "$config"

  if [ ! -x "${PROJECT_ROOT}/bin/${binary}" ]; then
    echo "  ERROR: binary not found: bin/${binary}" >&2; exit 2
  fi

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "qs_${exp_name:0:12}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",RUN_LABEL="$RUN_LABEL",BINARY="$binary",DPPRED="$dppred",CBPRED="$cbpred",PCONF_THD="$pconf_thd",BCONF_THD="$bconf_thd",MID_THD=1,MID_KEY=0,MID_PROMOTE=0,PHIST_HASH=1,BHIST_HASH=1,PFQ_CAP="$pfq_cap",ST_SIZE="$st_size" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  printf "  [jid=%-8s] %s\n" "$jid" "$exp_name"
done

echo ""
echo "All configs submitted. Monitor with: qstat -u \$USER"
echo "Results will appear under: results/${BASE_LABEL}/"
