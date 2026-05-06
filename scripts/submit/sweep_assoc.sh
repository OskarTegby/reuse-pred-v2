#!/usr/bin/env bash
# sweep_assoc.sh — associativity isolation study at the target table capacities.
#
# Fixes pHIST at 1024 entries and bHIST at 4096 entries and sweeps all
# power-of-2 associativity levels independently for each table:
#
#   pHIST sweep (BHIST held at FA, 4096 ways):
#     ways: 1, 2, 4, … 1024 (FA)  — log2(1024)+1 = 11 levels
#
#   bHIST sweep (PHIST held at FA, 1024 ways):
#     ways: 1, 2, 4, … 4096 (FA)  — log2(4096)+1 = 13 levels
#
# Runs both LRU and LFU for all three suites, all traces.
#
# References:
#   baseline  — no predictor, hashed tables (IPC floor)
#   hash_pred — predictor on, hashed tables (comparison baseline)
#   fa_lru    — both tables fully associative at target sizes, LRU
#   fa_lfu    — same with LFU
#
# Total configs: 4 refs + 11×2 (pHIST) + 13×2 (bHIST) = 52
# Total jobs: 52 × 183 traces ≈ 9,516
#
# Usage: ./sweep_assoc.sh {qmm|dpc3|google|test} [--debug] [--warmup N] [--sim N]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

PHIST_SIZE=1024
BHIST_SIZE=4096

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

mapfile -t ALL_TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N_TRACES=${#ALL_TRACES[@]}
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
BASE_LABEL="${token}_assoc_p${PHIST_SIZE}_b${BHIST_SIZE}_${DATE}${TEST_TAG}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# Config format: exp_name binary dppred cbpred pconf_thd bconf_thd phist_hash bhist_hash phist_sets phist_ways bhist_sets bhist_ways repl_pol
configs=()

# References (both tables at FA)
configs+=("baseline  champsim_lru     0 0 6 6 1 1 1 ${PHIST_SIZE} 1 ${BHIST_SIZE} lru")
configs+=("hash_pred champsim_lru 1 1 6 6 1 1 1 ${PHIST_SIZE} 1 ${BHIST_SIZE} lru")
configs+=("fa_lru    champsim_lru 1 1 6 6 0 0 1 ${PHIST_SIZE} 1 ${BHIST_SIZE} lru")
configs+=("fa_lfu    champsim_lru 1 1 6 6 0 0 1 ${PHIST_SIZE} 1 ${BHIST_SIZE} lfu")

# pHIST sweep: all power-of-2 levels, BHIST held at FA
sets=$PHIST_SIZE
while (( sets >= 1 )); do
  ways=$(( PHIST_SIZE / sets ))
  for pol in lru lfu; do
    configs+=("phist_s${sets}_w${ways}_${pol} champsim_lru 1 1 6 6 0 0 ${sets} ${ways} 1 ${BHIST_SIZE} ${pol}")
  done
  (( sets /= 2 )) || true
done

# bHIST sweep: all power-of-2 levels, PHIST held at FA
sets=$BHIST_SIZE
while (( sets >= 1 )); do
  ways=$(( BHIST_SIZE / sets ))
  for pol in lru lfu; do
    configs+=("bhist_s${sets}_w${ways}_${pol} champsim_lru 1 1 6 6 0 0 1 ${PHIST_SIZE} ${sets} ${ways} ${pol}")
  done
  (( sets /= 2 )) || true
done

echo "Submitting ${#configs[@]} configurations × ${N_TRACES} traces (tasks ${TASK_RANGE})"
echo "pHIST size   : ${PHIST_SIZE}  ($(( $(echo "l($PHIST_SIZE)/l(2)" | bc -l | cut -d. -f1) + 1 )) assoc levels)"
echo "bHIST size   : ${BHIST_SIZE}  ($(( $(echo "l($BHIST_SIZE)/l(2)" | bc -l | cut -d. -f1) + 1 )) assoc levels)"
echo "Warmup / Sim : ${WARMUP} / ${SIM}"
echo "Results base : results/${BASE_LABEL}/"
echo "Logs         : logs/${BASE_LABEL}/"
echo ""

for config in "${configs[@]}"; do
  read -r exp_name binary dppred cbpred pconf_thd bconf_thd \
           phist_hash bhist_hash phist_sets phist_ways bhist_sets bhist_ways repl_pol \
           <<< "$config"

  if [ ! -x "${PROJECT_ROOT}/bin/${binary}" ]; then
    echo "  ERROR: binary not found: bin/${binary}" >&2; exit 2
  fi

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "ac_${exp_name:0:12}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",RUN_LABEL="$RUN_LABEL",BINARY="$binary",DPPRED="$dppred",CBPRED="$cbpred",PCONF_THD="$pconf_thd",BCONF_THD="$bconf_thd",MID_THD=1,MID_KEY=0,MID_PROMOTE=0,PHIST_HASH="$phist_hash",BHIST_HASH="$bhist_hash",PHIST_SETS="$phist_sets",PHIST_WAYS="$phist_ways",BHIST_SETS="$bhist_sets",BHIST_WAYS="$bhist_ways",REPL_POL="$repl_pol",PFQ_CAP=8,ST_SIZE=2 \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  printf "  [jid=%-8s] %s\n" "$jid" "$exp_name"
done

echo ""
echo "All configs submitted. Monitor with: qstat -u \$USER"
echo "Results will appear under: results/${BASE_LABEL}/"
