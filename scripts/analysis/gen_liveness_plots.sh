#!/usr/bin/env bash
# gen_liveness_plots.sh — generate all liveness plots from a policy sweep result dir.
#
# Usage:
#   ./scripts/analysis/gen_liveness_plots.sh <results_dir> [--out-dir <dir>]
#
# <results_dir> is the top-level directory from sweep_policy.sh, e.g.:
#   results/dpc3_pol_20260401_1400/
#   results/dpc3_pol_20260401_1400_debug/
#
# It must contain subdirectories named after the configs:
#   lru/  srrip/  drrip/  lru_mid/  lru_pred/  lru_mid_pred/  ...
#
# Outputs (saved to --out-dir, default: <results_dir>/plots/):
#   liveness_LLC.png          — stacked bar chart, all policies, LLC
#   liveness_STLB.png         — stacked bar chart, all policies, STLB
#   pc_LLC_<policy>_scatter.png   — per-PC scatter for each policy
#   pc_STLB_<policy>_scatter.png

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Arguments ─────────────────────────────────────────────────────────────────
if [ $# -lt 1 ]; then
  echo "Usage: $0 <results_dir> [--out-dir <dir>]" >&2
  exit 2
fi

RESULTS_DIR="${1%/}"
OUT_DIR=""

shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ ! -d "$RESULTS_DIR" ]; then
  echo "ERROR: not a directory: $RESULTS_DIR" >&2
  exit 2
fi

OUT_DIR="${OUT_DIR:-${RESULTS_DIR}/plots}"
mkdir -p "$OUT_DIR"

# ── Discover which config subdirs are present ─────────────────────────────────
# Baseline policies (no predictor)
BASELINE_CONFIGS=(lru srrip drrip lru_mid)
# Predictor-augmented variants
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
    # strip trailing _pred for a cleaner label, add + sign
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

# ── Helper: join arrays into space-separated strings ─────────────────────────
join_dirs()   { printf '%s ' "$@"; }
join_labels() { printf '%s ' "$@"; }

# ── 1. Per-access liveness bar charts ────────────────────────────────────────
echo "=== Liveness bar charts ==="

# All configs in one chart
all_dirs=("${present_baseline[@]}" "${present_pred[@]}")
all_labels=("${present_baseline_labels[@]}" "${present_pred_labels[@]}")

python3 "${SCRIPT_DIR}/plot_liveness_bar.py" \
  "${all_dirs[@]}" \
  --labels "${all_labels[@]}" \
  --out "${OUT_DIR}/liveness.png"

echo ""

# ── 2. Per-PC scatter plots ───────────────────────────────────────────────────
echo "=== Per-PC scatter plots ==="

for cache in LLC cpu0_STLB; do
  echo "  Cache: ${cache}"

  # One scatter per baseline policy so they can be compared individually
  for i in "${!present_baseline[@]}"; do
    cfg_dir="${present_baseline[$i]}"
    cfg_label="${present_baseline_labels[$i]}"
    safe_label="${cfg_label//+pred/pred}"

    python3 "${SCRIPT_DIR}/analyze_pc_liveness.py" \
      "$cfg_dir" \
      --cache "$cache" \
      --out "${OUT_DIR}/pc_${cache}_${safe_label}"
  done

  # Combined scatter: all baseline policies overlaid (multi-suite mode)
  if [ ${#present_baseline[@]} -gt 1 ]; then
    python3 "${SCRIPT_DIR}/analyze_pc_liveness.py" \
      "${present_baseline[@]}" \
      --labels "${present_baseline_labels[@]}" \
      --cache "$cache" \
      --out "${OUT_DIR}/pc_${cache}_baseline_all"
  fi
done

echo ""
echo "Done. All plots saved to: ${OUT_DIR}/"
ls "${OUT_DIR}/"
