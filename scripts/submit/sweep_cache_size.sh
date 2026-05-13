#!/usr/bin/env bash
# sweep_cache_size.sh — submit liveness/correlation characterisation runs for
# the cache/TLB size study.
#
# Each run uses plain LRU (no predictor, no mid-insertion) so the measured
# liveness distribution and DoA/STLB correlation are uncontaminated by policy.
#
# Expects the binaries produced by:
#   ./scripts/build_cache_size_study.sh
#
# Directory layout:
#   results/<base_label>/baseline/          — champsim_lru (compiled sizes)
#   results/<base_label>/llc_s4096/         — LLC 4096-set variant
#   results/<base_label>/l2c_s1024/         — L2C 1024-set variant
#   ...
#
# Usage:
#   ./scripts/submit/sweep_cache_size.sh {qmm|dpc3|google|test} [--debug] [--warmup N] [--sim N]

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
    qmm|dpc3|google|test) token="${1,,}"; shift ;;
    --test)    TEST=1; shift ;;
    --debug)   DEBUG=1; shift ;;
    --warmup)  WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)     SIM_OVERRIDE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {qmm|dpc3|google|test} [--test] [--debug] [--warmup N] [--sim N]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {qmm|dpc3|google|test} [--test] [--debug] [--warmup N] [--sim N]" >&2
  exit 2
fi

SHARED_TRACES=/home/users/shared/traces

case "$token" in
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
N=${#TRACES[@]}
if [ "$N" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2; exit 2
fi

if [ "$TEST" -eq 1 ]; then
  TASK_RANGE="1-$(( N < 5 ? N : 5 ))"
elif [ "$DEBUG" -eq 1 ]; then
  TASK_RANGE="1-1"
else
  TASK_RANGE="1-${N}"
fi

DATE=$(date +%Y%m%d_%H%M)
TEST_TAG=$( [ "$TEST" -eq 1 ] && echo "_test" || echo "" )
BASE_LABEL="${token}_cache_size_${DATE}${TEST_TAG}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"
source "${SCRIPT_DIR}/_manifest.sh"
write_manifest

# (exp_name, binary) — one entry per point; baseline uses champsim_lru
configs=(
  "baseline          champsim_lru"
  "llc_half          champsim_lru_llc_half"
  "llc_double        champsim_lru_llc_double"
  "l2c_half          champsim_lru_l2c_half"
  "l2c_double        champsim_lru_l2c_double"
  "stlb_half         champsim_lru_stlb_half"
  "stlb_double       champsim_lru_stlb_double"
  "dtlb_half         champsim_lru_dtlb_half"
  "dtlb_double       champsim_lru_dtlb_double"
  "itlb_half         champsim_lru_itlb_half"
  "itlb_double       champsim_lru_itlb_double"
)

# Validate all binaries exist before submitting anything
missing=0
for config in "${configs[@]}"; do
  read -r exp_name binary <<< "$config"
  if [ ! -x "${PROJECT_ROOT}/bin/${binary}" ]; then
    echo "  MISSING: bin/${binary}  (run ./scripts/build_cache_size_study.sh first)" >&2
    ((missing++)) || true
  fi
done
[ "$missing" -gt 0 ] && exit 2

echo "Submitting ${#configs[@]} configs × ${N} traces (tasks ${TASK_RANGE})"
echo "Warmup / Sim : ${WARMUP} / ${SIM}"
echo "Results base : results/${BASE_LABEL}/"
echo "Logs         : logs/${BASE_LABEL}/"
echo ""

for config in "${configs[@]}"; do
  read -r exp_name binary <<< "$config"
  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "cs_${exp_name:0:12}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",RUN_LABEL="$RUN_LABEL",BINARY="$binary",DPPRED=0,CBPRED=0,PCONF_THD=6,BCONF_THD=6,MID_THD=1,MID_KEY=0,MID_PROMOTE=0 \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  printf "  [jid=%-8s] %s  (bin/%s)\n" "$jid" "$exp_name" "$binary"
done

echo ""
echo "All configs submitted. Monitor with: qstat -u \$USER"
echo "Results will appear under: results/${BASE_LABEL}/"
echo ""
echo "Once complete, plot with:"
echo "  python3 scripts/analysis/plot_cache_size_study.py results/${BASE_LABEL} \\"
echo "      --out results/plots/cache_size_study/"
