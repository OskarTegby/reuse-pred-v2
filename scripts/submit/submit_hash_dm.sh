#!/usr/bin/env bash
# submit_hash_dm.sh — add direct-mapped hashed configs to an existing hist-size study.
#
# Submits hash_p{N}_b{N} configs (PHIST_HASH=1, BHIST_HASH=1, sets=N, ways=1)
# into an already-existing results directory alongside the FA jobs.
#
# Usage: ./submit_hash_dm.sh <base_label> {small|large} [--debug] [--warmup N] [--sim N]
#
#   base_label   Timestamped directory already in results/, e.g.
#                dpc3_hist_large_20260504_1200

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

base_label=""
range=""
DEBUG=0
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    small|large) range="${1,,}"; shift ;;
    --debug)     DEBUG=1; shift ;;
    --warmup)    WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)       SIM_OVERRIDE="$2"; shift 2 ;;
    -*)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 <base_label> {small|large} [--debug] [--warmup N] [--sim N]" >&2
      exit 2 ;;
    *)
      if [ -z "$base_label" ]; then base_label="$1"; shift
      else echo "Unexpected argument: $1" >&2; exit 2
      fi ;;
  esac
done

if [ -z "$base_label" ] || [ -z "$range" ]; then
  echo "Usage: $0 <base_label> {small|large} [--debug] [--warmup N] [--sim N]" >&2
  exit 2
fi

RESULTS_DIR="${PROJECT_ROOT}/results/${base_label}"
if [ ! -d "$RESULTS_DIR" ]; then
  echo "ERROR: results directory not found: ${RESULTS_DIR}" >&2; exit 2
fi

case "$base_label" in
  qmm_*)    token=qmm ;;
  dpc3_*)   token=dpc3 ;;
  google_*) token=google ;;
  test_*)   token=test ;;
  *)
    echo "ERROR: cannot infer suite from '${base_label}' (expected qmm_/dpc3_/google_/test_ prefix)" >&2
    exit 2 ;;
esac

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

case "$range" in
  small)
    phist_sizes=(64 128 256 512 1024)
    bhist_sizes=(64 128 256 512 1024 2048 4096)
    ;;
  large)
    phist_sizes=(1024 2048 4096 8192 16384)
    bhist_sizes=(4096 8192 16384)
    ;;
esac

mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N_TRACES=${#TRACES[@]}
if [ "$N_TRACES" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2; exit 2
fi

TASK_RANGE="1-${N_TRACES}"
[ "$DEBUG" -eq 1 ] && TASK_RANGE="1-1"

LOG_DIR="${PROJECT_ROOT}/logs/${base_label}"
mkdir -p "$LOG_DIR"

binary="champsim_lru"
if [ ! -x "${PROJECT_ROOT}/bin/${binary}" ]; then
  echo "ERROR: binary not found: bin/${binary}" >&2; exit 2
fi

echo "Adding hash-DM configs to: results/${base_label}/"
echo "Range        : ${range}"
echo "pHIST sizes  : ${phist_sizes[*]}"
echo "bHIST sizes  : ${bhist_sizes[*]}"
echo "Warmup / Sim : ${WARMUP} / ${SIM}"
echo "Traces       : ${N_TRACES} (tasks ${TASK_RANGE})"
echo ""

for phist_n in "${phist_sizes[@]}"; do
  for bhist_n in "${bhist_sizes[@]}"; do
    exp_name="hash_p${phist_n}_b${bhist_n}"
    RUN_LABEL="${base_label}/${exp_name}"
    mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

    raw=$(qsub -t "$TASK_RANGE" \
               -N "hd_p${phist_n}_b${bhist_n}" \
               -o "${LOG_DIR}/" \
               -e "${LOG_DIR}/" \
               -wd "$PROJECT_ROOT" \
               -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",RUN_LABEL="$RUN_LABEL",BINARY="$binary",DPPRED=1,CBPRED=1,PCONF_THD=6,BCONF_THD=6,MID_THD=1,MID_KEY=0,MID_PROMOTE=0,PHIST_HASH=1,BHIST_HASH=1,PHIST_SETS="$phist_n",PHIST_WAYS=1,BHIST_SETS="$bhist_n",BHIST_WAYS=1,REPL_POL=lru,PFQ_CAP=8,ST_SIZE=2 \
               "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
    jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
    printf "  [jid=%-8s] %s\n" "$jid" "$exp_name"
  done
done

echo ""
echo "All hash-DM configs submitted. Monitor with: qstat -u \$USER"
echo "Results will appear under: results/${base_label}/"
