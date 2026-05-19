#!/usr/bin/env bash
# run_debug_bypass.sh — local single-trace validation for CBPRED weighted bypass.
#
# Runs srv_128 through 3 configs (baseline, cbpred_unweighted, cbpred_weighted)
# and prints a summary of key stats.  No qsub — runs sequentially in-process.
#
# Usage:
#   ./scripts/submit/run_debug_bypass.sh [--warmup N] [--sim N] [--trace PATH]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

BINARY="${PROJECT_ROOT}/bin/champsim_srrip_live"
TRACE="/home/otegby/repos/code/ChampSim-dev/trace-files/QMM/srv_128.champsimtrace.xz"
WARMUP=25000000
SIM=50000000

while [[ $# -gt 0 ]]; do
  case "$1" in
    --warmup) WARMUP="$2"; shift 2 ;;
    --sim)    SIM="$2";    shift 2 ;;
    --trace)  TRACE="$2";  shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ ! -x "$BINARY" ]; then
  echo "ERROR: binary not found or not executable: $BINARY" >&2
  echo "  Run: make -j$(nproc) champsim_srrip_live  (from project root)" >&2
  exit 1
fi
if [ ! -f "$TRACE" ]; then
  echo "ERROR: trace not found: $TRACE" >&2
  exit 1
fi

TRACE_NAME=$(basename "$TRACE" .champsimtrace.xz)
OUT_DIR="${PROJECT_ROOT}/results/debug_bypass/${TRACE_NAME}"
mkdir -p "$OUT_DIR"

run_config() {
  local label="$1"; shift
  local dir="${OUT_DIR}/${label}"
  mkdir -p "$dir"

  echo "=== ${label} ===" >&2
  # All env vars for the binary
  env "$@" \
    PHIST_HASH=1 BHIST_HASH=1 \
    PHIST_SETS=1 PHIST_WAYS=64 \
    BHIST_SETS=1 BHIST_WAYS=64 \
    REPL_POL=lru PFQ_CAP=8 ST_SIZE=2 \
    MID_THD=1 MID_KEY=0 MID_PROMOTE=0 \
    "$BINARY" \
      --warmup_instructions "$WARMUP" \
      --simulation_instructions "$SIM" \
      "$TRACE" \
      > "${dir}/champsim.out" \
      2> "${dir}/champsim.err"
  local rc=$?

  local sz
  sz=$(du -sh "${dir}/champsim.out" | cut -f1)
  echo "  exit=${rc}  out=${sz}" >&2

  if [ "$rc" -ne 0 ]; then
    echo "  FAILED — last 20 lines of stderr:" >&2
    tail -20 "${dir}/champsim.err" >&2
  fi
  return $rc
}

# 1) Baseline: no bypass at all
run_config "baseline" \
  DPPRED=0 CBPRED=0 PCONF_THD=0 BCONF_THD=0 \
  CBPRED_WEIGHTED=0 CBPRED_W_NORMAL=2 CBPRED_W_LOW=1 CBPRED_W_MISPREDICT=2

# 2) CBPRED unweighted (original, flat bhist updates)
run_config "cbpred_unweighted" \
  DPPRED=1 CBPRED=1 PCONF_THD=6 BCONF_THD=2 \
  CBPRED_WEIGHTED=0 CBPRED_W_NORMAL=2 CBPRED_W_LOW=1 CBPRED_W_MISPREDICT=2

# 3) CBPRED weighted
run_config "cbpred_weighted" \
  DPPRED=1 CBPRED=1 PCONF_THD=6 BCONF_THD=2 \
  CBPRED_WEIGHTED=1 CBPRED_W_NORMAL=2 CBPRED_W_LOW=1 CBPRED_W_MISPREDICT=2

echo ""
echo "Results written to: ${OUT_DIR}"
echo "Run the analysis script to generate plots:"
echo "  python3 scripts/analysis/plot_debug_bypass.py ${OUT_DIR}"
