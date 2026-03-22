#!/usr/bin/env bash
# run_local.sh — run the threshold sweep locally without SGE
# Usage: ./run_local.sh {maz|qmm} [--debug] [--warmup N] [--sim N] [--jobs N]
#
# --debug       Run only srv_128 (quick sanity check)
# --warmup N    Warmup instructions   (default: 1000000)
# --sim    N    Simulation instructions (default: 5000000)
# --jobs   N    Max parallel processes  (default: nproc - 1)
#
# Defaults are intentionally small so a local run finishes in minutes.
# Use the cluster values (--warmup 50000000 --sim 100000000) for full fidelity.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Argument parsing ──────────────────────────────────────────────────────────
token=""
DEBUG=0
WARMUP=1000000
SIM=5000000
MAX_JOBS=$(( $(nproc) - 1 ))
MAX_JOBS=$(( MAX_JOBS < 1 ? 1 : MAX_JOBS ))

while [[ $# -gt 0 ]]; do
  case "$1" in
    maz|mazumdar|qmm) token="${1,,}"; shift ;;
    --debug)          DEBUG=1; shift ;;
    --warmup)         WARMUP="$2"; shift 2 ;;
    --sim)            SIM="$2"; shift 2 ;;
    --jobs)           MAX_JOBS="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {maz|qmm} [--debug] [--warmup N] [--sim N] [--jobs N]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {maz|qmm} [--debug] [--warmup N] [--sim N] [--jobs N]" >&2
  exit 2
fi

# ── Trace-set settings ────────────────────────────────────────────────────────
case "$token" in
  maz|mazumdar) TRACE_DIR="${SCRIPT_DIR}/trace-files/MAZUMDAR" ;;
  qmm)          TRACE_DIR="${SCRIPT_DIR}/trace-files/QMM" ;;
esac

BIN="${SCRIPT_DIR}/bin/champsim"
if [ ! -x "$BIN" ]; then
  echo "ERROR: binary not found or not executable: ${BIN}" >&2
  echo "Run 'make -j\$(nproc)' first." >&2
  exit 2
fi

# ── Resolve trace list ────────────────────────────────────────────────────────
mapfile -t TRACES < <(ls -1 "${TRACE_DIR}"/*.champsimtrace.xz 2>/dev/null | sort)
N=${#TRACES[@]}
if [ "$N" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2
  exit 2
fi

if [ "$DEBUG" -eq 1 ]; then
  FILTERED=()
  for t in "${TRACES[@]}"; do
    [[ "$t" == *srv_128* ]] && FILTERED+=("$t")
  done
  if [ ${#FILTERED[@]} -eq 0 ]; then
    echo "WARNING: srv_128 not found — using first trace" >&2
    FILTERED=("${TRACES[0]}")
  fi
  TRACES=("${FILTERED[@]}")
  MODE_TAG="_debug"
else
  MODE_TAG=""
fi

DATE=$(date +%Y%m%d)
BASE_LABEL="${token}_${DATE}${MODE_TAG}_local"

# ── Build config list ─────────────────────────────────────────────────────────
configs=()
configs+=("baseline 0 0 0 0")
for thd in $(seq 0 6); do
  configs+=("pthd${thd} 1 0 ${thd} 0")
done
for pthd in $(seq 0 6); do
  for bthd in $(seq 0 6); do
    configs+=("pthd${pthd}_bthd${bthd} 1 1 ${pthd} ${bthd}")
  done
done

TOTAL=$(( ${#configs[@]} * ${#TRACES[@]} ))
echo "Running ${#configs[@]} configs × ${#TRACES[@]} traces = ${TOTAL} tasks"
echo "Parallel jobs : ${MAX_JOBS}"
echo "Warmup / Sim  : ${WARMUP} / ${SIM}"
echo "Results base  : results/${BASE_LABEL}/"
echo ""

# ── Run tasks with a simple parallelism limiter ───────────────────────────────
run_task() {
  local exp_name=$1 dppred=$2 cbpred=$3 pconf_thd=$4 bconf_thd=$5
  local trace_file=$6
  local trace_name
  trace_name=$(basename "$trace_file" .champsimtrace.xz)

  local run_label="${BASE_LABEL}/${exp_name}"
  local run_dir="${SCRIPT_DIR}/results/${run_label}/${trace_name}"
  mkdir -p "$run_dir"

  cat > "${run_dir}/run_info.txt" <<INFO
run_label=${run_label}
trace=${trace_name}
dppred=${dppred}
cbpred=${cbpred}
pconf_thd=${pconf_thd}
bconf_thd=${bconf_thd}
warmup=${WARMUP}
sim=${SIM}
INFO

  DPPRED=$dppred CBPRED=$cbpred PCONF_THD=$pconf_thd BCONF_THD=$bconf_thd \
    "$BIN" --warmup_instructions "$WARMUP" --simulation_instructions "$SIM" "$trace_file" \
    > "${run_dir}/champsim.out" 2> "${run_dir}/champsim.err"

  echo "  done: ${exp_name} / ${trace_name} (exit $?)"
}

export -f run_task
export WARMUP SIM BIN SCRIPT_DIR BASE_LABEL

running=0
declare -a pids=()

wait_for_slot() {
  while [ "${#pids[@]}" -ge "$MAX_JOBS" ]; do
    local new_pids=()
    for pid in "${pids[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        new_pids+=("$pid")
      else
        (( running-- )) || true
      fi
    done
    pids=("${new_pids[@]}")
    [ "${#pids[@]}" -ge "$MAX_JOBS" ] && sleep 0.5
  done
}

for config in "${configs[@]}"; do
  read -r exp_name dppred cbpred pconf_thd bconf_thd <<< "$config"
  for trace_file in "${TRACES[@]}"; do
    wait_for_slot
    run_task "$exp_name" "$dppred" "$cbpred" "$pconf_thd" "$bconf_thd" "$trace_file" &
    pids+=($!)
    (( running++ )) || true
  done
done

# Wait for all remaining jobs
for pid in "${pids[@]}"; do
  wait "$pid" || true
done

echo ""
echo "All tasks complete. Results under: results/${BASE_LABEL}/"
echo "Generate plots with: python3 plot_heatmap.py results/${BASE_LABEL}/"
