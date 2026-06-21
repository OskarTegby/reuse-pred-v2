#!/usr/bin/env bash
# sweep_lru_srrip_baselines.sh — Plain LRU and SRRIP baselines for all 7 suites.
#
# Purpose: provide matched LRU (champsim_lru) and SRRIP (champsim_srrip) baseline
# IPC values so that liveness-guided policies can be expressed as speedup over each.
# QMM baselines already exist in qmm_thd_rebaseline_20260604_2307; this script
# fills in the remaining six suites.
#
# Results land under: results/{LABEL}/{suite}/{lru,srrip}/{trace_name}/champsim.out
set -euo pipefail

BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="all_lru_srrip_baselines_${DATE}"
LOG_DIR="${BASE}/logs/${LABEL}"
mkdir -p "$LOG_DIR"

SHARED=/home/users/shared/traces

declare -A SUITE_TRACES SUITE_N
SUITE_TRACES=(
  [dpc3]="${SHARED}/dpc3_traces"
  [gap]="${BASE}/trace-files/gap"
  [gms]="${BASE}/trace-files/gms"
  [google]="${SHARED}/Google_Traces_v2"
  [ligra]="${BASE}/trace-files/ligra"
  [ml]="${BASE}/trace-files/ml"
  [qmm]="${BASE}/trace-files/QMM"
)

submit_policy() {
  local suite="$1" binary="$2" pol="$3"
  local trace_dir="${SUITE_TRACES[$suite]}"
  local n
  n=$(find "$trace_dir" -name "*.champsimtrace.xz" | wc -l)
  if [ "$n" -eq 0 ]; then
    echo "  SKIP $suite/$pol — no traces in $trace_dir"
    return
  fi
  local run_label="${LABEL}/${suite}/${pol}"
  mkdir -p "${BASE}/results/${run_label}"
  local jid
  jid=$(qsub -t "1-${n}" \
             -N "bl_${suite:0:3}_${pol:0:3}" \
             -o "${LOG_DIR}/" \
             -e "${LOG_DIR}/" \
             -l h_rt=24:00:00 \
             -l mem_free=1G \
             -wd "$BASE" \
             -v WARMUP="$W",SIM="$S",\
TRACE_DIR="$trace_dir",TRACE_EXT="champsimtrace.xz",\
RUN_LABEL="$run_label",BINARY="$binary" \
             "${BASE}/scripts/submit/run_cs.sh" \
       | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${suite}/${pol}  (n=${n} traces)"
}

echo "Label: ${LABEL}"
echo ""

for suite in dpc3 gap gms google ligra ml qmm; do
  echo "=== ${suite} ==="
  submit_policy "$suite" champsim_lru   lru
  submit_policy "$suite" champsim_srrip srrip
  echo ""
done

echo "Done. Results in: results/${LABEL}/"
