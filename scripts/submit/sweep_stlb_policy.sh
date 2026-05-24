#!/usr/bin/env bash
# sweep_stlb_policy.sh — compare STLB replacement policies (LLC fixed to LRU).
#
# Submits three configurations for each trace in the chosen suite:
#   lru           : champsim_lru             (STLB=LRU,          LLC=LRU) — baseline
#   stlb_srrip    : champsim_stlb_srrip      (STLB=SRRIP,        LLC=LRU)
#   stlb_srrip_live : champsim_stlb_srrip_live (STLB=srrip_live, LLC=LRU)
#
# For the threshold-sensitive policy (srrip_live), mid_thd is set via --mid-thd
# (default 8).  History indexing is controlled by --mid-key addr|pc|0|1 (default addr).
#
# Requires binaries built on the cluster with:
#   ./build_all.sh --nopref stlb_srrip stlb_srrip_live
#
# Usage:
#   ./sweep_stlb_policy.sh {dpc3|google|qmm|test} [--mid-thd N] [--mid-key addr|pc|0|1] [--debug] [--warmup N] [--sim N]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── Argument parsing ──────────────────────────────────────────────────────────
token=""
DEBUG=0
TEST=0
MID_THD=8
MID_KEY=0
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    dpc3|google|qmm|gap|gms|ligra|ml|maz|mazumdar|test) token="${1,,}"; shift ;;
    --test)    TEST=1; shift ;;
    --debug)   DEBUG=1; shift ;;
    --mid-thd) MID_THD="$2"; shift 2 ;;
    --mid-key)
      case "$2" in
        addr|0) MID_KEY=0 ;;
        pc|1)   MID_KEY=1 ;;
        *) echo "Unknown --mid-key value: $2 (expected addr|0 or pc|1)" >&2; exit 2 ;;
      esac
      shift 2 ;;
    --warmup)  WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)     SIM_OVERRIDE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {dpc3|google|qmm|gap|gms|ligra|ml|maz|test} [--mid-thd N] [--mid-key addr|pc|0|1] [--test] [--debug] [--warmup N] [--sim N]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {dpc3|google|qmm|gap|gms|ligra|ml|maz|test} [--mid-thd N] [--mid-key addr|pc|0|1] [--test] [--debug] [--warmup N] [--sim N]" >&2
  exit 2
fi

SHARED_TRACES=/home/users/shared/traces

# ── Trace-set settings ────────────────────────────────────────────────────────
case "$token" in
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
  qmm)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM"
    TRACE_EXT="champsimtrace.xz"
    ;;
  gap)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/gap"
    TRACE_EXT="trace.gz"
    ;;
  gms)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/gms"
    TRACE_EXT="gz"
    ;;
  ligra)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/ligra"
    TRACE_EXT="champsimtrace.xz"
    ;;
  ml)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/ml"
    TRACE_EXT="champsimtrace.gz"
    ;;
  maz|mazumdar)
    WARMUP=100000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/MAZUMDAR"
    TRACE_EXT="champsimtrace.xz"
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

# ── Resolve trace list ────────────────────────────────────────────────────────
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

# ── Verify required binaries ──────────────────────────────────────────────────
for bin in champsim_lru champsim_stlb_srrip champsim_stlb_srrip_live; do
  if [ ! -x "${PROJECT_ROOT}/bin/${bin}" ]; then
    echo "ERROR: binary not found: bin/${bin}" >&2
    echo "Run: ./build_all.sh --nopref stlb_srrip stlb_srrip_live" >&2
    exit 2
  fi
done

DATE=$(date +%Y%m%d_%H%M)
TEST_TAG=$( [ "$TEST" -eq 1 ] && echo "_test" || echo "" )
KEY_TAG=$( [ "$MID_KEY" -eq 1 ] && echo "_pc" || echo "" )
BASE_LABEL="${token}_stlb_policy${KEY_TAG}_${DATE}${TEST_TAG}"

LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"
source "${SCRIPT_DIR}/_manifest.sh"
write_manifest

echo "Suite         : ${token}  (${N} traces, tasks ${TASK_RANGE})"
echo "mid_thd       : ${MID_THD}  mid_key=${MID_KEY}"
echo "Results base  : results/${BASE_LABEL}/"
echo "Logs          : logs/${BASE_LABEL}/"
echo ""

submit_one() {
  local exp="$1"; local binary="$2"; shift 2
  local extra_vars="$*"
  local run_label="${BASE_LABEL}/${exp}"
  mkdir -p "${PROJECT_ROOT}/results/${run_label}"
  local raw
  raw=$(qsub -t "$TASK_RANGE" \
             -N "sp_${exp:0:10}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",RUN_LABEL="$run_label",BINARY="$binary",DPPRED=0,CBPRED=0,${extra_vars} \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  local jid
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp}"
}

submit_one "lru"             "champsim_lru"             "PCONF_THD=6,BCONF_THD=6,MID_THD=1,MID_KEY=${MID_KEY},MID_PROMOTE=0"
submit_one "stlb_srrip"     "champsim_stlb_srrip"     "PCONF_THD=6,BCONF_THD=6,MID_THD=1,MID_KEY=${MID_KEY},MID_PROMOTE=0"
submit_one "stlb_srrip_live" "champsim_stlb_srrip_live" "PCONF_THD=6,BCONF_THD=6,MID_THD=${MID_THD},MID_KEY=${MID_KEY},MID_PROMOTE=0"

echo ""
echo "All configs submitted. Monitor with: qstat -u \$USER"
echo "Results will appear under: results/${BASE_LABEL}/"
