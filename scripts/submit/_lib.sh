#!/usr/bin/env bash
# _lib.sh — shared helpers for sweep submission scripts.
# Source this file; do not execute it directly.

# finish_submission <n_jobs> <results_base_label>
#
# Prints the standard "all submitted" footer and a wall-clock estimate.
# Call this at the end of every sweep script in place of the ad-hoc echo block.
#
#   n_jobs            total array tasks submitted (configs × traces)
#   results_base_label  BASE_LABEL used for this sweep (e.g. qmm_pfq_gating_...)
finish_submission() {
  local n_jobs=$1
  local base_label=${2:-}

  echo ""
  echo "All configs submitted. Monitor with: qstat -u \$USER"
  [ -n "$base_label" ] && echo "Results will appear under: results/${base_label}/"

  # Find a reference directory: prefer one inside the current sweep's results,
  # fall back to the most recently written champsim.out anywhere under results/.
  local ref_dir=""
  if [ -n "$base_label" ]; then
    ref_dir=$(find "${PROJECT_ROOT}/results/${base_label}" \
                -mindepth 2 -maxdepth 2 -name "champsim.out" \
                -printf "%h\n" 2>/dev/null | head -1 | xargs dirname 2>/dev/null || true)
  fi
  if [ -z "$ref_dir" ]; then
    ref_dir=$(find "${PROJECT_ROOT}/results" \
                -mindepth 3 -maxdepth 3 -name "champsim.out" \
                -printf "%T@ %h\n" 2>/dev/null \
              | sort -n | tail -1 | awk '{print $2}' \
              | xargs dirname 2>/dev/null || true)
  fi

  local save_dir=""
  [ -n "$base_label" ] && save_dir="${PROJECT_ROOT}/results/${base_label}"
  bash "${SCRIPT_DIR}/../estimate_batch.sh" "$n_jobs" "${ref_dir:-}" "${save_dir}"
}
