#!/usr/bin/env bash
# gen_mid_lru_study_plots.sh — generate all plots for a mid/lru study directory.
#
# Expects a study directory containing result subdirs produced by sweep_policy.sh
# and sweep_mid.sh.  Detects each dir's type by name pattern:
#
#   *_pol_*       → gen_liveness_plots.sh + doa_correlation bar
#   *_mid_addr_*  → plot_mid_thd (ipc + mpki) + doa_correlation scatter
#   *_mid_pc_*    → same as mid_addr
#
# After per-dir plots, generates a cross-suite IPC comparison from all pol dirs.
#
# Usage:
#   ./scripts/gen_mid_lru_study_plots.sh <study_dir>
#
# Example:
#   ./scripts/gen_mid_lru_study_plots.sh results/mid_lru_study

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANALYSIS_DIR="${SCRIPT_DIR}/analysis"

if [ $# -lt 1 ]; then
  echo "Usage: $0 <study_dir>" >&2
  exit 2
fi

STUDY_DIR="${1%/}"
if [ ! -d "$STUDY_DIR" ]; then
  echo "ERROR: not a directory: $STUDY_DIR" >&2
  exit 2
fi

# ── Migration ─────────────────────────────────────────────────────────────────
echo "========================================"
echo "Step 1: Migrating per-PC stats to CSV"
echo "========================================"
python3 "${SCRIPT_DIR}/migrate_pc_liveness.py" "${STUDY_DIR}"/*/
echo ""

# ── Discover and classify result dirs ─────────────────────────────────────────
pol_dirs=()
mid_dirs=()

for d in "${STUDY_DIR}"/*/; do
  name="$(basename "$d")"
  case "$name" in
    *_pol_*)      pol_dirs+=("${d%/}") ;;
    *_mid_addr_*|*_mid_pc_*) mid_dirs+=("${d%/}") ;;
    *) echo "  Skipping unrecognised dir: $name" ;;
  esac
done

echo "Found ${#pol_dirs[@]} policy dir(s) and ${#mid_dirs[@]} mid-sweep dir(s)."
echo ""

# ── Per-policy-sweep plots ─────────────────────────────────────────────────────
for d in "${pol_dirs[@]}"; do
  name="$(basename "$d")"
  echo "========================================"
  echo "Policy sweep: ${name}"
  echo "========================================"
  OUT_DIR="${d}/plots"
  mkdir -p "$OUT_DIR"

  echo "--- Liveness plots ---"
  bash "${ANALYSIS_DIR}/gen_liveness_plots.sh" "$d" \
    || echo "  WARNING: gen_liveness_plots.sh failed for ${name} — continuing"

  echo "--- DoA correlation bar ---"
  python3 "${ANALYSIS_DIR}/plot_doa_correlation.py" "$d" \
    || echo "  WARNING: doa_correlation failed for ${name} — continuing"

  echo ""
done

# ── Per-mid-sweep plots ────────────────────────────────────────────────────────
for d in "${mid_dirs[@]}"; do
  name="$(basename "$d")"
  echo "========================================"
  echo "Mid-sweep: ${name}"
  echo "========================================"
  OUT_DIR="${d}/plots"
  mkdir -p "$OUT_DIR"

  # Detect mid_key from directory name
  mid_key=""
  [[ "$name" == *_mid_addr_* ]] && mid_key="addr"
  [[ "$name" == *_mid_pc_*   ]] && mid_key="pc"

  # Count how many mid_thd dirs exist
  max_n=0
  for thd_dir in "${d}"/mid_thd*/; do
    [ -d "$thd_dir" ] && (( max_n++ )) || true
  done

  if [ "$max_n" -eq 0 ]; then
    echo "  WARNING: no mid_thd dirs found — skipping"
    echo ""
    continue
  fi

  echo "  max_n=${max_n}  mid_key=${mid_key:-unknown}"

  echo "--- IPC vs mid_thd ---"
  python3 "${ANALYSIS_DIR}/plot_mid_thd.py" "$d" \
    --max-n "$max_n" --metric ipc \
    ${mid_key:+--mid-key "$mid_key"} \
    --out "${OUT_DIR}/mid_thd_ipc.png" \
    || echo "  WARNING: plot_mid_thd (ipc) failed — continuing"

  echo "--- MPKI vs mid_thd ---"
  python3 "${ANALYSIS_DIR}/plot_mid_thd.py" "$d" \
    --max-n "$max_n" --metric mpki \
    ${mid_key:+--mid-key "$mid_key"} \
    --out "${OUT_DIR}/mid_thd_mpki.png" \
    || echo "  WARNING: plot_mid_thd (mpki) failed — continuing"

  echo "--- DoA correlation scatter ---"
  python3 "${ANALYSIS_DIR}/plot_doa_correlation.py" "$d" --scatter \
    || echo "  WARNING: doa_correlation scatter failed — continuing"

  echo ""
done

# ── Cross-suite IPC comparison ─────────────────────────────────────────────────
if [ ${#pol_dirs[@]} -ge 2 ]; then
  echo "========================================"
  echo "Cross-suite IPC comparison"
  echo "========================================"
  CROSS_OUT="${STUDY_DIR}/plots"
  mkdir -p "$CROSS_OUT"

  # Build labels from dir names (strip trailing date _YYYYMMDD_HHMM)
  labels=()
  for d in "${pol_dirs[@]}"; do
    label="$(basename "$d")"
    label="${label%_pol_*}"   # strip _pol_<date>
    labels+=("$label")
  done

  python3 "${ANALYSIS_DIR}/plot_suite_comparison.py" \
    "${pol_dirs[@]}" \
    --labels "${labels[@]}" \
    --out "${CROSS_OUT}/suite_ipc_comparison.png" \
    || echo "  WARNING: cross-suite comparison failed — continuing"

  echo ""
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo "========================================"
echo "Done. Plots written to:"
for d in "${pol_dirs[@]}" "${mid_dirs[@]}"; do
  echo "  ${d}/plots/"
done
if [ ${#pol_dirs[@]} -ge 2 ]; then
  echo "  ${STUDY_DIR}/plots/  (cross-suite)"
fi
