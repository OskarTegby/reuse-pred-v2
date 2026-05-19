#!/usr/bin/env bash
# sweep_llc_half_bypass.sh — submit bypass-predictor comparison under 1 MB LLC.
#
# Three configs per suite:
#   lru         — plain LRU baseline (no predictor)
#   lru_dp_only — dpPred only        (DPPRED=1, CBPRED=0)
#   lru_pred    — dpPred + cbPred    (DPPRED=1, CBPRED=1)
#
# Binary: champsim_lru_llc_half  (1024-set LLC = 1 MB, must be rebuilt via
#         scripts/build_cache_size_study.sh llc before running this script)
#
# Usage: ./sweep_llc_half_bypass.sh {dpc3|google|qmm|test} [--test] [--debug]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

token=""
DEBUG=0
TEST=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    qmm|dpc3|google|test) token="${1,,}"; shift ;;
    --test)  TEST=1; shift ;;
    --debug) DEBUG=1; shift ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {qmm|dpc3|google|test} [--test] [--debug]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {qmm|dpc3|google|test} [--test] [--debug]" >&2; exit 2
fi

SHARED_TRACES=/home/users/shared/traces
BINARY="champsim_lru_llc_half"

case "$token" in
  qmm)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM"
    TRACE_EXT="champsimtrace.xz"
    MID_KEY=1 ;;
  dpc3)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/dpc3_traces"
    TRACE_EXT="champsimtrace.xz"
    MID_KEY=0 ;;
  google)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/Google_Traces_v2"
    TRACE_EXT="champsim.gz"
    MID_KEY=1 ;;
  test)
    WARMUP=25000000; SIM=50000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/TEST"
    TRACE_EXT="champsimtrace.xz"
    MID_KEY=0 ;;
esac

[ "$TEST" -eq 1 ] && { WARMUP=25000000; SIM=50000000; }

mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N=${#TRACES[@]}
[ "$N" -eq 0 ] && { echo "ERROR: no traces in ${TRACE_DIR}" >&2; exit 2; }

if [ "$TEST" -eq 1 ]; then
  TASK_RANGE="1-$(( N < 5 ? N : 5 ))"
elif [ "$DEBUG" -eq 1 ]; then
  TASK_RANGE="1-1"
else
  TASK_RANGE="1-${N}"
fi

DATE=$(date +%Y%m%d_%H%M)
TEST_TAG=$( [ "$TEST" -eq 1 ] && echo "_test" || echo "" )
BASE_LABEL="${token}_llc_half_${DATE}${TEST_TAG}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"
source "${SCRIPT_DIR}/_manifest.sh"
write_manifest

if [ ! -x "${PROJECT_ROOT}/bin/${BINARY}" ]; then
  echo "ERROR: binary not found: bin/${BINARY}" >&2
  echo "Run: scripts/build_cache_size_study.sh llc" >&2
  exit 2
fi

# Three configs: baseline, dpPred only, dpPred + cbPred
configs=(
  "lru         0 0 6 6"
  "lru_dp_only 1 0 6 6"
  "lru_pred    1 1 6 6"
)

MID_KEY_STR=$([ "$MID_KEY" -eq 1 ] && echo "pc" || echo "addr")

echo "Submitting ${#configs[@]} configs × ${N} traces (${TASK_RANGE})"
echo "Binary  : ${BINARY}  (LLC = 1 MB)"
echo "mid_key : ${MID_KEY_STR} (MID_KEY=${MID_KEY})"
echo "Results : results/${BASE_LABEL}/"
echo "Logs    : logs/${BASE_LABEL}/"
echo ""

for cfg in "${configs[@]}"; do
  read -r exp_name dppred cbpred pconf bconf <<< "$cfg"
  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "llch_${exp_name:0:8}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",DPPRED="$dppred",CBPRED="$cbpred",PCONF_THD="$pconf",BCONF_THD="$bconf",MID_THD=1,MID_KEY="$MID_KEY",MID_PROMOTE=0 \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}  (DPPRED=${dppred}, CBPRED=${cbpred})"
done

echo ""
echo "Monitor: qstat -u \$USER"
echo "Results: results/${BASE_LABEL}/"
