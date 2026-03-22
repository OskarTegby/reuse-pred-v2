#!/usr/bin/env bash
# gen_plots.sh — check sweep completion and launch plot_heatmap.py per trace
# Usage: ./gen_plots.sh <results_dir>
#   e.g. ./gen_plots.sh results/qmm_20260322_debug/

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <results_dir>" >&2
  exit 2
fi

BASE="${1%/}"
PLOT_SCRIPT="$(dirname "$0")/plot_heatmap.py"
PLOTS_DIR="${BASE}/plots"
mkdir -p "$PLOTS_DIR"

# All expected configs
CONFIGS=("baseline")
for thd in $(seq 0 6); do
  CONFIGS+=("pthd${thd}")
done
for pthd in $(seq 0 6); do
  for bthd in $(seq 0 6); do
    CONFIGS+=("pthd${pthd}_bthd${bthd}")
  done
done
TOTAL=${#CONFIGS[@]}

# Detect traces from baseline dir
BASELINE_DIR="${BASE}/baseline"
if [ ! -d "$BASELINE_DIR" ]; then
  echo "ERROR: baseline/ not found under ${BASE}" >&2
  exit 2
fi
mapfile -t TRACES < <(ls -1 "$BASELINE_DIR")
if [ ${#TRACES[@]} -eq 0 ]; then
  echo "ERROR: no trace results found in ${BASELINE_DIR}" >&2
  exit 2
fi

echo "Results dir : ${BASE}"
echo "Traces found: ${TRACES[*]}"
echo ""

# ── Completion check ──────────────────────────────────────────────────────────
for TRACE in "${TRACES[@]}"; do
  done_count=0
  missing=()

  for cfg in "${CONFIGS[@]}"; do
    out="${BASE}/${cfg}/${TRACE}/champsim.out"
    if [ -f "$out" ] && grep -q "Region of Interest Statistics" "$out" 2>/dev/null; then
      done_count=$((done_count + 1))
    else
      missing+=("$cfg")
    fi
  done

  echo "  ${TRACE}: ${done_count}/${TOTAL} configs complete"
  if [ ${#missing[@]} -gt 0 ] && [ ${#missing[@]} -le 10 ]; then
    echo "    Missing: ${missing[*]}"
  elif [ ${#missing[@]} -gt 10 ]; then
    echo "    Missing: ${missing[*]:0:10} ... (${#missing[@]} total)"
  fi
done

echo ""

# ── Plot ──────────────────────────────────────────────────────────────────────
for TRACE in "${TRACES[@]}"; do
  out_png="${PLOTS_DIR}/heatmap_${TRACE}.png"
  echo "Plotting ${TRACE} → ${out_png}"
  python3 "$PLOT_SCRIPT" "$BASE" --trace "$TRACE" --out "$out_png"
done

echo ""
echo "Done. Plots saved to ${PLOTS_DIR}/"
