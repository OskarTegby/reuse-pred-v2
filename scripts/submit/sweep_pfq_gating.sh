#!/usr/bin/env bash
# sweep_pfq_gating.sh — study PFQ-gate variants of cbPred.
#
# Eight configs (1MB LLC, LRU); baseline and optimal_bypass come from exp 001:
#   dppred_only_opt      — DPPRED=1, CBPRED=0, THD=(0,0)                  (dpPred alone reference)
#   dppred_only_default  — DPPRED=1, CBPRED=0, THD=(6,6)
#   cbpred_nopfq_opt     — DPPRED=1, CBPRED=1, THD=(0,0), CBPRED_NO_PFQ=1 (bhist alone)
#   cbpred_nopfq_default — DPPRED=1, CBPRED=1, THD=(6,6), CBPRED_NO_PFQ=1
#   cbpred_ema_opt       — DPPRED=1, CBPRED=1, THD=(0,0), PFQ_EMA=1       (EMA-adaptive, addr-indexed)
#   cbpred_ema_default   — DPPRED=1, CBPRED=1, THD=(6,6), PFQ_EMA=1
#   cbpred_pc_opt        — DPPRED=1, CBPRED=1, THD=(0,0), CBPRED_IDX=pc   (PC-indexed bHIST)
#   cbpred_pc_default    — DPPRED=1, CBPRED=1, THD=(6,6), CBPRED_IDX=pc
#
# EMA defaults: alpha=1/1024 (~0.001), gate turns OFF when hit rate < 10%.
# Override via PFQ_EMA_ALPHA=<f> and PFQ_EMA_THD=<pct> (percent, 0-100).
#
# Usage: ./sweep_pfq_gating.sh {gap|gms|ligra|ml|qmm|dpc3|google} [--debug]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SHARED_TRACES=/home/users/shared/traces
BINARY="champsim_verify"

token=""
DEBUG=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    gap|gms|ligra|ml|qmm|dpc3|google) token="${1,,}"; shift ;;
    --debug) DEBUG=1; shift ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: $0 {gap|gms|ligra|ml|qmm|dpc3|google} [--debug]" >&2
      exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {gap|gms|ligra|ml|qmm|dpc3|google} [--debug]" >&2
  exit 2
fi

WARMUP=50000000
SIM=100000000

case "$token" in
  qmm)
    TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM"
    TRACE_EXT="champsimtrace.xz"
    ;;
  dpc3)
    TRACE_DIR="${SHARED_TRACES}/dpc3_traces"
    TRACE_EXT="champsimtrace.xz"
    ;;
  google)
    TRACE_DIR="${SHARED_TRACES}/Google_Traces_v2"
    TRACE_EXT="champsim.gz"
    ;;
  gap)
    TRACE_DIR="${PROJECT_ROOT}/trace-files/gap"
    TRACE_EXT="trace.gz"
    ;;
  gms)
    TRACE_DIR="${PROJECT_ROOT}/trace-files/gms"
    TRACE_EXT="champsimtrace.gz"
    ;;
  ligra)
    TRACE_DIR="${PROJECT_ROOT}/trace-files/ligra"
    TRACE_EXT="champsimtrace.xz"
    ;;
  ml)
    TRACE_DIR="${PROJECT_ROOT}/trace-files/ml"
    TRACE_EXT="champsimtrace.gz"
    ;;
esac

mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N=${#TRACES[@]}
if [ "$N" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR} (ext: ${TRACE_EXT})" >&2
  exit 2
fi

TASK_RANGE="1-${N}"
DEBUG_TAG=""
if [ "$DEBUG" -eq 1 ]; then
  TASK_RANGE="1-1"
  DEBUG_TAG="_debug"
fi

if [ ! -x "${PROJECT_ROOT}/bin/${BINARY}" ]; then
  echo "ERROR: binary not found: bin/${BINARY}" >&2
  exit 2
fi

DATE=$(date +%Y%m%d_%H%M)
BASE_LABEL="${token}_pfq_gating_${DATE}${DEBUG_TAG}"

LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# Config format: exp_name  dppred cbpred no_pfq pfq_ema pconf bconf [cbpred_idx]
configs=(
  "dppred_only_opt      1 0 0 0 0 0"
  "dppred_only_default  1 0 0 0 6 6"
  "cbpred_nopfq_opt     1 1 1 0 0 0"
  "cbpred_nopfq_default 1 1 1 0 6 6"
  "cbpred_ema_opt       1 1 0 1 0 0"
  "cbpred_ema_default   1 1 0 1 6 6"
  "cbpred_pc_opt        1 1 0 0 0 0 pc"
  "cbpred_pc_default    1 1 0 0 6 6 pc"
)

echo "Suite         : ${token}"
echo "Traces        : ${N}  (tasks ${TASK_RANGE})"
echo "Configs       : ${#configs[@]}  (dppred_only_{opt,default}, cbpred_nopfq_{opt,default}, cbpred_ema_{opt,default})"
echo "Binary        : ${BINARY}"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "Results base  : results/${BASE_LABEL}/"
echo "Logs          : logs/${BASE_LABEL}/"
echo ""

for config in "${configs[@]}"; do
  read -r exp_name dppred cbpred no_pfq pfq_ema pconf bconf cbpred_idx <<< "$config"
  cbpred_idx="${cbpred_idx:-addr}"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "pfqg_${token}_${exp_name:0:10}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 \
             -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",\
DPPRED="$dppred",CBPRED="$cbpred",\
CBPRED_NO_PFQ="$no_pfq",PFQ_EMA="$pfq_ema",\
CBPRED_IDX="$cbpred_idx",\
PCONF_THD="$pconf",BCONF_THD="$bconf" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}  (NO_PFQ=${no_pfq}, EMA=${pfq_ema}, IDX=${cbpred_idx})"
done

echo ""
echo "All configs submitted. Monitor with: qstat -u \$USER"
echo "Results will appear under: results/${BASE_LABEL}/"

TOTAL_JOBS=$(( ${#configs[@]} * N ))
RECENT_REF=$(find "${PROJECT_ROOT}/results" -mindepth 2 -maxdepth 2 \
               -name "champsim.out" -printf "%T@ %h\n" 2>/dev/null \
             | sort -n | tail -1 | awk '{print $2}' | xargs dirname 2>/dev/null || true)
bash "${SCRIPT_DIR}/../estimate_batch.sh" "$TOTAL_JOBS" "${RECENT_REF:-}"
