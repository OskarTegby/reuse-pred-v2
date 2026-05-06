#!/usr/bin/env bash
# sweep_policy.sh — submit per-policy experiments at default predictor thresholds.
#
# Runs 8 configurations covering baseline replacement policies (liveness study)
# and predictor-augmented variants, at fixed default thresholds (pconf=6, bconf=6).
# For a threshold sweep, use sweep_cs.sh instead.
#
# Usage: ./sweep_policy.sh {maz|qmm|dpc3|google|test} [--debug] [--warmup N] [--sim N] [--pref] [--paper-pref] [--mid-thd N] [--mid-key addr|pc]
#
# --pref        Also submit the 8 prefetch variants (L1I=next_line_instr, L1D=ip_stride, L2C=spp_dev).
#               Requires champsim_{policy}_pref binaries built with ./build_all.sh --pref.
# --paper-pref  Also submit the 8 paper-prefetch variants (L1I=epi_instr, L1D=berti, L2C=next_line).
#               Matches the PACIPV ISCA'25 prefetcher configuration for apples-to-apples comparison.
#               Requires champsim_{policy}_paper_pref binaries built with ./build_all.sh --paper-pref.
#
# Configurations submitted (default, 8 configs):
#   lru            – champsim_lru,     DPPRED=0, CBPRED=0  (vanilla LRU + liveness stats)
#   srrip          – champsim_srrip,   DPPRED=0, CBPRED=0
#   drrip          – champsim_drrip,   DPPRED=0, CBPRED=0
#   lru_mid        – champsim_lru_mid, DPPRED=0, CBPRED=0  (liveness baseline; = LRU)
#   lru_dp_only    – champsim_lru,     DPPRED=1, CBPRED=0  (dpPred/STLB-bypass only, no LLC bypass)
#   lru_pred       – champsim_lru,     DPPRED=1, CBPRED=1  (bypass predictor on plain LRU)
#   lru_mid_pred   – champsim_lru_mid, DPPRED=1, CBPRED=1  (full system: lru_mid + predictor)
#   srrip_pred     – champsim_srrip,   DPPRED=1, CBPRED=1
#   drrip_pred     – champsim_drrip,   DPPRED=1, CBPRED=1
# With --pref, 8 additional configs (same policies, _pref binaries):
#   lru_pref       – champsim_lru_pref,     DPPRED=0, CBPRED=0
#   srrip_pref     – champsim_srrip_pref,   DPPRED=0, CBPRED=0
#   drrip_pref     – champsim_drrip_pref,   DPPRED=0, CBPRED=0
#   lru_mid_pref   – champsim_lru_mid_pref, DPPRED=0, CBPRED=0
#   lru_pred_pref        – champsim_lru_pref,     DPPRED=1, CBPRED=1
#   lru_mid_pred_pref    – champsim_lru_mid_pref, DPPRED=1, CBPRED=1
#   srrip_pred_pref      – champsim_srrip_pref,   DPPRED=1, CBPRED=1
#   drrip_pred_pref      – champsim_drrip_pref,   DPPRED=1, CBPRED=1
# With --paper-pref, 8 additional configs (same policies, _paper_pref binaries):
#   lru_paper_pref       – champsim_lru_paper_pref,     DPPRED=0, CBPRED=0
#   srrip_paper_pref     – champsim_srrip_paper_pref,   DPPRED=0, CBPRED=0
#   drrip_paper_pref     – champsim_drrip_paper_pref,   DPPRED=0, CBPRED=0
#   lru_mid_paper_pref   – champsim_lru_mid_paper_pref, DPPRED=0, CBPRED=0
#   lru_pred_paper_pref      – champsim_lru_paper_pref,     DPPRED=1, CBPRED=1
#   lru_mid_pred_paper_pref  – champsim_lru_mid_paper_pref, DPPRED=1, CBPRED=1
#   srrip_pred_paper_pref    – champsim_srrip_paper_pref,   DPPRED=1, CBPRED=1
#   drrip_pred_paper_pref    – champsim_drrip_paper_pref,   DPPRED=1, CBPRED=1
# Total: 8, 16, or 24 configs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── Argument parsing ──────────────────────────────────────────────────────────
token=""
DEBUG=0
TEST=0
WITH_BASE=1          # include the 8 no-prefetch configs (disable with --no-base)
WITH_PREF=0
WITH_PAPER_PREF=0
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""
MID_THD=1
MID_KEY_STR="addr"
MID_KEY_VAL=0
MID_PROMOTE_VAL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    maz|mazumdar|qmm|dpc3|google|test) token="${1,,}"; shift ;;
    --test)         TEST=1; shift ;;
    --debug)        DEBUG=1; shift ;;
    --no-base)      WITH_BASE=0; shift ;;
    --pref)         WITH_PREF=1; shift ;;
    --paper-pref)   WITH_PAPER_PREF=1; shift ;;
    --warmup)       WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)          SIM_OVERRIDE="$2"; shift 2 ;;
    --mid-thd)      MID_THD="$2"; shift 2 ;;
    --mid-promote)  MID_PROMOTE_VAL=1; shift ;;
    --mid-key)
      case "$2" in
        addr) MID_KEY_STR="addr"; MID_KEY_VAL=0 ;;
        pc)   MID_KEY_STR="pc";   MID_KEY_VAL=1 ;;
        *) echo "Unknown --mid-key value: $2 (expected addr or pc)" >&2; exit 2 ;;
      esac
      shift 2 ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {maz|qmm|dpc3|google|test} [--test] [--debug] [--no-base] [--pref] [--paper-pref] [--warmup N] [--sim N] [--mid-thd N] [--mid-key addr|pc] [--mid-promote]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {maz|qmm|dpc3|google|test} [--test] [--debug] [--no-base] [--pref] [--paper-pref] [--warmup N] [--sim N] [--mid-thd N] [--mid-key addr|pc] [--mid-promote]" >&2
  exit 2
fi

SHARED_TRACES=/home/users/shared/traces

# ── Trace-set settings ────────────────────────────────────────────────────────
case "$token" in
  maz|mazumdar)
    WARMUP=100000000
    SIM=100000000
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
    WARMUP=25000000
    SIM=50000000
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
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2
  exit 2
fi

if [ "$TEST" -eq 1 ]; then
  TASK_RANGE="1-$(( N < 5 ? N : 5 ))"
elif [ "$DEBUG" -eq 1 ]; then
  TASK_RANGE="1-1"
else
  TASK_RANGE="1-${N}"
fi

DATE=$(date +%Y%m%d_%H%M)
TEST_TAG=$( [ "$TEST" -eq 1 ] && echo "_test" || echo "" )
BASE_LABEL="${token}_pol_${DATE}${TEST_TAG}"

LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# ── Config list: (exp_name binary dppred cbpred pconf_thd bconf_thd) ──────────
# Default predictor thresholds: pconf=6, bconf=6
configs=()

# Base (no-prefetch) configs — skipped with --no-base
if [ "${WITH_BASE}" -eq 1 ]; then
  configs+=(
    "lru          champsim_lru      0 0 6 6"
    "srrip         champsim_srrip    0 0 6 6"
    "drrip         champsim_drrip    0 0 6 6"
    "lru_mid       champsim_lru_mid  0 0 6 6"
    "lru_dp_only   champsim_lru      1 0 6 6"
    "lru_pred      champsim_lru      1 1 6 6"
    "lru_mid_pred  champsim_lru_mid  1 1 6 6"
    "srrip_pred    champsim_srrip    1 1 6 6"
    "drrip_pred    champsim_drrip    1 1 6 6"
  )
fi

# Append prefetch variants when --pref is given.
if [ "${WITH_PREF}" -eq 1 ]; then
  configs+=(
    "lru_pref          champsim_lru_pref      0 0 6 6"
    "srrip_pref        champsim_srrip_pref    0 0 6 6"
    "drrip_pref        champsim_drrip_pref    0 0 6 6"
    "lru_mid_pref      champsim_lru_mid_pref  0 0 6 6"
    "lru_pred_pref     champsim_lru_pref      1 1 6 6"
    "lru_mid_pred_pref champsim_lru_mid_pref  1 1 6 6"
    "srrip_pred_pref   champsim_srrip_pref    1 1 6 6"
    "drrip_pred_pref   champsim_drrip_pref    1 1 6 6"
  )
fi

# Append paper-prefetch variants when --paper-pref is given (EPI + Berti + next_line).
if [ "${WITH_PAPER_PREF}" -eq 1 ]; then
  configs+=(
    "lru_paper_pref          champsim_lru_paper_pref      0 0 6 6"
    "srrip_paper_pref        champsim_srrip_paper_pref    0 0 6 6"
    "drrip_paper_pref        champsim_drrip_paper_pref    0 0 6 6"
    "lru_mid_paper_pref      champsim_lru_mid_paper_pref  0 0 6 6"
    "lru_pred_paper_pref     champsim_lru_paper_pref      1 1 6 6"
    "lru_mid_pred_paper_pref champsim_lru_mid_paper_pref  1 1 6 6"
    "srrip_pred_paper_pref   champsim_srrip_paper_pref    1 1 6 6"
    "drrip_pred_paper_pref   champsim_drrip_paper_pref    1 1 6 6"
  )
fi

echo "Submitting ${#configs[@]} configurations × ${N} traces (tasks ${TASK_RANGE})"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "mid_thd / key : ${MID_THD} / ${MID_KEY_STR}  promote_on_hit: $([ "${MID_PROMOTE_VAL}" -eq 1 ] && echo yes || echo no)"
echo "Results base  : results/${BASE_LABEL}/"
echo "Logs          : logs/${BASE_LABEL}/"
echo ""

# ── Submit all configs ────────────────────────────────────────────────────────
for config in "${configs[@]}"; do
  read -r exp_name binary dppred cbpred pconf_thd bconf_thd <<< "$config"

  # Verify binary exists before submitting
  if [ ! -x "${PROJECT_ROOT}/bin/${binary}" ]; then
    echo "  ERROR: binary not found: bin/${binary}" >&2
    echo "  Run ./build_all.sh first." >&2
    exit 2
  fi

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "pol_${exp_name}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",RUN_LABEL="$RUN_LABEL",BINARY="$binary",DPPRED="$dppred",CBPRED="$cbpred",PCONF_THD="$pconf_thd",BCONF_THD="$bconf_thd",MID_THD="$MID_THD",MID_KEY="$MID_KEY_VAL",MID_PROMOTE="$MID_PROMOTE_VAL" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}  (${binary})"
done

echo ""
echo "All configs submitted. Monitor with: qstat -u \$USER"
echo "Results will appear under: results/${BASE_LABEL}/"
