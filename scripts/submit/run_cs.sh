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
export MID_KEY=${MID_KEY:-0}
export MID_PROMOTE=${MID_PROMOTE:-0}
export CBPRED_WEIGHTED=${CBPRED_WEIGHTED:-0}
export CBPRED_NO_PFQ=${CBPRED_NO_PFQ:-0}
export PFQ_ADAPTIVE_WINDOW=${PFQ_ADAPTIVE_WINDOW:-0}
export PFQ_ADAPTIVE_THD=${PFQ_ADAPTIVE_THD:-30}
export CBPRED_W_NORMAL=${CBPRED_W_NORMAL:-2}
export CBPRED_W_LOW=${CBPRED_W_LOW:-1}
export CBPRED_W_MISPREDICT=${CBPRED_W_MISPREDICT:-2}
export BYPASS_DEBT_SCALE=${BYPASS_DEBT_SCALE:-0}
export BYPASS_DEBT_CAP=${BYPASS_DEBT_CAP:-0}

# History-table and queue parameters (read from env by ChampSim)
export PHIST_HASH=${PHIST_HASH:-1}
export BHIST_HASH=${BHIST_HASH:-1}
export PHIST_SETS=${PHIST_SETS:-1}
export PHIST_WAYS=${PHIST_WAYS:-1024}
export BHIST_SETS=${BHIST_SETS:-1}
export BHIST_WAYS=${BHIST_WAYS:-4096}
export REPL_POL=${REPL_POL:-lru}
export PFQ_CAP=${PFQ_CAP:-8}
export ST_SIZE=${ST_SIZE:-2}

# Binary selection: BINARY env var selects the per-policy executable.
BINARY=${BINARY:-champsim_lru}
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
mid_key=${MID_KEY}
mid_promote=${MID_PROMOTE}
phist_hash=${PHIST_HASH}
bhist_hash=${BHIST_HASH}
phist_sets=${PHIST_SETS}
phist_ways=${PHIST_WAYS}
bhist_sets=${BHIST_SETS}
bhist_ways=${BHIST_WAYS}
repl_pol=${REPL_POL}
pfq_cap=${PFQ_CAP}
st_size=${ST_SIZE}
cbpred_no_pfq=${CBPRED_NO_PFQ}
pfq_adaptive_window=${PFQ_ADAPTIVE_WINDOW}
pfq_adaptive_thd=${PFQ_ADAPTIVE_THD}
cbpred_weighted=${CBPRED_WEIGHTED}
cbpred_w_normal=${CBPRED_W_NORMAL}
cbpred_w_low=${CBPRED_W_LOW}
cbpred_w_mispredict=${CBPRED_W_MISPREDICT}
bypass_debt_scale=${BYPASS_DEBT_SCALE}
bypass_debt_cap=${BYPASS_DEBT_CAP}
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
