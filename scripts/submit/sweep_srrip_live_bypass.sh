#!/usr/bin/env bash
# sweep_srrip_live_bypass.sh — SRRIP_live with weighted bypass (cbpred_weighted) sweep.
#
# Sweeps CBPRED_W_NORMAL × CBPRED_W_LOW × BCONF_THD to find the best combination.
# All configs use DPPRED=1 (STLB bypass) + CBPRED=1 + CBPRED_WEIGHTED=1.
# Baseline (unweighted cbpred) is included for reference.
#
# Counter update semantics when CBPRED_WEIGHTED=1:
#   DoA eviction after normal insertion:      bhist.doa += CBPRED_W_NORMAL
#   DoA eviction after pessimistic insertion: bhist.doa += CBPRED_W_LOW
#   mostly-dead eviction:                     bhist.doa-- (smooth), mostly_dead++
#   mostly-alive eviction:                    bhist.doa -= CBPRED_W_NORMAL (capped), mostly_dead--
#   bypass misprediction:                     bhist.doa -= CBPRED_W_MISPREDICT
#
# Usage:
#   ./sweep_srrip_live_bypass.sh {dpc3|google|qmm|test} \
#       [--mid-key addr|pc] [--debug] [--warmup N] [--sim N]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

token=""
DEBUG=0
TEST=0
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""
MID_KEY_STR=""
MID_KEY_VAL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    dpc3|google|qmm|test) token="${1,,}"; shift ;;
    --test)    TEST=1;  shift ;;
    --debug)   DEBUG=1; shift ;;
    --warmup)  WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)     SIM_OVERRIDE="$2";    shift 2 ;;
    --mid-key)
      case "$2" in
        addr) MID_KEY_STR="addr"; MID_KEY_VAL=0 ;;
        pc)   MID_KEY_STR="pc";   MID_KEY_VAL=1 ;;
        *) echo "Unknown --mid-key value: $2" >&2; exit 2 ;;
      esac
      shift 2 ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {dpc3|google|qmm|test} [--mid-key addr|pc] [--test] [--debug] [--warmup N] [--sim N]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {dpc3|google|qmm|test} [--mid-key addr|pc] [--test] [--debug] [--warmup N] [--sim N]" >&2
  exit 2
fi

SHARED_TRACES=/home/users/shared/traces

case "$token" in
  dpc3)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/dpc3_traces"; TRACE_EXT="champsimtrace.xz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="addr"; MID_KEY_VAL=0; } ;;
  google)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/Google_Traces_v2"; TRACE_EXT="champsim.gz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="pc"; MID_KEY_VAL=1; } ;;
  qmm)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM"; TRACE_EXT="champsimtrace.xz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="pc"; MID_KEY_VAL=1; } ;;
  test)
    WARMUP=25000000; SIM=50000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/TEST"; TRACE_EXT="champsimtrace.xz"
    [ -z "$MID_KEY_STR" ] && { MID_KEY_STR="addr"; MID_KEY_VAL=0; } ;;
esac

[ -n "$WARMUP_OVERRIDE" ] && WARMUP="$WARMUP_OVERRIDE"
[ -n "$SIM_OVERRIDE" ]    && SIM="$SIM_OVERRIDE"
[ "$TEST" -eq 1 ] && { WARMUP=25000000; SIM=50000000; }

BINARY="champsim_srrip_live"
if [ ! -x "${PROJECT_ROOT}/bin/${BINARY}" ]; then
  echo "ERROR: binary not found: bin/${BINARY}" >&2
  echo "Run ./build_all.sh srrip_live first." >&2
  exit 2
fi

mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N=${#TRACES[@]}
if [ "$N" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2; exit 2
fi

if   [ "$TEST"  -eq 1 ]; then TASK_RANGE="1-$(( N < 5 ? N : 5 ))"
elif [ "$DEBUG" -eq 1 ]; then TASK_RANGE="1-1"
else                          TASK_RANGE="1-${N}"
fi

DATE=$(date +%Y%m%d_%H%M)
TEST_TAG=$( [ "$TEST" -eq 1 ] && echo "_test" || echo "" )
BASE_LABEL="${token}_srrip_live_bypass_${DATE}${TEST_TAG}"

LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"
source "${SCRIPT_DIR}/_manifest.sh"
write_manifest

# Config format: exp_name  w_normal  w_low  bconf_thd  w_mispredict  weighted
configs=(
  # Unweighted baseline (original cbpred semantics, no CBPRED_WEIGHTED)
  "baseline       2  1  6  2  0"
  # Weighted: sweep W_NORMAL × W_LOW at default bconf_thd=6
  "wn2_wl1_b6     2  1  6  2  1"
  "wn3_wl1_b6     3  1  6  2  1"
  "wn2_wl1_b4     2  1  4  2  1"
  "wn3_wl1_b4     3  1  4  2  1"
  "wn2_wl1_b8     2  1  8  2  1"
  "wn3_wl1_b8     3  1  8  2  1"
  # Stronger misprediction penalty
  "wn2_wl1_b6_mp3 2  1  6  3  1"
  "wn3_wl1_b6_mp3 3  1  6  3  1"
)

echo "Submitting ${#configs[@]} configurations × ${N} traces (tasks ${TASK_RANGE})"
echo "Binary   : ${BINARY}"
echo "mid_key  : ${MID_KEY_STR} (MID_KEY=${MID_KEY_VAL})"
echo "Warmup/Sim: ${WARMUP} / ${SIM}"
echo "Results  : results/${BASE_LABEL}/"
echo ""

for config in "${configs[@]}"; do
  read -r exp_name w_normal w_low bconf_thd w_mispredict weighted <<< "$config"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "slb_${exp_name:0:9}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",DPPRED=1,CBPRED=1,PCONF_THD=6,BCONF_THD="$bconf_thd",MID_THD=1,MID_KEY="$MID_KEY_VAL",MID_PROMOTE=0,CBPRED_WEIGHTED="$weighted",CBPRED_W_NORMAL="$w_normal",CBPRED_W_LOW="$w_low",CBPRED_W_MISPREDICT="$w_mispredict" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  printf "  [jid=%-8s] %s\n" "$jid" "$exp_name"
done

echo ""
echo "Monitor with: qstat -u \$USER"
echo "Results under: results/${BASE_LABEL}/"
