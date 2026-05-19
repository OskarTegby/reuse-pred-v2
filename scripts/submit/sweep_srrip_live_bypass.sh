#!/usr/bin/env bash
# sweep_srrip_live_bypass.sh — SRRIP_live + weighted bypass predictor parameter sweep.
#
# Explores three orthogonal axes:
#
#   1. THRESHOLD SWEEP (equal pconf/bconf): which confidence level is best?
#      At bconf_thd=N with W_NORMAL=2, a normally-inserted block needs ceil((N+1)/2)
#      DoA evictions before bypass fires; a pessimistically-inserted block needs N+1.
#
#   2. BYPASS DEBT (adaptive gate): global mispredict penalty raises effective threshold.
#      BYPASS_DEBT_SCALE=S means effective_bconf = bconf_thd + bypass_debt / S.
#      BYPASS_DEBT_CAP (default bconf_thd) limits max threshold increase.
#
# Reference configs:
#   srrip_live_base  — srrip_live with no bypass at all (DPPRED=0, CBPRED=0)
#   unweighted_6_6   — original cbpred (CBPRED_WEIGHTED=0), equal evidence per DoA
#
# Usage:
#   ./sweep_srrip_live_bypass.sh {dpc3|google|qmm|test} [--debug] [--warmup N] [--sim N]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

token=""
DEBUG=0
TEST=0
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    dpc3|google|qmm|test) token="${1,,}"; shift ;;
    --test)    TEST=1;  shift ;;
    --debug)   DEBUG=1; shift ;;
    --warmup)  WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)     SIM_OVERRIDE="$2";    shift 2 ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {dpc3|google|qmm|test} [--test] [--debug] [--warmup N] [--sim N]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {dpc3|google|qmm|test} [--test] [--debug] [--warmup N] [--sim N]" >&2
  exit 2
fi

SHARED_TRACES=/home/users/shared/traces

case "$token" in
  dpc3)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/dpc3_traces"; TRACE_EXT="champsimtrace.xz" ;;
  google)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/Google_Traces_v2"; TRACE_EXT="champsim.gz" ;;
  qmm)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM"; TRACE_EXT="champsimtrace.xz" ;;
  test)
    WARMUP=25000000; SIM=50000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/TEST"; TRACE_EXT="champsimtrace.xz" ;;
esac

[ -n "$WARMUP_OVERRIDE" ] && WARMUP="$WARMUP_OVERRIDE"
[ -n "$SIM_OVERRIDE" ]    && SIM="$SIM_OVERRIDE"
[ "$TEST" -eq 1 ] && { WARMUP=25000000; SIM=50000000; }

BINARY="champsim_srrip_live"
if [ ! -x "${PROJECT_ROOT}/bin/${BINARY}" ]; then
  echo "ERROR: binary not found: bin/${BINARY}" >&2
  echo "Run ./build_all.sh --nopref srrip_live first." >&2
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

# Config format:
#   exp_name  dppred cbpred  pconf bconf  weighted  w_normal w_low w_mispredict  debt_scale
# Fixed: MID_THD=1 MID_KEY=0 MID_PROMOTE=0 PFQ_CAP=8 ST_SIZE=2 BHIST_HASH=1
configs=(
  # ── Reference configs ────────────────────────────────────────────────────────
  # No bypass: pure srrip_live liveness insertion, no predictor gating
  "srrip_live_base  0 0  0  0  0  2 1 2  0"
  # Unweighted cbpred: every DoA eviction counts +1 regardless of insertion class
  "unweighted_6_6   1 1  6  6  0  2 1 2  0"

  # ── Axis 1: equal threshold sweep (weighted, default weights) ─────────────
  # Determines: how much evidence is needed before bypassing?
  "thd_4_4          1 1  4  4  1  2 1 2  0"
  "thd_6_6          1 1  6  6  1  2 1 2  0"
  "thd_8_8          1 1  8  8  1  2 1 2  0"
  "thd_12_12        1 1 12 12  1  2 1 2  0"

  # ── Axis 3: bypass debt adaptive gate (pconf=bconf=6, default weights) ────
  # debt_scale=1: each misprediction adds W_MISPREDICT to debt; effective_bconf += debt
  # debt_scale=2: gentler — effective_bconf += debt/2
  "debt_scale1_6_6  1 1  6  6  1  2 1 2  1"
  "debt_scale2_6_6  1 1  6  6  1  2 1 2  2"
  # Debt with higher threshold: tighter static gate + adaptive penalty
  "debt_s1_thd8_8   1 1  8  8  1  2 1 2  1"
)

echo "Submitting ${#configs[@]} configurations × ${N} traces (tasks ${TASK_RANGE})"
echo "Binary   : ${BINARY}"
echo "Warmup/Sim: ${WARMUP} / ${SIM}"
echo "Results  : results/${BASE_LABEL}/"
echo ""

for config in "${configs[@]}"; do
  read -r exp_name dppred cbpred pconf bconf weighted w_normal w_low w_mispredict debt_scale <<< "$config"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  debt_cap=$bconf  # default debt cap = bconf_thd (allows threshold to double at most)

  raw=$(qsub -t "$TASK_RANGE" \
             -N "slb_${exp_name:0:10}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",\
DPPRED="$dppred",CBPRED="$cbpred",PCONF_THD="$pconf",BCONF_THD="$bconf",\
MID_THD=1,MID_KEY=0,MID_PROMOTE=0,\
CBPRED_WEIGHTED="$weighted",CBPRED_W_NORMAL="$w_normal",CBPRED_W_LOW="$w_low",CBPRED_W_MISPREDICT="$w_mispredict",\
BYPASS_DEBT_SCALE="$debt_scale",BYPASS_DEBT_CAP="$debt_cap" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  printf "  [jid=%-8s] %s\n" "$jid" "$exp_name"
done

echo ""
echo "Monitor with: qstat -u \$USER"
echo "Results under: results/${BASE_LABEL}/"
