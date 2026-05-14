#!/usr/bin/env bash
# coord_descent_pacipv.sh — coordinate-descent training for the PACIPV 6-vector policy.
#
# Sweeps the three liveness classes in order (mostly_alive → mostly_dead → doa),
# holding the other two fixed.  After each class sweep the best vectors are
# extracted and passed as fixed values for the next sweep.  Rounds repeat until
# no vector changes between rounds (convergence) or --rounds is exhausted.
#
# The ordering constraint (doa[k] >= mostly_dead[k] >= mostly_alive[k]) is
# enforced automatically: sweep_pacipv_class.sh passes --min-ipv to
# enumerate_ipvs.py based on the current fixed lower-class vectors.
#
# Usage:
#   ./coord_descent_pacipv.sh {dpc3|google|qmm|test} \
#       [--rounds N] [--max-traces N] \
#       [--baseline-dir DIR]... \
#       [--warmup N] [--sim N] [--debug]
#
# Defaults: --rounds 5, --max-traces 8.
# Jobs are submitted via SGE (qsub) and the script blocks until each
# job array completes before proceeding to the next sweep.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── Argument parsing ──────────────────────────────────────────────────────────
token=""
MAX_ROUNDS=5
MAX_TRACES=8
DEBUG=0
WARMUP_ARG=""
SIM_ARG=""
BASELINE_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    dpc3|google|qmm|test) token="${1,,}"; shift ;;
    --rounds)       MAX_ROUNDS="$2"; shift 2 ;;
    --max-traces)   MAX_TRACES="$2"; shift 2 ;;
    --baseline-dir) BASELINE_ARGS+=(--baseline-dir "$2"); shift 2 ;;
    --warmup)       WARMUP_ARG="--warmup $2"; shift 2 ;;
    --sim)          SIM_ARG="--sim $2"; shift 2 ;;
    --debug)        DEBUG=1; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {dpc3|google|qmm|test} [options]" >&2
  exit 2
fi

DEBUG_FLAG=""; [ "$DEBUG" -eq 1 ] && DEBUG_FLAG="--debug"

# ── Initial vectors (pacipv.cc defaults) ─────────────────────────────────────
MA_D="0,1,1,0,3";  MA_P="0,1,0,0,3"
MD_D="0,0,0,2,3";  MD_P="0,0,0,2,3"
DOA_D="0,0,1,2,3"; DOA_P="0,0,0,2,3"

# ── Helpers ───────────────────────────────────────────────────────────────────

# Run one class sweep; block until the SGE job array finishes.
# Prints the absolute path to the results directory on stdout.
sweep_and_wait() {
  local sweep_output jid results_rel results_dir

  sweep_output=$("${SCRIPT_DIR}/sweep_pacipv_class.sh" "$@" 2>&1 | tee /dev/stderr)

  results_rel=$(echo "$sweep_output" | awk '/^Results/ {print $NF}' | tr -d '/')
  results_dir="${PROJECT_ROOT}/${results_rel}"

  jid=$(echo "$sweep_output" | grep -o 'jid=[0-9]*' | cut -d= -f2 || true)

  if [ -n "$jid" ]; then
    echo "[coord] Waiting for SGE job ${jid}..." >&2
    while qstat -j "$jid" &>/dev/null; do sleep 30; done
    echo "[coord] Job ${jid} finished." >&2
  fi

  echo "$results_dir"
}

# Extract the best demand and prefetch vectors from a completed sweep.
# Prints two space-separated values: <demand_ipv> <prefetch_ipv>
best_vectors() {
  local results_dir="$1"
  local output demand prefetch
  output=$(python3 "${PROJECT_ROOT}/scripts/analysis/find_best_pacipv.py" \
             "$results_dir" "${BASELINE_ARGS[@]}" 2>/dev/null)
  demand=$(echo  "$output" | awk '/^  demand/   {print $NF}')
  prefetch=$(echo "$output" | awk '/^  prefetch/ {print $NF}')
  if [ -z "$demand" ] || [ -z "$prefetch" ]; then
    echo "[coord] ERROR: could not parse best vectors from ${results_dir}" >&2
    exit 1
  fi
  echo "$demand $prefetch"
}

# ── Main loop ─────────────────────────────────────────────────────────────────
echo "[coord] Starting coordinate descent for ${token}"
echo "[coord] Initial vectors:"
echo "          mostly_alive  demand=${MA_D}  prefetch=${MA_P}"
echo "          mostly_dead   demand=${MD_D}  prefetch=${MD_P}"
echo "          doa           demand=${DOA_D}  prefetch=${DOA_P}"
echo ""

for round in $(seq 1 "$MAX_ROUNDS"); do
  echo "[coord] ── Round ${round} ──────────────────────────────────"
  prev_MA_D=$MA_D;  prev_MA_P=$MA_P
  prev_MD_D=$MD_D;  prev_MD_P=$MD_P
  prev_DOA_D=$DOA_D; prev_DOA_P=$DOA_P

  # ── Sweep mostly_alive (unconstrained) ───────────────────────────────────
  echo "[coord] Sweeping mostly_alive..."
  rdir=$(sweep_and_wait "$token" mostly_alive \
    --mostly-dead-d "$MD_D"  --mostly-dead-p "$MD_P" \
    --doa-d         "$DOA_D" --doa-p         "$DOA_P" \
    --max-traces "$MAX_TRACES" $WARMUP_ARG $SIM_ARG $DEBUG_FLAG)
  read -r MA_D MA_P <<< "$(best_vectors "$rdir")"
  echo "[coord]   best mostly_alive: demand=${MA_D}  prefetch=${MA_P}"

  # ── Sweep mostly_dead (constrained by MA) ────────────────────────────────
  echo "[coord] Sweeping mostly_dead (constrained by mostly_alive)..."
  rdir=$(sweep_and_wait "$token" mostly_dead \
    --mostly-alive-d "$MA_D" --mostly-alive-p "$MA_P" \
    --doa-d          "$DOA_D" --doa-p         "$DOA_P" \
    --max-traces "$MAX_TRACES" $WARMUP_ARG $SIM_ARG $DEBUG_FLAG)
  read -r MD_D MD_P <<< "$(best_vectors "$rdir")"
  echo "[coord]   best mostly_dead:  demand=${MD_D}  prefetch=${MD_P}"

  # ── Sweep doa (constrained by MD) ────────────────────────────────────────
  echo "[coord] Sweeping doa (constrained by mostly_dead)..."
  rdir=$(sweep_and_wait "$token" doa \
    --mostly-alive-d "$MA_D" --mostly-alive-p "$MA_P" \
    --mostly-dead-d  "$MD_D" --mostly-dead-p  "$MD_P" \
    --max-traces "$MAX_TRACES" $WARMUP_ARG $SIM_ARG $DEBUG_FLAG)
  read -r DOA_D DOA_P <<< "$(best_vectors "$rdir")"
  echo "[coord]   best doa:          demand=${DOA_D}  prefetch=${DOA_P}"

  echo ""
  echo "[coord] Round ${round} result:"
  echo "          mostly_alive  demand=${MA_D}  prefetch=${MA_P}"
  echo "          mostly_dead   demand=${MD_D}  prefetch=${MD_P}"
  echo "          doa           demand=${DOA_D}  prefetch=${DOA_P}"
  echo ""

  # ── Convergence check ────────────────────────────────────────────────────
  if [ "$MA_D"  = "$prev_MA_D"  ] && [ "$MA_P"  = "$prev_MA_P"  ] && \
     [ "$MD_D"  = "$prev_MD_D"  ] && [ "$MD_P"  = "$prev_MD_P"  ] && \
     [ "$DOA_D" = "$prev_DOA_D" ] && [ "$DOA_P" = "$prev_DOA_P" ]; then
    echo "[coord] Converged after round ${round}."
    break
  fi
  echo "[coord] Vectors changed; continuing to round $((round + 1))."
done

# ── Final summary ─────────────────────────────────────────────────────────────
echo ""
echo "[coord] ── Final vectors ───────────────────────────────────"
echo "  mostly_alive  demand=${MA_D}  prefetch=${MA_P}"
echo "  mostly_dead   demand=${MD_D}  prefetch=${MD_P}"
echo "  doa           demand=${DOA_D}  prefetch=${DOA_P}"
echo ""
echo "To run with these vectors, set:"
echo "  PACIPV_MOSTLY_ALIVE_DEMAND=${MA_D}"
echo "  PACIPV_MOSTLY_ALIVE_PREFETCH=${MA_P}"
echo "  PACIPV_MOSTLY_DEAD_DEMAND=${MD_D}"
echo "  PACIPV_MOSTLY_DEAD_PREFETCH=${MD_P}"
echo "  PACIPV_DOA_DEMAND=${DOA_D}"
echo "  PACIPV_DOA_PREFETCH=${DOA_P}"
