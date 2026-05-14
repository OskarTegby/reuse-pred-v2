#!/bin/bash
# SGE directives
#$ -N pacipv_search
#$ -o logs/$JOB_NAME_$JOB_ID_$TASK_ID.out
#$ -e logs/$JOB_NAME_$JOB_ID_$TASK_ID.err
#$ -l h_rt=24:00:00
#$ -l mem_free=1G
#
# run_pacipv_search.sh — run one (IPV pair, trace) combination.
#
# Task ID encodes a 2D index:
#   pair_idx  = (SGE_TASK_ID - 1) / N_SEARCH_TRACES
#   trace_idx = (SGE_TASK_ID - 1) % N_SEARCH_TRACES
#
# The IPV pair for pair_idx is read from PARAMS_FILE (line pair_idx+1,
# tab-separated: demand_ipv <TAB> prefetch_ipv).
#
# The swept class is set by CLASS_DEMAND_VAR / CLASS_PREFETCH_VAR, which
# name the PACIPV_* env vars to populate from the params file.
# The other four vectors are passed directly via env vars at qsub time.

set -euo pipefail

WARMUP=${WARMUP:-50000000}
SIM=${SIM:-100000000}
TRACE_DIR=${TRACE_DIR:-}
TRACE_EXT=${TRACE_EXT:-champsimtrace.xz}
RUN_BASE=${RUN_BASE:-unlabelled}
BINARY=${BINARY:-champsim_pacipv}
PARAMS_FILE=${PARAMS_FILE:-}
N_SEARCH_TRACES=${N_SEARCH_TRACES:-8}

# Names of the two env vars to populate from the params file for the
# class being swept (e.g. "PACIPV_DOA_DEMAND" and "PACIPV_DOA_PREFETCH").
CLASS_DEMAND_VAR=${CLASS_DEMAND_VAR:-PACIPV_MOSTLY_ALIVE_DEMAND}
CLASS_PREFETCH_VAR=${CLASS_PREFETCH_VAR:-PACIPV_MOSTLY_ALIVE_PREFETCH}

# Fixed vectors for the non-swept classes (passed via -v at qsub time).
export PACIPV_DOA_DEMAND=${PACIPV_DOA_DEMAND:-0,0,1,2,3}
export PACIPV_DOA_PREFETCH=${PACIPV_DOA_PREFETCH:-0,0,0,2,3}
export PACIPV_MOSTLY_DEAD_DEMAND=${PACIPV_MOSTLY_DEAD_DEMAND:-0,0,0,2,3}
export PACIPV_MOSTLY_DEAD_PREFETCH=${PACIPV_MOSTLY_DEAD_PREFETCH:-0,0,0,2,3}
export PACIPV_MOSTLY_ALIVE_DEMAND=${PACIPV_MOSTLY_ALIVE_DEMAND:-0,1,1,0,3}
export PACIPV_MOSTLY_ALIVE_PREFETCH=${PACIPV_MOSTLY_ALIVE_PREFETCH:-0,1,0,0,3}

# ── Decode 2D task index ──────────────────────────────────────────────────────
: "${SGE_TASK_ID:=1}"
FLAT_IDX=$(( SGE_TASK_ID - 1 ))
PAIR_IDX=$(( FLAT_IDX / N_SEARCH_TRACES ))
TRACE_IDX=$(( FLAT_IDX % N_SEARCH_TRACES ))

# ── Read IPV pair from params file ────────────────────────────────────────────
if [ -z "$PARAMS_FILE" ] || [ ! -f "$PARAMS_FILE" ]; then
  echo "ERROR: PARAMS_FILE not set or not found: $PARAMS_FILE" >&2; exit 1
fi

LINE=$(sed -n "$((PAIR_IDX + 1))p" "$PARAMS_FILE")
if [ -z "$LINE" ]; then
  echo "ERROR: pair_idx $PAIR_IDX out of range in $PARAMS_FILE" >&2; exit 1
fi

DEMAND_IPV=$(echo "$LINE" | cut -f1)
PREFETCH_IPV=$(echo "$LINE" | cut -f2)

export "${CLASS_DEMAND_VAR}"="$DEMAND_IPV"
export "${CLASS_PREFETCH_VAR}"="$PREFETCH_IPV"

# ── Select trace ──────────────────────────────────────────────────────────────
mapfile -t ALL_TRACES < <(find "${TRACE_DIR}" -name "*.${TRACE_EXT}" | sort)
N_TOTAL=${#ALL_TRACES[@]}
if [ "$N_TOTAL" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2; exit 1
fi
if [ "$TRACE_IDX" -ge "$N_TOTAL" ]; then
  echo "ERROR: trace_idx $TRACE_IDX >= N_TOTAL $N_TOTAL" >&2; exit 1
fi

TRACE_FILE="${ALL_TRACES[$TRACE_IDX]}"
TRACE_NAME=$(basename "$TRACE_FILE" ".${TRACE_EXT}")

# ── Set up output directory ───────────────────────────────────────────────────
PAIR_TAG=$(printf "pair_%05d" "$PAIR_IDX")
RUN_DIR="results/${RUN_BASE}/${PAIR_TAG}/${TRACE_NAME}"
mkdir -p "$RUN_DIR"

# Record the IPV pair alongside the results for analysis.
cat > "${RUN_DIR}/ipv_pair.txt" <<IPV
demand=${DEMAND_IPV}
prefetch=${PREFETCH_IPV}
IPV

# ── Sanity checks ─────────────────────────────────────────────────────────────
BIN="./bin/${BINARY}"
if [ ! -x "$BIN" ]; then
  echo "ERROR: binary not found: $BIN" >&2; exit 1
fi

# ── Run ───────────────────────────────────────────────────────────────────────
echo "pair=${PAIR_IDX} trace=${TRACE_NAME} ${CLASS_DEMAND_VAR}=${DEMAND_IPV} ${CLASS_PREFETCH_VAR}=${PREFETCH_IPV}"

"$BIN" --warmup_instructions "$WARMUP" --simulation_instructions "$SIM" \
  "$TRACE_FILE" \
  > "${RUN_DIR}/champsim.out" 2> "${RUN_DIR}/champsim.err"
rc=$?

date
echo "Exit code: $rc"
exit $rc
