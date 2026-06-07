#!/usr/bin/env bash
# test_three_tier.sh — Functional test for the three-tier scoring system + bypass.
#
# Runs 3 configs on 5 QMM traces to verify:
#   (a) old: THD_DEAD=0, THD_DOA=4  (baseline, single threshold)
#   (b) new: THD_DEAD=2, THD_DOA=4  (three-tier, no bypass)
#   (c) new: THD_DEAD=2, THD_DOA=4, BYPASS_THD=6, LIVENESS_BYPASS=1
#
# Check champsim.out stats for:
#   - Insert mix showing Dead% > 0 in configs (b) and (c)
#   - liveness_bypasses > 0 in config (c)
#   - No crashes / non-zero exit codes

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${SCRIPT_DIR}/_lib.sh"

TRACE_DIR=${TRACE_DIR:-/home/users/otegby/ChampSim-dev/trace-files/QMM}
TRACE_EXT=${TRACE_EXT:-champsimtrace.xz}
WARMUP=${WARMUP:-50000000}
SIM=${SIM:-100000000}
BINARY=${BINARY:-champsim_srrip_live}
N_TRACES=${N_TRACES:-5}

DATE=$(date +%Y%m%d_%H%M)
BASE_LABEL="qmm_three_tier_test_${DATE}"
LOG_DIR="${PROJECT_ROOT}/logs/${BASE_LABEL}"
mkdir -p "$LOG_DIR"

echo "Label   : ${BASE_LABEL}"
echo "Binary  : ${BINARY}"
echo "Traces  : first ${N_TRACES} of QMM"
echo ""

submit_config() {
  local name="$1"; shift
  local extra_vars="$1"; shift

  local run_label="${BASE_LABEL}/${name}"
  mkdir -p "${PROJECT_ROOT}/results/${run_label}"

  local raw
  raw=$(qsub -t "1-${N_TRACES}" \
             -N "tt_${name:0:10}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -l h_rt=4:00:00 \
             -l mem_free=1G \
             -wd "$PROJECT_ROOT" \
             -v WARMUP="$WARMUP",SIM="$SIM",\
TRACE_DIR="$TRACE_DIR",TRACE_EXT="$TRACE_EXT",\
RUN_LABEL="$run_label",BINARY="$BINARY",\
"${extra_vars}" \
             "${PROJECT_ROOT}/scripts/submit/run_cs.sh")
  local jid
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${name}"
}

# (a) Old: single threshold, no mostly_dead tier, no bypass
submit_config "old_thd4" \
  "THD_DEAD=0,THD_DOA=4,LIVENESS_BYPASS=0"

# (b) New: three-tier, no bypass
submit_config "new_thd4_dead2" \
  "THD_DEAD=2,THD_DOA=4,LIVENESS_BYPASS=0"

# (c) New: three-tier + bypass
submit_config "new_thd4_dead2_bypass6" \
  "THD_DEAD=2,THD_DOA=4,BYPASS_THD=6,LIVENESS_BYPASS=1"

finish_submission $(( N_TRACES * 3 )) "${BASE_LABEL}"
