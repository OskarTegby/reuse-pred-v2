#!/usr/bin/env bash
# sweep_pacipv_class.sh — coordinate-descent IPV search for one liveness class.
#
# Sweeps all 96×96 = 9,216 (demand, prefetch) IPV pairs for the given liveness
# class while holding the other two classes fixed.  Submits a single SGE job
# array with N_PAIRS × N_SEARCH_TRACES tasks.
#
# Usage:
#   ./sweep_pacipv_class.sh {dpc3|google|qmm|test} {doa|mostly_dead|mostly_alive} \
#       [--doa-d V] [--doa-p V] [--mostly-dead-d V] [--mostly-dead-p V] \
#       [--mostly-alive-d V] [--mostly-alive-p V] \
#       [--max-traces N] [--warmup N] [--sim N] [--debug]
#
# Fixed-class vectors default to the coded defaults in pacipv.cc.
# --max-traces limits the trace subset used for the search (default 8).
# Keep N_PAIRS (9216) × max-traces ≤ ~75000 to stay within SGE array limits.
#
# After all jobs finish, run find_best_pacipv.py to identify the winning pair.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── Argument parsing ──────────────────────────────────────────────────────────
token=""
CLASS=""
DEBUG=0
MAX_TRACES=8
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""
MID_KEY_STR=""   # set per-token below; overridable with --mid-key
MID_KEY_VAL=""

DOA_D="0,0,1,2,3";  DOA_P="0,0,0,2,3"
MD_D="0,0,0,2,3";   MD_P="0,0,0,2,3"
MA_D="0,1,1,0,3";   MA_P="0,1,0,0,3"

while [[ $# -gt 0 ]]; do
  case "$1" in
    dpc3|google|qmm|test)        token="${1,,}"; shift ;;
    doa|mostly_dead|mostly_alive) CLASS="$1";   shift ;;
    --doa-d)          DOA_D="$2";       shift 2 ;;
    --doa-p)          DOA_P="$2";       shift 2 ;;
    --mostly-dead-d)  MD_D="$2";        shift 2 ;;
    --mostly-dead-p)  MD_P="$2";        shift 2 ;;
    --mostly-alive-d) MA_D="$2";        shift 2 ;;
    --mostly-alive-p) MA_P="$2";        shift 2 ;;
    --max-traces)     MAX_TRACES="$2";  shift 2 ;;
    --debug)          DEBUG=1;          shift ;;
    --warmup)         WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)            SIM_OVERRIDE="$2";    shift 2 ;;
    --mid-key)
      case "$2" in
        addr) MID_KEY_STR="addr"; MID_KEY_VAL=0 ;;
        pc)   MID_KEY_STR="pc";   MID_KEY_VAL=1 ;;
        *) echo "Unknown --mid-key value: $2 (expected addr or pc)" >&2; exit 2 ;;
      esac
      shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$token" ] || [ -z "$CLASS" ]; then
  echo "Usage: $0 {dpc3|google|qmm|test} {doa|mostly_dead|mostly_alive} [options]" >&2
  exit 2
fi

SHARED_TRACES=/home/users/shared/traces

# ── Trace-set settings ────────────────────────────────────────────────────────
case "$token" in
  dpc3)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/dpc3_traces";      TRACE_EXT="champsimtrace.xz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="addr"; MID_KEY_VAL=0; } ;;
  google)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/Google_Traces_v2"; TRACE_EXT="champsim.gz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="pc";   MID_KEY_VAL=1; } ;;
  qmm)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM";   TRACE_EXT="champsimtrace.xz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="pc";   MID_KEY_VAL=1; } ;;
  test)
    WARMUP=25000000; SIM=50000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/TEST";  TRACE_EXT="champsimtrace.xz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="addr"; MID_KEY_VAL=0; } ;;
esac

[ -n "$WARMUP_OVERRIDE" ] && WARMUP="$WARMUP_OVERRIDE"
[ -n "$SIM_OVERRIDE" ]    && SIM="$SIM_OVERRIDE"

# ── Resolve search trace count ────────────────────────────────────────────────
mapfile -t ALL_TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N_TOTAL=${#ALL_TRACES[@]}
if [ "$N_TOTAL" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2; exit 2
fi
N_SEARCH=$(( MAX_TRACES < N_TOTAL ? MAX_TRACES : N_TOTAL ))
[ "$DEBUG" -eq 1 ] && N_SEARCH=1

# ── Map class to env var names and liveness ordering constraints ──────────────
# Constraint: doa[k] >= mostly_dead[k] >= mostly_alive[k] for all k.
# When sweeping mostly_dead, each candidate vector must be >= the fixed
# mostly_alive vector (element-wise).  When sweeping doa, it must be >=
# the fixed mostly_dead vector.  mostly_alive is unconstrained.
case "$CLASS" in
  doa)
    DEMAND_VAR="PACIPV_DOA_DEMAND";         PREFETCH_VAR="PACIPV_DOA_PREFETCH"
    MIN_D="$MD_D";  MIN_P="$MD_P" ;;
  mostly_dead)
    DEMAND_VAR="PACIPV_MOSTLY_DEAD_DEMAND"; PREFETCH_VAR="PACIPV_MOSTLY_DEAD_PREFETCH"
    MIN_D="$MA_D";  MIN_P="$MA_P" ;;
  mostly_alive)
    DEMAND_VAR="PACIPV_MOSTLY_ALIVE_DEMAND";PREFETCH_VAR="PACIPV_MOSTLY_ALIVE_PREFETCH"
    MIN_D="";       MIN_P="" ;;
esac

# ── Generate params file (all valid IPV pairs for this class) ─────────────────
BINARY="champsim_pacipv"
if [ ! -x "${PROJECT_ROOT}/bin/${BINARY}" ]; then
  echo "ERROR: binary not found: bin/${BINARY}" >&2
  echo "Run: ./build_all.sh --nopref pacipv" >&2; exit 2
fi

DATE=$(date +%Y%m%d_%H%M)
BASE_LABEL="${token}_pacipv_search_${CLASS}_${DATE}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
RESULTS_DIR="${PROJECT_ROOT}/results/${BASE_LABEL}"
mkdir -p "$LOG_DIR" "$RESULTS_DIR"

PARAMS_FILE="${RESULTS_DIR}/params.tsv"
MIN_D_ARG=(); [ -n "$MIN_D" ] && MIN_D_ARG=(--min-ipv "$MIN_D")
MIN_P_ARG=(); [ -n "$MIN_P" ] && MIN_P_ARG=(--min-ipv "$MIN_P")
python3 "${PROJECT_ROOT}/scripts/analysis/enumerate_ipvs.py" "${MIN_D_ARG[@]}" | \
  while read -r d; do
    python3 "${PROJECT_ROOT}/scripts/analysis/enumerate_ipvs.py" "${MIN_P_ARG[@]}" | \
      while read -r p; do printf '%s\t%s\n' "$d" "$p"; done
  done > "$PARAMS_FILE"

N_PAIRS=$(wc -l < "$PARAMS_FILE")
N_TASKS=$(( N_PAIRS * N_SEARCH ))

echo "Suite         : ${token}"
echo "Class         : ${CLASS}  (sweeping ${DEMAND_VAR} / ${PREFETCH_VAR})"
echo "Pairs         : ${N_PAIRS}  ×  search traces: ${N_SEARCH}  =  ${N_TASKS} tasks"
echo "Fixed vectors :"
echo "  DOA          demand=${DOA_D}  prefetch=${DOA_P}"
echo "  mostly_dead  demand=${MD_D}   prefetch=${MD_P}"
echo "  mostly_alive demand=${MA_D}   prefetch=${MA_P}"
echo "Results       : results/${BASE_LABEL}/"
echo ""

TASK_RANGE="1-${N_TASKS}"
[ "$DEBUG" -eq 1 ] && TASK_RANGE="1-1"

raw=$(qsub -t "$TASK_RANGE" \
           -N "pacipv_${CLASS:0:3}" \
           -o "${LOG_DIR}/" \
           -e "${LOG_DIR}/" \
           -wd "$PROJECT_ROOT" \
           -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_BASE="$BASE_LABEL",BINARY="$BINARY",\
PARAMS_FILE="$PARAMS_FILE",N_SEARCH_TRACES="$N_SEARCH",\
CLASS_DEMAND_VAR="$DEMAND_VAR",CLASS_PREFETCH_VAR="$PREFETCH_VAR",\
PACIPV_DOA_DEMAND="$DOA_D",PACIPV_DOA_PREFETCH="$DOA_P",\
PACIPV_MOSTLY_DEAD_DEMAND="$MD_D",PACIPV_MOSTLY_DEAD_PREFETCH="$MD_P",\
PACIPV_MOSTLY_ALIVE_DEMAND="$MA_D",PACIPV_MOSTLY_ALIVE_PREFETCH="$MA_P",\
MID_THD=1,MID_KEY="$MID_KEY_VAL",MID_PROMOTE=0 \
           "${PROJECT_ROOT}/scripts/submit/run_pacipv_search.sh")

jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
echo "Submitted [jid=${jid}]  ${N_TASKS} tasks"
echo ""
echo "When done, find the best pair with:"
echo "  python3 scripts/analysis/find_best_pacipv.py results/cluster/${BASE_LABEL}"
