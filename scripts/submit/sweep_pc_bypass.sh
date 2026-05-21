#!/usr/bin/env bash
# sweep_pc_bypass.sh — compare PC-indexed and merged bypass history modes.
#
# All runs use DPPRED=1, CBPRED=1, hashed phist, default PFQ cap=8.
# CBPRED_IDX selects which history table drives the bypass decision:
#
#   lru_baseline   — no predictor                             (IPC floor)
#   addr_pred      — existing paper-style (CBPRED_IDX=addr)  (reference)
#   pc_pred        — PC-indexed bypass (CBPRED_IDX=pc)
#   pc_addr_pred   — combined strict-AND (CBPRED_IDX=pc_addr)
#   pc_or_addr_pred— combined OR       (CBPRED_IDX=pc_or_addr)
#   merged_pred    — merged STLB+LLC table (CBPRED_IDX=merged)
#
# Behavioral study (--behavioral): one extra config with PC_STATS=1 that
# populates the merged_pc_hist CSV for cross-level correlation analysis.
# Run on a subset of traces (--test or small suite) to keep file sizes down.
#
# Usage: ./sweep_pc_bypass.sh {maz|qmm|dpc3|google|gap|ligra|gms|ml|test}
#                             [--test] [--debug] [--behavioral]
#                             [--warmup N] [--sim N]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

BINARY="champsim_lru"

token=""
DEBUG=0
TEST=0
BEHAVIORAL=0
WARMUP_OVERRIDE=""
SIM_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    maz|mazumdar|qmm|dpc3|google|gap|ligra|gms|ml|test) token="${1,,}"; shift ;;
    --test)       TEST=1;       shift ;;
    --debug)      DEBUG=1;      shift ;;
    --behavioral) BEHAVIORAL=1; shift ;;
    --warmup) WARMUP_OVERRIDE="$2"; shift 2 ;;
    --sim)    SIM_OVERRIDE="$2";    shift 2 ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {maz|qmm|dpc3|google|gap|ligra|gms|ml|test} [--test] [--debug] [--behavioral] [--warmup N] [--sim N]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {maz|qmm|dpc3|google|gap|ligra|gms|ml|test} [--test] [--debug] [--behavioral] [--warmup N] [--sim N]" >&2
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
BASE_LABEL="${token}_pc_bypass_${DATE}${TEST_TAG}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"
source "${SCRIPT_DIR}/_manifest.sh"
write_manifest

# Config format:
#   exp_name  dppred cbpred  cbpred_idx  phist_hash bhist_hash  phist_ways bhist_ways
#
# All pred configs share: PCONF_THD=6, BCONF_THD=6, PFQ_CAP=8, ST_SIZE=2.
# Hashed phist (PHIST_HASH=1): matches paper baseline for dpPred.
# bhist_hash is irrelevant for pc/merged modes but kept consistent.
configs=(
  "lru_baseline      0 0   addr   1 1   1024 4096"
  "addr_pred         1 1   addr   1 1   1024 4096"
  "pc_pred           1 1   pc     1 1   1024 4096"
  "pc_addr_pred      1 1   pc_addr     1 1   1024 4096"
  "pc_or_addr_pred   1 1   pc_or_addr  1 1   1024 4096"
  "merged_pred       1 1   merged 1 1   1024 4096"
)

echo "Submitting ${#configs[@]} configs × ${N} traces (${TASK_RANGE})"
echo "Suite   : ${token}"
echo "Binary  : ${BINARY}"
echo "Warmup  : ${WARMUP}  Sim: ${SIM}"
echo "Results : results/${BASE_LABEL}/"
echo "Logs    : logs/${BASE_LABEL}/"
echo ""

for cfg in "${configs[@]}"; do
  read -r exp_name dppred cbpred cbpred_idx phist_hash bhist_hash phist_ways bhist_ways <<< "$cfg"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "pcb_${exp_name:0:10}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",\
DPPRED="$dppred",CBPRED="$cbpred",PCONF_THD=6,BCONF_THD=6,\
MID_THD=1,MID_KEY=0,MID_PROMOTE=0,\
PHIST_HASH="$phist_hash",BHIST_HASH="$bhist_hash",\
PHIST_SETS=1,PHIST_WAYS="$phist_ways",BHIST_SETS=1,BHIST_WAYS="$bhist_ways",\
CBPRED_IDX="$cbpred_idx",CBPRED_NO_PFQ=0,\
PFQ_CAP=8,ST_SIZE=2 \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  printf "  [jid=%-8s] %-22s  CBPRED_IDX=%-12s\n" "$jid" "$exp_name" "$cbpred_idx"
done

# Behavioral study: merged_pred with PC_STATS=1 to collect merged_pc_hist CSV.
# Runs on the same task range by default, but --test limits to 5 traces.
if [ "$BEHAVIORAL" -eq 1 ]; then
  echo ""
  echo "Submitting behavioral study (PC_STATS=1, merged_pred) ..."
  exp_name="behavioral_study"
  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "pcb_behav" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",\
DPPRED=1,CBPRED=1,PCONF_THD=6,BCONF_THD=6,\
MID_THD=1,MID_KEY=0,MID_PROMOTE=0,\
PHIST_HASH=1,BHIST_HASH=1,\
PHIST_SETS=1,PHIST_WAYS=1024,BHIST_SETS=1,BHIST_WAYS=4096,\
CBPRED_IDX=merged,CBPRED_NO_PFQ=0,\
PFQ_CAP=8,ST_SIZE=2,PC_STATS=1 \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  printf "  [jid=%-8s] %-22s  PC_STATS=1\n" "$jid" "$exp_name"
fi

echo ""
echo "Monitor : qstat -u \$USER"
echo "Results : results/${BASE_LABEL}/"
echo ""
echo "Analysis (after results are in):"
echo "  python3 scripts/analysis/plot_merged_pc_correlation.py \\"
echo "      results/${BASE_LABEL}/behavioral_study/ --suite ${token}"
