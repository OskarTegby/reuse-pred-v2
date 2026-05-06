#!/usr/bin/env bash
# sweep_threshold_oldcfg.sh — full dpPred/cbPred threshold sweep (7×7 grid)
# using the pre-Mazumdar cache configuration (champsim_lru_oldcfg).
#
# Produces the same directory layout as the March 2026 QMM sweep
# (results/qmm_20260322) so that plot_heatmap.py works unchanged.
#
# Configs submitted (57 per suite):
#   baseline          DPPRED=0, CBPRED=0
#   pthd{0..6}        DPPRED=1, CBPRED=0, PCONF_THD={0..6}
#   pthd{N}_bthd{M}   DPPRED=1, CBPRED=1, PCONF_THD=N, BCONF_THD=M  (N,M ∈ 0..6)
#
# Usage: ./sweep_threshold_oldcfg.sh {dpc3|google|qmm|test} [--debug]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

token=""
DEBUG=0
TEST=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    qmm|dpc3|google|test) token="${1,,}"; shift ;;
    --test)  TEST=1; shift ;;
    --debug) DEBUG=1; shift ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {qmm|dpc3|google|test} [--test] [--debug]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {qmm|dpc3|google|test} [--test] [--debug]" >&2; exit 2
fi

BINARY="champsim_lru_oldcfg"
SHARED_TRACES=/home/users/shared/traces

case "$token" in
  qmm)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/QMM"
    TRACE_EXT="champsimtrace.xz" ;;
  dpc3)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/dpc3_traces"
    TRACE_EXT="champsimtrace.xz" ;;
  google)
    WARMUP=50000000; SIM=100000000
    TRACE_DIR="${SHARED_TRACES}/Google_Traces_v2"
    TRACE_EXT="champsim.gz" ;;
  test)
    WARMUP=1000000; SIM=5000000
    TRACE_DIR="${PROJECT_ROOT}/trace-files/TEST"
    TRACE_EXT="champsimtrace.xz" ;;
esac

[ "$TEST" -eq 1 ] && { WARMUP=25000000; SIM=50000000; DEBUG=1; }

mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N=${#TRACES[@]}
[ "$N" -eq 0 ] && { echo "ERROR: no traces in ${TRACE_DIR}" >&2; exit 2; }

if [ "$DEBUG" -eq 1 ]; then
  TASK_RANGE="1-1"
else
  TASK_RANGE="1-${N}"
fi

if [ ! -x "${PROJECT_ROOT}/bin/${BINARY}" ]; then
  echo "ERROR: binary not found: bin/${BINARY}" >&2; exit 2
fi

DATE=$(date +%Y%m%d_%H%M)
TEST_TAG=$( [ "$TEST" -eq 1 ] && echo "_test" || echo "" )
BASE_LABEL="${token}_oldcfg_thd_${DATE}${TEST_TAG}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

# ── Build config list ─────────────────────────────────────────────────────────
# Format: "exp_name dppred cbpred pconf bconf"
configs=("baseline 0 0 6 6")
for p in 0 1 2 3 4 5 6; do
  configs+=("pthd${p} 1 0 ${p} 6")
done
for p in 0 1 2 3 4 5 6; do
  for b in 0 1 2 3 4 5 6; do
    configs+=("pthd${p}_bthd${b} 1 1 ${p} ${b}")
  done
done

echo "Binary  : ${BINARY}  (old config: L2C 512 KB, LLC 20 cy)"
echo "Suite   : ${token}  (${N} traces)"
echo "Configs : ${#configs[@]}  (1 baseline + 7 dpPred-only + 49 dpPred+cbPred)"
echo "Jobs    : $((${#configs[@]} * N))  (task range per array: ${TASK_RANGE})"
echo "Results : results/${BASE_LABEL}/"
echo "Logs    : logs/${BASE_LABEL}/"
echo ""

for cfg in "${configs[@]}"; do
  read -r exp_name dppred cbpred pconf bconf <<< "$cfg"
  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "${PROJECT_ROOT}/results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "thd_${exp_name}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",RUN_LABEL="$RUN_LABEL",BINARY="$BINARY",DPPRED="$dppred",CBPRED="$cbpred",PCONF_THD="$pconf",BCONF_THD="$bconf",MID_THD=1,MID_KEY=0,MID_PROMOTE=0 \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}"
done

echo ""
echo "Monitor : qstat -u \$USER"
echo "Results : results/${BASE_LABEL}/"
