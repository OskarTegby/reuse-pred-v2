#!/usr/bin/env bash
# sweep_assoc.sh — associativity isolation study at the target table capacities.
#
# Fixes pHIST at PHIST_SIZE entries (default 1024) and bHIST at BHIST_SIZE entries
# (default 4096), then sweeps the set/way split independently for each table:
#
#   phist sweep: ways ∈ {1,2,4,…,PHIST_SIZE}, sets=PHIST_SIZE/ways
#                BHIST held at FA (sets=1, ways=BHIST_SIZE)
#   bhist sweep: ways ∈ {1,2,4,…,BHIST_SIZE}, sets=BHIST_SIZE/ways
#                PHIST held at FA (sets=1, ways=PHIST_SIZE)
#
# Associativity levels:
#   pHIST (default 1024): log2(1024)+1 = 11  (1-way DM … 1024-way FA)
#   bHIST (default 4096): log2(4096)+1 = 13  (1-way DM … 4096-way FA)
#
# Runs both LRU and LFU.  At FA (sets=1) only capacity evictions occur;
# the replacement policy still distinguishes fa_lru from fa_lfu.
#
# References:
#   baseline  — no predictor, hashed tables (IPC floor)
#   hash_pred — predictor on, hashed tables (comparison baseline)
#   fa_lru    — both tables fully associative at their target sizes, LRU
#   fa_lfu    — same with LFU
#
# Total configs (defaults): 4 refs + 11×2 (phist) + 13×2 (bhist) = 52
#
# Usage: ./sweep_assoc.sh {qmm|dpc3|google|test} [--phist-size N] [--bhist-size N]
#                         [--debug] [--warmup N] [--sim N]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

token=""
DEBUG=0
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""
PHIST_SIZE=1024
BHIST_SIZE=4096

while [[ $# -gt 0 ]]; do
  case "$1" in
    qmm|dpc3|google|test) token="${1,,}"; shift ;;
    --debug)        DEBUG=1; shift ;;
    --phist-size)   PHIST_SIZE="$2"; shift 2 ;;
    --bhist-size)   BHIST_SIZE="$2"; shift 2 ;;
    --warmup)       WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)          SIM_OVERRIDE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {qmm|dpc3|google|test} [--phist-size N] [--bhist-size N] [--debug] [--warmup N] [--sim N]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {qmm|dpc3|google|test} [--phist-size N] [--bhist-size N] [--debug] [--warmup N] [--sim N]" >&2
  exit 2
fi

is_power_of_two() { (( $1 > 0 )) && (( ($1 & ($1 - 1)) == 0 )); }
is_power_of_two "$PHIST_SIZE" || { echo "ERROR: --phist-size must be a power of 2 (got ${PHIST_SIZE})" >&2; exit 2; }
is_power_of_two "$BHIST_SIZE" || { echo "ERROR: --bhist-size must be a power of 2 (got ${BHIST_SIZE})" >&2; exit 2; }

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
    WARMUP=1000000; SIM=5000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/TEST"
    TRACE_EXT="champsimtrace.xz"
    ;;
esac

[ -n "$WARMUP_OVERRIDE" ] && WARMUP="$WARMUP_OVERRIDE"
[ -n "$SIM_OVERRIDE" ]    && SIM="$SIM_OVERRIDE"

mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N_TRACES=${#TRACES[@]}
if [ "$N_TRACES" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2; exit 2
fi

if [ "$DEBUG" -eq 1 ]; then
  TASK_RANGE="1-1"; MODE_TAG="_debug"
else
  TASK_RANGE="1-${N_TRACES}"; MODE_TAG=""
fi

DATE=$(date +%Y%m%d_%H%M)
BASE_LABEL="${token}_assoc_p${PHIST_SIZE}_b${BHIST_SIZE}_${DATE}${MODE_TAG}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# Config format: exp_name binary dppred cbpred pconf_thd bconf_thd phist_hash bhist_hash phist_sets phist_ways bhist_sets bhist_ways repl_pol
configs=()

# References
configs+=("baseline  champsim_lru     0 0 6 6 1 1 1 ${PHIST_SIZE} 1 ${BHIST_SIZE} lru")
configs+=("hash_pred champsim_lru_mid 1 1 6 6 1 1 1 ${PHIST_SIZE} 1 ${BHIST_SIZE} lru")
configs+=("fa_lru    champsim_lru_mid 1 1 6 6 0 0 1 ${PHIST_SIZE} 1 ${BHIST_SIZE} lru")
configs+=("fa_lfu    champsim_lru_mid 1 1 6 6 0 0 1 ${PHIST_SIZE} 1 ${BHIST_SIZE} lfu")

# pHIST associativity sweep: vary PHIST sets/ways, hold BHIST at FA
sets=$PHIST_SIZE
while (( sets >= 1 )); do
  ways=$(( PHIST_SIZE / sets ))
  for pol in lru lfu; do
    name="phist_s${sets}_w${ways}_${pol}"
    configs+=("${name} champsim_lru_mid 1 1 6 6 0 0 ${sets} ${ways} 1 ${BHIST_SIZE} ${pol}")
  done
  (( sets /= 2 )) || true
done

# bHIST associativity sweep: vary BHIST sets/ways, hold PHIST at FA
sets=$BHIST_SIZE
while (( sets >= 1 )); do
  ways=$(( BHIST_SIZE / sets ))
  for pol in lru lfu; do
    name="bhist_s${sets}_w${ways}_${pol}"
    configs+=("${name} champsim_lru_mid 1 1 6 6 0 0 1 ${PHIST_SIZE} ${sets} ${ways} ${pol}")
  done
  (( sets /= 2 )) || true
done

log2() { local n=$1 r=0; while (( n > 1 )); do (( n /= 2, r++ )); done; echo $r; }
PHIST_LEVELS=$(( $(log2 "$PHIST_SIZE") + 1 ))
BHIST_LEVELS=$(( $(log2 "$BHIST_SIZE") + 1 ))

echo "Submitting ${#configs[@]} configurations × ${N_TRACES} traces (tasks ${TASK_RANGE})"
echo "pHIST size   : ${PHIST_SIZE} entries  (${PHIST_LEVELS} assoc levels)"
echo "bHIST size   : ${BHIST_SIZE} entries  (${BHIST_LEVELS} assoc levels)"
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
