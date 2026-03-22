#!/usr/bin/env bash
# submit_cs.sh - helper to submit the SGE job with preset WARMUP/SIM/TRACE_DIR per token
# Usage: ./submit_cs.sh maz|qmm [additional qsub args...]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ $# -lt 1 ]; then
  echo "Usage: $0 {maz|qmm} [qsub args...]" >&2
  exit 2
fi

token="$1"; shift

case "${token,,}" in
  maz|mazumdar)
    WARMUP=100000000
    SIM=1000000000
    TRACE_DIR="${SCRIPT_DIR}/trace-files/MAZUMDAR"
    ;;
  qmm)
    WARMUP=50000000
    SIM=100000000
    TRACE_DIR="${SCRIPT_DIR}/trace-files/QMM"
    ;;
  *)
    echo "Unknown token: $token — use maz or qmm" >&2
    exit 2
    ;;
esac

# Count traces so we can set the array range correctly
mapfile -t TRACES < <(ls -1 "${TRACE_DIR}"/*.champsimtrace.xz 2>/dev/null | sort)
N=${#TRACES[@]}
if [ "$N" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2
  exit 2
fi
echo "Found $N traces in ${TRACE_DIR}"

# Label for this run: e.g. qmm_20260322
RUN_LABEL="${token,,}_$(date +%Y%m%d)"

# Ensure logs and results dirs exist before SGE tries to write to them
LOG_DIR="${SCRIPT_DIR}/logs/${RUN_LABEL}"
mkdir -p "$LOG_DIR" "${SCRIPT_DIR}/results/${RUN_LABEL}"

echo "Run label : ${RUN_LABEL} — results will be in results/${RUN_LABEL}/<trace>/"
echo "Logs      : logs/${RUN_LABEL}/"

qsub -t "1-${N}" \
     -o "${LOG_DIR}/" \
     -e "${LOG_DIR}/" \
     -wd "$SCRIPT_DIR" \
     -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",RUN_LABEL="$RUN_LABEL" \
     "$@" "${SCRIPT_DIR}/run_cs.sh"
