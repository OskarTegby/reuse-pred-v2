#!/usr/bin/env bash
# sweep_hist_size.sh — history-table size and associativity study.
#
# Sweeps the joint capacity of phist and bhist (both set to the same N = sets×ways)
# from 64 to 16384 entries (2^6 to 2^14), at every power-of-2 associativity from
# direct-mapped (ways=1) to fully associative (sets=1).  Runs both LRU and LFU
# replacement policies.  All configs use full-key mode (PHIST_HASH=0, BHIST_HASH=0).
#
# References submitted alongside the sweep:
#   baseline  — no predictor, hashed tables (IPC floor)
#   hash_pred — predictor on, hashed tables (comparison baseline for full-key mode)
#   inf       — full-key, fully associative, 2^20 ways (no evictions; policy irrelevant)
#
# Total configs: 3 references + 2 × Σ(k+1, k=6..14) = 3 + 2×99 = 201
#
# Usage: ./sweep_hist_size.sh {qmm|dpc3|google|test} [--debug] [--warmup N] [--sim N]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

token=""
DEBUG=0
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    qmm|dpc3|google|test) token="${1,,}"; shift ;;
    --debug)   DEBUG=1; shift ;;
    --warmup)  WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)     SIM_OVERRIDE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {qmm|dpc3|google|test} [--debug] [--warmup N] [--sim N]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {qmm|dpc3|google|test} [--debug] [--warmup N] [--sim N]" >&2
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
BASE_LABEL="${token}_hist_size_${DATE}${MODE_TAG}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# Config format: exp_name binary dppred cbpred pconf_thd bconf_thd phist_hash bhist_hash phist_sets phist_ways bhist_sets bhist_ways repl_pol
# PFQ_CAP and ST_SIZE are kept at their defaults (8 and 2) throughout this study.
configs=()

# References
configs+=("baseline  champsim_lru     0 0 6 6 1 1 1  64      1  64      lru")
configs+=("hash_pred champsim_lru_mid 1 1 6 6 1 1 1  64      1  64      lru")
configs+=("inf       champsim_lru_mid 1 1 6 6 0 0 1  1048576 1  1048576 lru")

# Sweep: N = 2^log_n, ways = 2^log_ways, sets = N/ways
for log_n in 6 7 8 9 10 11 12 13 14; do
  N=$((1 << log_n))
  for log_ways in $(seq 0 "$log_n"); do
    ways=$((1 << log_ways))
    sets=$((N / ways))
    for pol in lru lfu; do
      name="${pol}_N${N}_s${sets}_w${ways}"
      configs+=("${name} champsim_lru_mid 1 1 6 6 0 0 ${sets} ${ways} ${sets} ${ways} ${pol}")
    done
  done
done

echo "Submitting ${#configs[@]} configurations × ${N_TRACES} traces (tasks ${TASK_RANGE})"
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
             -N "hs_${exp_name:0:12}" \
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
