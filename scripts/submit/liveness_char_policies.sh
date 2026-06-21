#!/bin/bash
# liveness_char_policies.sh — per-PC liveness characterisation for SRRIP and IPV baselines.
#
# Runs champsim_srrip and champsim_ipv with LIVENESS_CHAR=1 on every trace in
# every suite. Produces the same LIVENESS_CHAR BEGIN/END blocks as the LRU run
# (liveness_char_20260601_1907) so all three baseline policies can be compared.
#
# Enables two follow-up comparisons:
#   1. Figure: DoA/MD/alive split under LRU vs SRRIP vs IPV (motivation figure)
#   2. Later: compare with guided variants to show guidance reduces DoA fraction
#
# Usage: ./liveness_char_policies.sh

set -euo pipefail

BASE=/home/users/otegby/ChampSim-dev
W=50000000
S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="liveness_char_policies_${DATE}"

declare -A SUITE_DIRS=(
  [dpc3]="/home/users/shared/traces/dpc3_traces"
  [gap]="${BASE}/trace-files/gap"
  [gms]="${BASE}/trace-files/gms"
  [google]="/home/users/shared/traces/Google_Traces_v2"
  [ligra]="${BASE}/trace-files/ligra"
  [ml]="${BASE}/trace-files/ml"
  [qmm]="${BASE}/trace-files/QMM"
)

declare -A SUITE_EXTS=(
  [dpc3]="champsimtrace.xz"
  [gap]="trace.gz"
  [gms]="champsimtrace.gz"
  [google]="champsim.gz"
  [ligra]="champsimtrace.xz"
  [ml]="champsimtrace.gz"
  [qmm]="champsimtrace.xz"
)

declare -A SUITE_N=(
  [dpc3]=95 [gap]=9 [gms]=11 [google]=43 [ligra]=18 [ml]=31 [qmm]=45
)

submit() {
  local binary="$1" suite="$2"
  local n="${SUITE_N[$suite]}"
  local tdir="${SUITE_DIRS[$suite]}"
  local ext="${SUITE_EXTS[$suite]}"
  local run_label="${LABEL}/${binary}/${suite}"
  local jobname="${binary:10:1}c_${suite:0:3}"   # e.g. sc_gap, ic_qmm

  mkdir -p "${BASE}/results/${run_label}" "${BASE}/logs/${LABEL}"

  local jid
  jid=$(qsub -t "1-${n}" -N "${jobname}" \
       -o "${BASE}/logs/${LABEL}/" -e "${BASE}/logs/${LABEL}/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "${BASE}" \
       -v "WARMUP=${W},SIM=${S},TRACE_DIR=${tdir},TRACE_EXT=${ext},RUN_LABEL=${run_label},BINARY=${binary},LIVENESS_CHAR=1" \
       "${BASE}/scripts/submit/run_cs.sh" \
    | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${binary}/${suite}: ${n} traces"
}

echo "=== Liveness characterisation: SRRIP and IPV baselines ==="
echo "=== Label: ${LABEL} ==="
echo ""

for binary in champsim_srrip champsim_ipv; do
  echo "--- ${binary} ---"
  for suite in dpc3 gap gms google ligra ml qmm; do
    submit "${binary}" "${suite}"
  done
  echo ""
done

total=$(( (95 + 9 + 11 + 43 + 18 + 31 + 45) * 2 ))
echo "Label: ${LABEL}"
echo "Arrays: 2 policies * 7 suites = 14 arrays"
echo "Total tasks: ${total} (252 per policy)"
