#!/usr/bin/env bash
# Submit black-box full jobs on the cluster.
# Each job runs a scenario and saves output to test_outputs/.
# Comparison against expected reference outputs is done locally by
# blackbox_run_cluster.sh, not on the cluster.
#
# Usage (called by blackbox_run_cluster.sh, not directly):
#   bash blackbox_validation.sh     # submit all full jobs
#
# The scenario list and per-scenario trace are owned by run_scenario.sh
# (--list); this script only fans them out over the queue. No single TRACE is
# pinned here -- each scenario resolves its own real trace.
set -euo pipefail

ROOT=/home/users/otegby/ChampSim-dev
RUNNER=$ROOT/test/blackbox/run_scenario.sh
OUTPUT_DIR=$ROOT/test/blackbox/test_outputs
LOGDIR=$ROOT/test/blackbox/logs
mkdir -p "$LOGDIR" "$OUTPUT_DIR"

mapfile -t SCENARIOS < <(bash "$RUNNER" --list)

for scen in "${SCENARIOS[@]}"; do
  qsub -N "bb_${scen}" -j y \
       -o "$LOGDIR/${scen}.log" \
       -v "SRC_ROOT=$ROOT,BIN_DIR=$ROOT/bin,OUTPUT_DIR=$OUTPUT_DIR,GENERATE=1" \
       -b y bash "$RUNNER" "$scen"
done

echo "Submitted ${#SCENARIOS[@]} full jobs"
