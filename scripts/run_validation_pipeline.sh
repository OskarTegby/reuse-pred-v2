#!/usr/bin/env bash
# run_validation_pipeline.sh — Full pipeline: validation→analysis→exp016/017
#
# This script waits for validation jobs to complete, downloads results,
# analyzes them against the baseline, and if successful, submits exp016/017.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Configuration
VALIDATION_DIR="${1:-qmm_validate_srrip_live_20260531_1948}"
BASELINE_DIR="${2:-qmm_srrip_live_thd_pc_20260513_0056}"
POLL_INTERVAL=300  # seconds

echo "=========================================="
echo "Validation Pipeline"
echo "=========================================="
echo ""
echo "Validation dir: $VALIDATION_DIR"
echo "Baseline dir:   $BASELINE_DIR"
echo "Poll interval:  ${POLL_INTERVAL}s"
echo ""

# ── Wait for validation jobs to complete ──────────────────────────────────────
echo "[1/4] Waiting for validation jobs to complete..."
while true; do
  RUNNING=$(ssh -A otegby@abdet.inf.um.es "ssh otegby@castillo.inf.um.es 'qstat -u otegby 2>/dev/null | grep -E \"1403591|1403592\" | grep -v qw | wc -l'" 2>/dev/null || echo "0")
  QUEUED=$(ssh -A otegby@abdet.inf.um.es "ssh otegby@castillo.inf.um.es 'qstat -u otegby 2>/dev/null | grep -E \"1403591|1403592\" | grep qw | wc -l'" 2>/dev/null || echo "2")

  if [ "$RUNNING" -gt 0 ]; then
    echo "  $(date): $RUNNING job(s) running, $QUEUED queued..."
  elif [ "$QUEUED" -eq 0 ]; then
    echo "  $(date): All jobs complete!"
    break
  else
    echo "  $(date): $QUEUED job(s) waiting for resources..."
  fi

  sleep "$POLL_INTERVAL"
done

echo ""
echo "[2/4] Downloading results..."
bash "$SCRIPT_DIR/download_validation.sh" "$VALIDATION_DIR"

echo ""
echo "[3/4] Analyzing results..."
bash "$SCRIPT_DIR/analysis/validate_replacement_integration.sh" "$VALIDATION_DIR" "$BASELINE_DIR"

echo ""
echo "[4/4] Submitting exp016/017..."
echo "  Ready to submit exp016 and exp017 (srrip_live with 512x8 and unbounded bHIST)"
echo "  Run:"
echo "    bash $SCRIPT_DIR/submit/sweep_exp016.sh qmm"
echo "    bash $SCRIPT_DIR/submit/sweep_exp017.sh qmm"
