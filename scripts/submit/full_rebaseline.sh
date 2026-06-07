#!/bin/bash
set -euo pipefail
# full_rebaseline.sh — Rebaseline all 6 suites with the corrected binary.
#
# Fixes vs. previous rebaseline:
#   - ins_class now set from classify_block_liveness() at fill time
#   - MID_THD renamed to THD_DOA in env vars
#
# Runs: LRU, SRRIP baselines + SRRIP-Live/IPV-Live LLC threshold sweep {1,2,4,8,16}
# Google excluded (no trace access from cluster).

BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
SHARED=/home/users/shared/traces

declare -A SUITE_TRACES SUITE_EXT SUITE_N
SUITE_TRACES=(
  [dpc3]="${SHARED}/dpc3_traces"
  [gap]="${BASE}/trace-files/gap"
  [gms]="${BASE}/trace-files/gms"
  [ligra]="${BASE}/trace-files/ligra"
  [ml]="${BASE}/trace-files/ml"
  [qmm]="${BASE}/trace-files/QMM"
)
SUITE_EXT=(
  [dpc3]="champsimtrace.xz"
  [gap]="trace.gz"
  [gms]="champsimtrace.gz"
  [ligra]="champsimtrace.xz"
  [ml]="champsimtrace.gz"
  [qmm]="champsimtrace.xz"
)
SUITE_N=(
  [dpc3]=95  [gap]=9  [gms]=11  [ligra]=17  [ml]=31  [qmm]=45
)

total=0

submit() {
  local suite="$1" label="$2" binary="$3" jobname="$4"; shift 4
  local n="${SUITE_N[$suite]}"
  local tdir="${SUITE_TRACES[$suite]}"
  local ext="${SUITE_EXT[$suite]}"
  mkdir -p "$BASE/results/$label" "$BASE/logs/$label"
  local jid
  jid=$(qsub -t "1-${n}" -N "$jobname" \
       -o "$BASE/logs/$label/" -e "$BASE/logs/$label/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "$BASE" \
       -v WARMUP=$W,SIM=$S,TRACE_DIR="$tdir",TRACE_EXT="$ext",\
RUN_LABEL="$label",BINARY="$binary",$* \
       "$BASE/scripts/submit/run_cs.sh" \
       | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=$jid] $label  (n=$n)"
  total=$((total + n))
}

for suite in dpc3 gap gms ligra ml qmm; do
  LABEL="${suite}_thd_rebaseline_${DATE}"
  echo "=== ${suite} ==="

  submit "$suite" "$LABEL/lru"   champsim_lru   "rb_${suite:0:3}_lru"
  submit "$suite" "$LABEL/srrip" champsim_srrip "rb_${suite:0:3}_srp"

  for thd in 1 2 4 8 16; do
    submit "$suite" "$LABEL/srrip_live_llc/thd${thd}" champsim_srrip_live \
      "rsl_${suite:0:3}_${thd}" \
      "THD_DOA=${thd},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"
    submit "$suite" "$LABEL/ipv_live_llc/thd${thd}" champsim_ipv_live \
      "ril_${suite:0:3}_${thd}" \
      "THD_DOA=${thd},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"
  done
  echo ""
done

echo "Total jobs submitted: $total"
echo "Label pattern: {suite}_thd_rebaseline_${DATE}"
