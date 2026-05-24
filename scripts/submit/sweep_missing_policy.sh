#!/usr/bin/env bash
# sweep_missing_policy.sh — submit the policies missing from the LLC+STLB comparison.
#
# Adds to the combined_stlb_llc_comparison set:
#   srrip_live_both : champsim_srrip_live_both  (STLB=srrip_live, LLC=srrip_live)
#   ipv             : champsim_ipv              (LLC=IPV,          STLB=LRU)
#   ipv_live        : champsim_ipv_live         (LLC=ipv_live,     STLB=LRU)
#   stlb_ipv_live   : champsim_stlb_ipv_live    (STLB=ipv_live,    LLC=LRU)
#   ipv_live_both   : champsim_ipv_live_both    (STLB=ipv_live,    LLC=ipv_live)
#   srrip_both      : champsim_srrip_both       (STLB=srrip,       LLC=srrip)
#   stlb_ipv        : champsim_stlb_ipv         (STLB=IPV,         LLC=LRU)
#   ipv_both        : champsim_ipv_both         (STLB=IPV,         LLC=IPV)
#
# MID_THD defaults (used for srrip_live_both and ipv_live):
#   dpc3    → addr-keyed, thd=16  (matches best LLC thd from srrip_live_thd sweep)
#   google  → pc-keyed,   thd=8   (matches best LLC thd from srrip_live_thd sweep)
#   qmm     → pc-keyed,   thd=4   (matches best LLC thd from srrip_live_thd sweep)
#
# Usage:
#   ./sweep_missing_policy.sh {dpc3|google|qmm|test} [--mid-thd N] [--mid-key addr|pc] [--debug] [--warmup N] [--sim N]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

token=""
DEBUG=0
TEST=0
MID_THD=""
MID_KEY_STR=""
MID_KEY_VAL=""
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    dpc3|google|qmm|gms|test) token="${1,,}"; shift ;;
    --test)     TEST=1; shift ;;
    --debug)    DEBUG=1; shift ;;
    --warmup)   WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)      SIM_OVERRIDE="$2";    shift 2 ;;
    --mid-thd)  MID_THD="$2"; shift 2 ;;
    --mid-key)
      case "$2" in
        addr) MID_KEY_STR="addr"; MID_KEY_VAL=0 ;;
        pc)   MID_KEY_STR="pc";   MID_KEY_VAL=1 ;;
        *) echo "Unknown --mid-key: $2" >&2; exit 2 ;;
      esac
      shift 2 ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {dpc3|google|qmm|gms|test} [--mid-thd N] [--mid-key addr|pc] [--debug] [--warmup N] [--sim N]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {dpc3|google|qmm|gms|test} [--mid-thd N] [--mid-key addr|pc] [--debug] [--warmup N] [--sim N]" >&2
  exit 2
fi

SHARED_TRACES=/home/users/shared/traces

case "$token" in
  dpc3)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/dpc3_traces"; TRACE_EXT="champsimtrace.xz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="addr"; MID_KEY_VAL=0; }
    [ -z "$MID_THD" ]     && MID_THD=16 ;;
  google)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/Google_Traces_v2"; TRACE_EXT="champsim.gz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="pc"; MID_KEY_VAL=1; }
    [ -z "$MID_THD" ]     && MID_THD=8 ;;
  qmm)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM"; TRACE_EXT="champsimtrace.xz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="pc"; MID_KEY_VAL=1; }
    [ -z "$MID_THD" ]     && MID_THD=4 ;;
  gms)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/gms"; TRACE_EXT="gz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="addr"; MID_KEY_VAL=0; }
    [ -z "$MID_THD" ]     && MID_THD=8 ;;
  test)
    WARMUP=25000000; SIM=50000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/TEST"; TRACE_EXT="champsimtrace.xz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="addr"; MID_KEY_VAL=0; }
    [ -z "$MID_THD" ]     && MID_THD=4 ;;
esac

[ -n "$WARMUP_OVERRIDE" ] && WARMUP="$WARMUP_OVERRIDE"
[ -n "$SIM_OVERRIDE" ]    && SIM="$SIM_OVERRIDE"
[ "$TEST" -eq 1 ] && { WARMUP=25000000; SIM=50000000; }

for bin in champsim_srrip_live_both champsim_ipv champsim_ipv_live champsim_stlb_ipv_live champsim_ipv_live_both champsim_srrip_both champsim_stlb_ipv champsim_ipv_both; do
  if [ ! -x "${PROJECT_ROOT}/bin/${bin}" ]; then
    echo "ERROR: binary not found: bin/${bin}" >&2
    echo "Run: ./build_all.sh" >&2
    exit 2
  fi
done

mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N=${#TRACES[@]}
[ "$N" -eq 0 ] && { echo "ERROR: No traces in ${TRACE_DIR}" >&2; exit 2; }

if   [ "$TEST"  -eq 1 ]; then TASK_RANGE="1-$(( N < 5 ? N : 5 ))"
elif [ "$DEBUG" -eq 1 ]; then TASK_RANGE="1-1"
else                          TASK_RANGE="1-${N}"
fi

DATE=$(date +%Y%m%d_%H%M)
TEST_TAG=$( [ "$TEST" -eq 1 ] && echo "_test" || echo "" )
KEY_TAG=$( [ "$MID_KEY_STR" = "pc" ] && echo "_pc" || echo "" )
BASE_LABEL="${token}_missing_policy${KEY_TAG}_${DATE}${TEST_TAG}"

LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"
source "${SCRIPT_DIR}/_manifest.sh"
write_manifest

echo "Suite         : ${token}  (${N} traces, tasks ${TASK_RANGE})"
echo "mid_thd       : ${MID_THD}  mid_key=${MID_KEY_STR}"
echo "Results base  : results/${BASE_LABEL}/"
echo ""

submit_one() {
  local exp="$1"; local binary="$2"; local mid_thd="$3"
  local run_label="${BASE_LABEL}/${exp}"
  mkdir -p "${PROJECT_ROOT}/results/${run_label}"
  local raw
  raw=$(qsub -t "$TASK_RANGE" \
             -N "mp_${exp:0:10}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",RUN_LABEL="$run_label",BINARY="$binary",DPPRED=0,CBPRED=0,PCONF_THD=6,BCONF_THD=6,MID_THD="$mid_thd",MID_KEY="$MID_KEY_VAL",MID_PROMOTE=0 \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  local jid
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp}  (MID_THD=${mid_thd})"
}

submit_one "srrip_live_both"  "champsim_srrip_live_both"  "$MID_THD"
submit_one "ipv"              "champsim_ipv"               1
submit_one "ipv_live"         "champsim_ipv_live"          "$MID_THD"
submit_one "stlb_ipv_live"    "champsim_stlb_ipv_live"     "$MID_THD"
submit_one "ipv_live_both"    "champsim_ipv_live_both"     "$MID_THD"
submit_one "srrip_both"       "champsim_srrip_both"        1
submit_one "stlb_ipv"         "champsim_stlb_ipv"          1
submit_one "ipv_both"         "champsim_ipv_both"          1

echo ""
echo "Monitor with: qstat -u \$USER"
echo "Results under: results/${BASE_LABEL}/"
echo ""
echo "Once done, add to combined comparison with:"
echo "  ln -s \$(pwd)/results/${BASE_LABEL}/srrip_live_both  results/combined_stlb_llc_comparison/${token}/srrip_live_both"
echo "  ln -s \$(pwd)/results/${BASE_LABEL}/ipv               results/combined_stlb_llc_comparison/${token}/ipv"
echo "  ln -s \$(pwd)/results/${BASE_LABEL}/ipv_live          results/combined_stlb_llc_comparison/${token}/ipv_live"
echo "  ln -s \$(pwd)/results/${BASE_LABEL}/stlb_ipv_live     results/combined_stlb_llc_comparison/${token}/stlb_ipv_live"
echo "  ln -s \$(pwd)/results/${BASE_LABEL}/ipv_live_both     results/combined_stlb_llc_comparison/${token}/ipv_live_both"
echo "  ln -s \$(pwd)/results/${BASE_LABEL}/srrip_both        results/combined_stlb_llc_comparison/${token}/srrip_both"
echo "  ln -s \$(pwd)/results/${BASE_LABEL}/stlb_ipv          results/combined_stlb_llc_comparison/${token}/stlb_ipv"
echo "  ln -s \$(pwd)/results/${BASE_LABEL}/ipv_both          results/combined_stlb_llc_comparison/${token}/ipv_both"
