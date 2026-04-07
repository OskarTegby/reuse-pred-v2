#!/usr/bin/env bash
# gen_liveness_plots.sh — generate all plots from a policy sweep result dir.
#
# Usage:
#   ./scripts/analysis/gen_liveness_plots.sh <results_dir>
#
# <results_dir> is the top-level directory from sweep_policy.sh, e.g.:
#   results/dpc3_pol_20260401_1400/
#
# All plots are saved to <results_dir>/plots/.
#
# Plots produced:
#   policy_comparison_*.png     — IPC speedup and MPKI bar charts (per workload + geomean)
#   liveness.png                — per-access liveness bars across all policies
#   liveness_<config>.png       — per-workload liveness bars + geomean, one per config
#   pc_liveness_LLC_*_scatter.png   — per-PC liveness scatter (LLC) per policy
#   pc_liveness_STLB_*_scatter.png  — per-PC liveness scatter (STLB) per policy

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Arguments ─────────────────────────────────────────────────────────────────
if [ $# -lt 1 ]; then
  echo "Usage: $0 <results_dir>" >&2
  exit 2
fi

RESULTS_DIR="${1%/}"

if [ ! -d "$RESULTS_DIR" ]; then
  echo "ERROR: not a directory: $RESULTS_DIR" >&2
  exit 2
fi

OUT_DIR="${RESULTS_DIR}/plots"
mkdir -p "$OUT_DIR"

# ── Discover which config subdirs are present ─────────────────────────────────
BASELINE_CONFIGS=(lru srrip drrip lru_mid)
PRED_CONFIGS=(lru_pred lru_mid_pred srrip_pred drrip_pred)

present_baseline=()
present_baseline_labels=()
present_pred=()
present_pred_labels=()

for cfg in "${BASELINE_CONFIGS[@]}"; do
  if [ -d "${RESULTS_DIR}/${cfg}" ]; then
    present_baseline+=("${RESULTS_DIR}/${cfg}")
    present_baseline_labels+=("$cfg")
  fi
done

for cfg in "${PRED_CONFIGS[@]}"; do
  if [ -d "${RESULTS_DIR}/${cfg}" ]; then
    present_pred+=("${RESULTS_DIR}/${cfg}")
    label="${cfg%_pred}+pred"
    present_pred_labels+=("$label")
  fi
done

if [ ${#present_baseline[@]} -eq 0 ]; then
  echo "ERROR: no recognised config subdirs found in ${RESULTS_DIR}" >&2
  echo "  Expected any of: ${BASELINE_CONFIGS[*]} ${PRED_CONFIGS[*]}" >&2
  exit 2
fi

echo "Results dir : ${RESULTS_DIR}"
echo "Output dir  : ${OUT_DIR}"
echo "Baseline configs found : ${present_baseline_labels[*]:-none}"
echo "Predictor configs found: ${present_pred_labels[*]:-none}"
echo ""

# ── 1. IPC speedup and MPKI bar charts ───────────────────────────────────────
echo "=== Policy comparison (IPC / MPKI) ==="

python3 "${SCRIPT_DIR}/plot_policy_comparison.py" \
  "${RESULTS_DIR}" \
  --out "${OUT_DIR}/policy_comparison" \
  || echo "  WARNING: policy comparison plots failed — skipped"

echo ""

# ── 2. Per-access liveness: one bar per workload + geomean, per config ────────
echo "=== Per-workload liveness bars ==="

all_configs=("${present_baseline_labels[@]}" "${present_pred_labels[@]//+pred/_pred}")

for cfg in "${present_baseline_labels[@]}" "${present_pred_labels[@]//+pred/_pred}"; do
  if [ -d "${RESULTS_DIR}/${cfg}" ]; then
    echo "  Config: ${cfg}"
    python3 "${SCRIPT_DIR}/plot_liveness.py" \
      "${RESULTS_DIR}" \
      --config "${cfg}" \
      || echo "  WARNING: liveness plot failed for ${cfg} — skipped"
  fi
done

echo ""

# ── 3. Cross-policy liveness bar chart ───────────────────────────────────────
echo "=== Cross-policy liveness bar chart ==="

all_dirs=("${present_baseline[@]}" "${present_pred[@]}")
all_labels=("${present_baseline_labels[@]}" "${present_pred_labels[@]}")

python3 "${SCRIPT_DIR}/plot_liveness_bar.py" \
  "${all_dirs[@]}" \
  --labels "${all_labels[@]}" \
  --summary \
  --out "${OUT_DIR}/liveness.png"

echo ""

# ── 4. Per-PC scatter plots ───────────────────────────────────────────────────
echo "=== Per-PC scatter plots ==="

for cache in LLC cpu0_STLB; do
  echo "  Cache: ${cache}"
  for cfg_dir in "${present_baseline[@]}"; do
    python3 "${SCRIPT_DIR}/analyze_pc_liveness.py" \
      "$cfg_dir" \
      --cache "$cache" \
      || echo "  WARNING: no per-PC data for ${cfg_dir##*/} ${cache} — skipped"
  done
done

echo ""
echo "Done. All plots saved to: ${OUT_DIR}/"
ls "${OUT_DIR}/"
