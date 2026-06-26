#!/usr/bin/env bash
# Submit black-box full jobs on the cluster.
# Each job runs a scenario and saves output to test_outputs/.
# Comparison against expected reference outputs is done locally by
# blackbox_run_cluster.sh, not on the cluster.
#
# Usage (called by blackbox_run_cluster.sh, not directly):
#   bash blackbox_validation.sh     # submit all 26 full jobs
set -euo pipefail

ROOT=/home/users/otegby/ChampSim-dev
RUNNER=$ROOT/test/blackbox/run_scenario.sh
TRACE=$ROOT/trace-files/ligra/ligra_PageRank.com-lj.ungraph.gcc_6.3.0_O3.drop_51000M.length_250M.champsimtrace.xz
OUTPUT_DIR=$ROOT/test/blackbox/test_outputs
LOGDIR=$ROOT/test/blackbox/logs
mkdir -p "$LOGDIR" "$OUTPUT_DIR"

SCENARIOS=(
  lru_default lru_2n3 lru_lru lru_bypass lru_bypass_off
  lru_duel_hits lru_duel_lat_hyst lru_cap256
  srrip_default srrip_mode3 srrip_mode4 srrip_mode5 srrip_mode7 srrip_mode8
  srrip_cap256 srrip_duel_cfg0 srrip_bypass_fixed srrip_bypass_duel
  ipv_default ipv_canonical ipv_ins3_comma ipv_ins3_colon ipv_cap256
  duel_ipv_cfg0_ins2 duel_ipv_cfg0_ins3 duel_ipv_3way
)

for scen in "${SCENARIOS[@]}"; do
  qsub -N "bb_${scen}" -j y \
       -o "$LOGDIR/${scen}.full.log" \
       -v "SRC_ROOT=$ROOT,BIN_DIR=$ROOT/bin,TRACE=$TRACE,OUTPUT_DIR=$OUTPUT_DIR,GENERATE=1" \
       -b y bash "$RUNNER" "$scen" full
done

echo "Submitted ${#SCENARIOS[@]} gate jobs"
