#!/usr/bin/env bash
# sweep_mid.sh — sweep mid_thd (mid-insertion threshold) from 1 to MAX_N.
#
# Usage: ./sweep_mid.sh {maz|qmm|dpc3|google|test} [--max-n N] [--debug] [--warmup N] [--sim N] [--mid-key addr|pc] [--mid-promote] [--paper-pref]
#
# Submits one job array per mid_thd value plus a plain LRU baseline.
# Bypass predictors (dppred/cbpred) are always OFF — this study isolates
# the effect of mid-insertion threshold and key alone.  mid_thd controls
# how many consecutive DoA-or-mostly-dead evictions are required before
# lru_mid inserts a new block at the set midpoint rather than MRU.
#
# --mid-promote Promote mid-inserted blocks to MRU on hit (MID_PROMOTE=1).
# --paper-pref  Use EPI+Berti+next_line prefetcher binaries.
#               Requires binaries built with ./build_all.sh --paper-pref.
#
# Configurations submitted (default):
#   lru               : champsim_lru,     dppred=0, cbpred=0  (reference baseline)
#   mid_thd{1..MAX_N} : champsim_lru_mid, dppred=0, cbpred=0, mid_thd=1..MAX_N
# With --paper-pref:
#   lru               : champsim_lru_paper_pref
#   mid_thd{1..MAX_N} : champsim_lru_mid_paper_pref, mid_thd=1..MAX_N
# Total: 1 + MAX_N configs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── Argument parsing ──────────────────────────────────────────────────────────
token=""
DEBUG=0
MAX_N=5
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""
MID_KEY_STR="addr"   # addr (default) or pc
MID_KEY_VAL=0
MID_PROMOTE_VAL=0
PAPER_PREF=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    maz|mazumdar|qmm|dpc3|google|test) token="${1,,}"; shift ;;
    --max-n)      MAX_N="$2"; shift 2 ;;
    --debug)      DEBUG=1; shift ;;
    --warmup)     WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)        SIM_OVERRIDE="$2"; shift 2 ;;
    --paper-pref)  PAPER_PREF=1; shift ;;
    --mid-promote) MID_PROMOTE_VAL=1; shift ;;
    --mid-key)
      case "$2" in
        addr) MID_KEY_STR="addr"; MID_KEY_VAL=0 ;;
        pc)   MID_KEY_STR="pc";   MID_KEY_VAL=1 ;;
        *) echo "Unknown --mid-key value: $2 (expected addr or pc)" >&2; exit 2 ;;
      esac
      shift 2 ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {maz|qmm|dpc3|google|test} [--max-n N] [--mid-key addr|pc] [--mid-promote] [--paper-pref] [--debug] [--warmup N] [--sim N]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {maz|qmm|dpc3|google|test} [--max-n N] [--mid-key addr|pc] [--mid-promote] [--paper-pref] [--debug] [--warmup N] [--sim N]" >&2
  exit 2
fi

SHARED_TRACES=/home/users/shared/traces

# ── Trace-set settings ────────────────────────────────────────────────────────
case "$token" in
  maz|mazumdar)
    WARMUP=100000000
    SIM=1000000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/MAZUMDAR"
    TRACE_EXT="champsimtrace.xz"
    ;;
  qmm)
    WARMUP=50000000
    SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM"
    TRACE_EXT="champsimtrace.xz"
    ;;
  dpc3)
    WARMUP=50000000
    SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/dpc3_traces"
    TRACE_EXT="champsimtrace.xz"
    ;;
  google)
    WARMUP=50000000
    SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/Google_Traces_v2"
    TRACE_EXT="champsim.gz"
    ;;
  test)
    WARMUP=1000000
    SIM=5000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/TEST"
    TRACE_EXT="champsimtrace.xz"
    ;;
esac

[ -n "$WARMUP_OVERRIDE" ] && WARMUP="$WARMUP_OVERRIDE"
[ -n "$SIM_OVERRIDE" ]    && SIM="$SIM_OVERRIDE"

# ── Resolve trace list ────────────────────────────────────────────────────────
mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N=${#TRACES[@]}
if [ "$N" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2
  exit 2
fi

if [ "$DEBUG" -eq 1 ]; then
  TASK_RANGE="1-1"
  MODE_TAG="_debug"
else
  TASK_RANGE="1-${N}"
  MODE_TAG=""
fi

DATE=$(date +%Y%m%d_%H%M)
PREF_TAG=""
PROMOTE_TAG=""
BASELINE_BIN="champsim_lru"
SWEEP_BIN="champsim_lru_mid"
if [ "${PAPER_PREF}" -eq 1 ]; then
  PREF_TAG="_paper_pref"
  BASELINE_BIN="champsim_lru_paper_pref"
  SWEEP_BIN="champsim_lru_mid_paper_pref"
fi
[ "${MID_PROMOTE_VAL}" -eq 1 ] && PROMOTE_TAG="_promote"
BASE_LABEL="${token}_mid_${MID_KEY_STR}${PROMOTE_TAG}${PREF_TAG}_${DATE}${MODE_TAG}"

LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# ── Submit LRU baseline ───────────────────────────────────────────────────────
RUN_LABEL="${BASE_LABEL}/lru"
mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

echo "Submitting 1 + ${MAX_N} configurations × ${N} traces (tasks ${TASK_RANGE})"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "mid_thd sweep : 1..${MAX_N}  mid_key: ${MID_KEY_STR}  promote_on_hit: $([ "${MID_PROMOTE_VAL}" -eq 1 ] && echo yes || echo no)"
echo "Prefetchers   : $([ "${PAPER_PREF}" -eq 1 ] && echo "EPI+Berti+next_line (paper)" || echo "none")"
echo "Results base  : results/${BASE_LABEL}/"
echo "Logs          : logs/${BASE_LABEL}/"
echo ""

raw=$(qsub -t "$TASK_RANGE" \
           -N "cs_lru" \
           -o "${LOG_DIR}/" \
           -e "${LOG_DIR}/" \
           -wd "$PROJECT_ROOT" \
           -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",RUN_LABEL="$RUN_LABEL",BINARY="${BASELINE_BIN}",DPPRED=0,CBPRED=0,PCONF_THD=0,BCONF_THD=0,MID_THD=1,MID_PROMOTE=0 \
           "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
echo "  [jid=${jid}] lru  (baseline)"

# ── Submit mid_thd sweep ──────────────────────────────────────────────────────
for mthd in $(seq 1 "$MAX_N"); do
  RUN_LABEL="${BASE_LABEL}/mid_thd${mthd}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "cs_mid_thd" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",RUN_LABEL="$RUN_LABEL",BINARY="${SWEEP_BIN}",DPPRED=0,CBPRED=0,PCONF_THD=0,BCONF_THD=0,MID_THD="$mthd",MID_KEY="$MID_KEY_VAL",MID_PROMOTE="$MID_PROMOTE_VAL" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] mid_thd${mthd}"
done

echo ""
echo "All configs submitted. Monitor with: qstat -u \$USER"
echo "Results will appear under: results/${BASE_LABEL}/"
echo ""
echo "Plot with:"
echo "  python3 scripts/analysis/plot_mid_thd.py results/${BASE_LABEL}/ --baseline-dir results/${BASE_LABEL}/lru --max-n ${MAX_N}"
echo "  python3 scripts/analysis/plot_doa_correlation.py results/${BASE_LABEL}/ --baseline-dir results/${BASE_LABEL}/lru"
