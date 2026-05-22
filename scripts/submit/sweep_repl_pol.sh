#!/usr/bin/env bash
# sweep_repl_pol.sh — compare LRU vs LFU replacement policies for the history tables.
#
# All runs use champsim_lru at default history-table sizes (pHIST=1024, bHIST=4096).
# The replacement policy is only meaningful in full-key mode (PHIST_HASH=0, BHIST_HASH=0);
# the hash_pred reference uses the default hashed mode to match the paper baseline.
#
# Configs:
#   lru_baseline — no predictor, hashed tables    (IPC floor)
#   hash_pred    — dpPred + cbPred, hashed tables  (paper baseline)
#   lru_pred     — dpPred + cbPred, full-key + LRU
#   lfu_pred     — dpPred + cbPred, full-key + LFU
#
# Usage: ./sweep_repl_pol.sh {maz|qmm|dpc3|google|gap|ligra|gms|ml|test}
#                            [--test] [--debug] [--warmup N] [--sim N]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

BINARY="champsim_lru"

token=""
DEBUG=0
TEST=0
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    maz|mazumdar|qmm|dpc3|google|gap|ligra|gms|ml|test) token="${1,,}"; shift ;;
    --test)   TEST=1; shift ;;
    --debug)  DEBUG=1; shift ;;
    --warmup) WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)    SIM_OVERRIDE="$2";    shift 2 ;;
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
    TRACE_DIR="${PROJECT_ROOT}/trace-files/MAZUMDAR"; TRACE_EXT="champsimtrace.xz" ;;
  qmm)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM";      TRACE_EXT="champsimtrace.xz" ;;
  dpc3)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/dpc3_traces";         TRACE_EXT="champsimtrace.xz" ;;
  google)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/Google_Traces_v2";    TRACE_EXT="champsim.gz" ;;
  gap)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/gap";      TRACE_EXT="trace.gz" ;;
  ligra)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/ligra";    TRACE_EXT="champsimtrace.xz" ;;
  gms)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/gms";      TRACE_EXT="gz" ;;
  ml)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/ml";       TRACE_EXT="champsimtrace.gz" ;;
  test)
    WARMUP=25000000; SIM=50000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/TEST";     TRACE_EXT="champsimtrace.xz" ;;
esac

[ -n "$WARMUP_OVERRIDE" ] && WARMUP="$WARMUP_OVERRIDE"
[ -n "$SIM_OVERRIDE" ]    && SIM="$SIM_OVERRIDE"
[ "$TEST" -eq 1 ] && { WARMUP=25000000; SIM=50000000; }

if [ ! -x "${PROJECT_ROOT}/bin/${BINARY}" ]; then
  echo "ERROR: binary not found: bin/${BINARY}" >&2
  exit 2
fi

mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N=${#TRACES[@]}
[ "$N" -eq 0 ] && { echo "ERROR: no traces in ${TRACE_DIR}" >&2; exit 2; }

if   [ "$TEST"  -eq 1 ]; then TASK_RANGE="1-$(( N < 5 ? N : 5 ))"
elif [ "$DEBUG" -eq 1 ]; then TASK_RANGE="1-1"
else                          TASK_RANGE="1-${N}"
fi

DATE=$(date +%Y%m%d_%H%M)
TEST_TAG=$( [ "$TEST" -eq 1 ] && echo "_test" || echo "" )
BASE_LABEL="${token}_repl_pol_${DATE}${TEST_TAG}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"
source "${SCRIPT_DIR}/_manifest.sh"
write_manifest

# Config format:
#   exp_name  dppred cbpred  phist_hash bhist_hash  phist_ways bhist_ways  repl_pol
#
# phist_sets and bhist_sets are always 1 (fully associative).
# Hashed configs (phist_hash=1, bhist_hash=1) ignore repl_pol and use
# phist_ways/bhist_ways as the hash-table width — set to defaults (1024/4096).
# All configs use the default bypass predictor (CBPRED_IDX=addr, PFQ on).
configs=(
  "lru_baseline  0 0   1 1   1024 4096  lru"
  "hash_pred     1 1   1 1   1024 4096  lru"
  "lru_pred      1 1   0 0   1024 4096  lru"
  "lfu_pred      1 1   0 0   1024 4096  lfu"
)

echo "Submitting ${#configs[@]} configs × ${N} traces (${TASK_RANGE})"
echo "Suite   : ${token}"
echo "Binary  : ${BINARY}"
echo "Warmup  : ${WARMUP}  Sim: ${SIM}"
echo "Results : results/${BASE_LABEL}/"
echo "Logs    : logs/${BASE_LABEL}/"
echo ""

for cfg in "${configs[@]}"; do
  read -r exp_name dppred cbpred \
           phist_hash bhist_hash phist_ways bhist_ways \
           repl_pol <<< "$cfg"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "rp_${exp_name:0:10}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",\
DPPRED="$dppred",CBPRED="$cbpred",PCONF_THD=6,BCONF_THD=6,\
MID_THD=1,MID_KEY=0,MID_PROMOTE=0,\
PHIST_HASH="$phist_hash",BHIST_HASH="$bhist_hash",\
PHIST_SETS=1,PHIST_WAYS="$phist_ways",BHIST_SETS=1,BHIST_WAYS="$bhist_ways",\
REPL_POL="$repl_pol",\
PFQ_CAP=8,ST_SIZE=2 \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  mode=$( [ "$phist_hash" -eq 1 ] && echo "hashed" || echo "full-key/${repl_pol}" )
  printf "  [jid=%-8s] %-20s  %s\n" "$jid" "$exp_name" "$mode"
done

echo ""
echo "Monitor : qstat -u \$USER"
echo "Results : results/${BASE_LABEL}/"
