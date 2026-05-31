#!/usr/bin/env bash
# download_validation.sh — Download validation results from cluster

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <result_dir_name>"
  echo "Example: $0 qmm_validate_srrip_live_20260531_1948"
  exit 1
fi

RESULT_DIR="$1"
LOCAL_PATH="${RESULT_DIR}"

echo "Downloading $RESULT_DIR from cluster..."
ssh -A otegby@abdet.inf.um.es "ssh otegby@castillo.inf.um.es \
  'cd ~/ChampSim-dev/results && tar czf - ${RESULT_DIR}/' " | \
  tar xzf - -C results/

echo "Downloaded to: results/${LOCAL_PATH}/"
ls -lh results/${LOCAL_PATH}/
