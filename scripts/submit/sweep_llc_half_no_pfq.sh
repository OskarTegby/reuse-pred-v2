#!/usr/bin/env bash
# sweep_llc_half_no_pfq.sh — cbPred without PFQ gate under 1 MB LLC.
#
# Runs two configs per suite to isolate the PFQ gate's contribution:
#   lru_pred_pfq    — dpPred + cbPred with PFQ gate (standard)
#   lru_pred_no_pfq — dpPred + cbPred, CBPRED_NO_PFQ=1 (bypass on bhist alone)
#
# Both use the same binary (champsim_lru_llc_half) and the same thresholds
# (pconf=6, bconf=6). The only difference is whether cbPred requires a PFQ hit.
#
# Binary: champsim_lru_llc_half (1 MB LLC) — must be up to date with CBPRED_NO_PFQ support.
#
# Usage: ./sweep_llc_half_no_pfq.sh {dpc3|google|qmm|test} [--test] [--debug]

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
    TRACE_EXT="champsimtrace.xz" ;;
  dpc3)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/dpc3_traces"
    TRACE_EXT="champsimtrace.xz" ;;
  google)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/Google_Traces_v2"
    TRACE_EXT="champsim.gz" ;;
  test)
    WARMUP=25000000; SIM=50000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/TEST"
    TRACE_EXT="champsimtrace.xz" ;;
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
BASE_LABEL="${token}_llc_half_nopfq_${DATE}${TEST_TAG}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"
source "${SCRIPT_DIR}/_manifest.sh"
write_manifest

if [ ! -x "${PROJECT_ROOT}/bin/${BINARY}" ]; then
  echo "ERROR: binary not found: bin/${BINARY}" >&2
  echo "Run: scripts/build_cache_size_study.sh llc && rebuild with CBPRED_NO_PFQ support" >&2
  exit 2
fi

# exp_name  dppred cbpred no_pfq pconf bconf
configs=(
  "lru_pred        1 1 0 6 6"
  "lru_pred_no_pfq 1 1 1 6 6"
)

echo "Submitting ${#configs[@]} configs × ${N} traces (${TASK_RANGE})"
echo "Binary  : ${BINARY}  (LLC = 1 MB)"
echo "Results : results/${BASE_LABEL}/"
echo "Logs    : logs/${BASE_LABEL}/"
echo ""

for cfg in "${configs[@]}"; do
  read -r exp_name dppred cbpred no_pfq pconf bconf <<< "$cfg"
  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "nopfq_${exp_name:0:8}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",DPPRED="$dppred",CBPRED="$cbpred",CBPRED_NO_PFQ="$no_pfq",PCONF_THD="$pconf",BCONF_THD="$bconf",MID_THD=1,MID_KEY=0,MID_PROMOTE=0 \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}  (CBPRED_NO_PFQ=${no_pfq})"
done

echo ""
echo "Monitor: qstat -u \$USER"
echo "Results: results/${BASE_LABEL}/"
