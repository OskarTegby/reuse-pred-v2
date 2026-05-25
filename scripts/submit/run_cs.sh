#!/bin/bash
# SGE directives
#$ -N cs_sim
#$ -o logs/$JOB_NAME_$JOB_ID_$TASK_ID.out
#$ -e logs/$JOB_NAME_$JOB_ID_$TASK_ID.err
#$ -l h_rt=24:00:00
#$ -l mem_free=1G

# Defaults (overridden at submit time via qsub -v)
WARMUP=${WARMUP:-500000}
SIM=${SIM:-1000000}
TRACE_DIR=${TRACE_DIR:-trace-files/MAZUMDAR}
TRACE_EXT=${TRACE_EXT:-champsimtrace.xz}
RUN_LABEL=${RUN_LABEL:-unlabelled}

# Replacement policy parameters (read from env by ChampSim; defaults = baseline)
export MID_THD=${MID_THD:-1}
export MID_KEY=${MID_KEY:-0}
export MID_PROMOTE=${MID_PROMOTE:-0}
export REPL_POL=${REPL_POL:-lru}

# Binary selection: BINARY env var selects the per-policy executable.
BINARY=${BINARY:-champsim_lru}
BIN="./bin/${BINARY}"

# Build sorted list of traces at runtime (TRACE_FILTER narrows to selected workloads)
if [ -n "${TRACE_FILTER:-}" ]; then
  mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort | grep -E "${TRACE_FILTER}")
else
  mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
fi
N=${#TRACES[@]}
if [ "$N" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2
  exit 1
fi

# Default SGE_TASK_ID to 1 if not running as array task (allows single-job runs)
: "${SGE_TASK_ID:=1}"

IDX=$((SGE_TASK_ID - 1))
if [ "$IDX" -lt 0 ] || [ "$IDX" -ge "$N" ]; then
  echo "ERROR: SGE_TASK_ID ($SGE_TASK_ID) out of range (1..$N)" >&2
  exit 1
fi

TRACE_FILE="${TRACES[$IDX]}"
TRACE_NAME=$(basename "$TRACE_FILE" ".${TRACE_EXT}")
RUN_DIR="results/${RUN_LABEL}/${TRACE_NAME}"
mkdir -p "$RUN_DIR"

# Sanity checks
if [ ! -x "$BIN" ]; then
  echo "ERROR: binary not found or not executable: $BIN" >&2
  exit 1
fi

if [ ! -f "$TRACE_FILE" ]; then
  echo "ERROR: trace not found: $TRACE_FILE" >&2
  exit 1
fi

# Write config summary alongside results
cat > "${RUN_DIR}/run_info.txt" <<INFO
run_label=${RUN_LABEL}
trace=${TRACE_NAME}
binary=${BINARY}
mid_thd=${MID_THD}
mid_key=${MID_KEY}
mid_promote=${MID_PROMOTE}
repl_pol=${REPL_POL}
warmup=${WARMUP}
sim=${SIM}
INFO

# Run the binary
# PC_STATS=1 enables per-PC liveness CSV output (large files; off by default)
PC_STATS=${PC_STATS:-0}
PC_STATS_ARG=()
[ "${PC_STATS}" = "1" ] && PC_STATS_ARG=(--pc-stats="${RUN_DIR}/pc_liveness.csv")

echo "Run: ${RUN_LABEL}  trace: ${TRACE_NAME}"
"$BIN" --warmup_instructions "$WARMUP" --simulation_instructions "$SIM" \
  "${PC_STATS_ARG[@]}" "$TRACE_FILE" \
  > "${RUN_DIR}/champsim.out" 2> "${RUN_DIR}/champsim.err"
rc=$?

date
echo "Exit code: $rc"

# Append one completion line to the parent-level log so the whole suite's
# progress can be followed with: tail -f results/<label>/completed.log
LOG_BASE="${RUN_LABEL%/*}"
[ "$LOG_BASE" != "$RUN_LABEL" ] && \
    printf '%s  exit=%d  %-20s  [%s]\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$rc" "$TRACE_NAME" "${RUN_LABEL##*/}" \
        >> "${PROJECT_ROOT}/results/${LOG_BASE}/completed.log"

exit $rc
