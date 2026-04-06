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

# Predictor parameters (read from env by ChampSim; defaults = baseline)
export DPPRED=${DPPRED:-0}
export CBPRED=${CBPRED:-0}
export PCONF_THD=${PCONF_THD:-0}
export BCONF_THD=${BCONF_THD:-0}
export MID_THD=${MID_THD:-1}

# Binary selection: BINARY env var selects the per-policy executable.
# Defaults to champsim_lru_mid for backwards compatibility.
BINARY=${BINARY:-champsim_lru_mid}
BIN="./bin/${BINARY}"

# Build sorted list of traces at runtime
mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
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
dppred=${DPPRED}
cbpred=${CBPRED}
pconf_thd=${PCONF_THD}
bconf_thd=${BCONF_THD}
mid_thd=${MID_THD}
warmup=${WARMUP}
sim=${SIM}
INFO

# Run the binary
echo "Run: ${RUN_LABEL}  trace: ${TRACE_NAME}"
"$BIN" --warmup_instructions "$WARMUP" --simulation_instructions "$SIM" \
  --pc-stats="${RUN_DIR}/pc_liveness.csv" "$TRACE_FILE" \
  > "${RUN_DIR}/champsim.out" 2> "${RUN_DIR}/champsim.err"
rc=$?

date
echo "Exit code: $rc"
exit $rc
