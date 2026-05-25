#!/bin/bash
# SGE directives
#$ -N baseline_verify
#$ -o logs/
#$ -e logs/
#$ -l h_rt=24:00:00
#$ -l mem_free=1G

# Worker for verify_baseline_qmm.sh — runs one trace per array task.
# All parameters come from qsub -v.

WARMUP=${WARMUP:-50000000}
SIM=${SIM:-100000000}
TRACE_DIR=${TRACE_DIR:-trace-files/QMM}
TRACE_EXT=${TRACE_EXT:-champsimtrace.xz}
RUN_LABEL=${RUN_LABEL:-qmm_baseline_verify}
BINARY=${BINARY:-champsim_lru}

export DPPRED=${DPPRED:-0}
export CBPRED=${CBPRED:-0}
export PCONF_THD=${PCONF_THD:-0}
export BCONF_THD=${BCONF_THD:-0}
export MID_THD=${MID_THD:-0}
export MID_KEY=${MID_KEY:-0}
export MID_PROMOTE=${MID_PROMOTE:-0}

BIN="./bin/${BINARY}"

mapfile -t TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N=${#TRACES[@]}
[ "$N" -eq 0 ] && { echo "ERROR: no traces in ${TRACE_DIR}" >&2; exit 1; }

: "${SGE_TASK_ID:=1}"
IDX=$((SGE_TASK_ID - 1))
[ "$IDX" -lt 0 ] || [ "$IDX" -ge "$N" ] && { echo "ERROR: task $SGE_TASK_ID out of range 1..$N" >&2; exit 1; }

TRACE_FILE="${TRACES[$IDX]}"
TRACE_NAME=$(basename "$TRACE_FILE" ".${TRACE_EXT}")
RUN_DIR="results/${RUN_LABEL}/${TRACE_NAME}"
mkdir -p "$RUN_DIR"

[ ! -x "$BIN" ] && { echo "ERROR: binary not found: $BIN" >&2; exit 1; }
[ ! -f "$TRACE_FILE" ] && { echo "ERROR: trace not found: $TRACE_FILE" >&2; exit 1; }

cat > "${RUN_DIR}/run_info.txt" <<INFO
run_label=${RUN_LABEL}
trace=${TRACE_NAME}
binary=${BINARY}
dppred=${DPPRED}
cbpred=${CBPRED}
pconf_thd=${PCONF_THD}
bconf_thd=${BCONF_THD}
mid_thd=${MID_THD}
mid_key=${MID_KEY}
mid_promote=${MID_PROMOTE}
warmup=${WARMUP}
sim=${SIM}
INFO

echo "Run: ${RUN_LABEL}  trace: ${TRACE_NAME}"
"$BIN" --warmup_instructions "$WARMUP" --simulation_instructions "$SIM" "$TRACE_FILE" \
  > "${RUN_DIR}/champsim.out" 2> "${RUN_DIR}/champsim.err"
rc=$?
date
echo "Exit code: $rc"
exit $rc
