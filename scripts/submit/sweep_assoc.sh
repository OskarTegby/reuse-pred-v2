#!/usr/bin/env bash
# sweep_assoc.sh — associativity isolation study at a fixed table capacity.
#
# Fixes both history tables at N entries total (default N=256) and sweeps the
# set/way split independently for pHIST and bHIST:
#
#   phist sweep: ways ∈ {1, 2, 4, …, N}, sets = N/ways; BHIST fixed at FA (sets=1, ways=N)
#   bhist sweep: ways ∈ {1, 2, 4, …, N}, sets = N/ways; PHIST fixed at FA (sets=1, ways=N)
#
# There are log2(N)+1 associativity levels per table per policy, ranging from
# direct-mapped (ways=1, sets=N) to fully associative (ways=N, sets=1).
#
# Runs both LRU and LFU.  At FA (sets=1) there are no conflict misses, only
# capacity evictions; the policy still matters and fa_lru vs fa_lfu are distinct.
# Results answer: does conflict-miss rate fall as associativity increases, and
# does IPC converge toward the FA ceiling?
#
# References:
#   baseline  — no predictor, hashed tables (IPC floor)
#   hash_pred — predictor on, hashed tables (comparison baseline)
#   fa_lru    — both tables fully associative at N, LRU  (upper bound for this N)
#   fa_lfu    — both tables fully associative at N, LFU
#
# Total configs: 4 refs + 2 tables × (log2(N)+1) × 2 pols
#   N=256  → 4 + 2×9×2  = 40
#   N=1024 → 4 + 2×11×2 = 48
#   N=4096 → 4 + 2×13×2 = 56
#
# Usage: ./sweep_assoc.sh {qmm|dpc3|google|test} [--size N] [--debug] [--warmup N] [--sim N]
#   --size N  total entries per table (must be a power of 2; default 256)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

token=""
DEBUG=0
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""
TABLE_SIZE=256

while [[ $# -gt 0 ]]; do
  case "$1" in
    qmm|dpc3|google|test) token="${1,,}"; shift ;;
    --debug)   DEBUG=1; shift ;;
    --size)    TABLE_SIZE="$2"; shift 2 ;;
    --warmup)  WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)     SIM_OVERRIDE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {qmm|dpc3|google|test} [--size N] [--debug] [--warmup N] [--sim N]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {qmm|dpc3|google|test} [--size N] [--debug] [--warmup N] [--sim N]" >&2
  exit 2
fi

# Validate TABLE_SIZE is a power of two
if (( TABLE_SIZE <= 0 )) || (( TABLE_SIZE & (TABLE_SIZE - 1) )); then
  echo "ERROR: --size must be a power of 2 (got ${TABLE_SIZE})" >&2; exit 2
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
BASE_LABEL="${token}_assoc_N${TABLE_SIZE}_${DATE}${MODE_TAG}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# Config format: exp_name binary dppred cbpred pconf_thd bconf_thd phist_hash bhist_hash phist_sets phist_ways bhist_sets bhist_ways repl_pol
configs=()

# References
configs+=("baseline  champsim_lru     0 0 6 6 1 1 1 ${TABLE_SIZE} 1 ${TABLE_SIZE} lru")
configs+=("hash_pred champsim_lru_mid 1 1 6 6 1 1 1 ${TABLE_SIZE} 1 ${TABLE_SIZE} lru")
configs+=("fa_lru    champsim_lru_mid 1 1 6 6 0 0 1 ${TABLE_SIZE} 1 ${TABLE_SIZE} lru")
configs+=("fa_lfu    champsim_lru_mid 1 1 6 6 0 0 1 ${TABLE_SIZE} 1 ${TABLE_SIZE} lfu")

# pHIST associativity sweep: vary PHIST_SETS, hold BHIST at FA
sets=$TABLE_SIZE
while (( sets >= 1 )); do
  ways=$(( TABLE_SIZE / sets ))
  for pol in lru lfu; do
    name="phist_s${sets}_w${ways}_${pol}"
    configs+=("${name} champsim_lru_mid 1 1 6 6 0 0 ${sets} ${ways} 1 ${TABLE_SIZE} ${pol}")
  done
  (( sets /= 2 )) || true   # /= 2; stops after sets=1
done

# bHIST associativity sweep: vary BHIST_SETS, hold PHIST at FA
sets=$TABLE_SIZE
while (( sets >= 1 )); do
  ways=$(( TABLE_SIZE / sets ))
  for pol in lru lfu; do
    name="bhist_s${sets}_w${ways}_${pol}"
    configs+=("${name} champsim_lru_mid 1 1 6 6 0 0 1 ${TABLE_SIZE} ${sets} ${ways} ${pol}")
  done
  (( sets /= 2 )) || true
done

echo "Submitting ${#configs[@]} configurations × ${N_TRACES} traces (tasks ${TASK_RANGE})"
echo "Table size   : N=${TABLE_SIZE} ($(( TABLE_SIZE / 1 )) entries per table)"
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
