#!/usr/bin/env bash
# submit_cs.sh - helper to submit the SGE job with preset WARMUP/SIM/TRACE_DIR per token
# Usage: ./submit_cs.sh maz|qmm [additional qsub args...]

if [ $# -lt 1 ]; then
  echo "Usage: $0 {maz|qmm} [qsub args...]" >&2
  exit 2
fi

token="$1"; shift

case "${token,,}" in
  maz|mazumdar)
    WARMUP=100000000
    SIM=1000000000
    TRACE_DIR=trace-files/MAZUMDAR
    ;;
  qmm)
    WARMUP=50000000
    SIM=100000000
    TRACE_DIR=trace-files/QMM
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
mkdir -p logs "results/${RUN_LABEL}"

JOBSCRIPT="run_cs.sh"

echo "Run label: ${RUN_LABEL} — results will be in results/${RUN_LABEL}/<trace>/"

qsub -t "1-${N}" \
     -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",RUN_LABEL="$RUN_LABEL" \
     "$@" "$JOBSCRIPT"
