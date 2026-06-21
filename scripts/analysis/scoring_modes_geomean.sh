#!/usr/bin/env bash
# scoring_modes_geomean.sh — Geomean IPC vs SRRIP for scoring mode sweep across all suites.
export LC_ALL=C
BASE=~/ChampSim-dev
DATE=20260608_2350

declare -A SRRIP_DIR
SRRIP_DIR[dpc3]=$BASE/results/dpc3_thd_rebaseline_20260605_2316/srrip
SRRIP_DIR[gap]=$BASE/results/gap_thd_rebaseline_20260605_2316/srrip
SRRIP_DIR[gms]=$BASE/results/gms_thd_rebaseline_20260605_2316/srrip
SRRIP_DIR[ligra]=$BASE/results/ligra_thd_rebaseline_20260605_2316/srrip
SRRIP_DIR[ml]=$BASE/results/ml_thd_rebaseline_20260605_2316/srrip
SRRIP_DIR[qmm]=$BASE/results/qmm_thd_rebaseline_20260604_2307/srrip

geomean_mode() {
  local dir=$1 srrip=$2 mode=$3
  local prod=1 n=0 missing=0
  for tdir in "$dir"/*/; do
    local trace; trace=$(basename "$tdir")
    local ipc; ipc=$(awk '/CPU 0 cumulative IPC/ {print $5}' "$tdir/champsim.out" 2>/dev/null)
    # baseline dirs may have various suffixes depending on suite
    local sdir="$srrip/$trace"
    [ ! -d "$sdir" ] && sdir="$srrip/$trace.trace"
    [ ! -d "$sdir" ] && sdir="$srrip/$trace.champsimtrace"
    local sipc; sipc=$(awk '/CPU 0 cumulative IPC/ {print $5}' "$sdir/champsim.out" 2>/dev/null)
    if [ -z "$ipc" ] || [ -z "$sipc" ]; then missing=$((missing+1)); continue; fi
    ratio=$(awk -v a="$ipc" -v b="$sipc" 'BEGIN{printf "%.6f",a/b}')
    prod=$(awk -v p="$prod" -v r="$ratio" 'BEGIN{printf "%.10f",p*r}')
    n=$((n+1))
  done
  awk -v p="$prod" -v n="$n" -v m="$missing" -v mode="$mode" \
    'BEGIN{
      if(n>0){geo=p^(1/n); printf "  %-14s  %3d traces  %+.2f%%  (missing=%d)\n",mode,n,(geo-1)*100,m}
      else   {printf "  %-14s  NO DATA\n",mode}
    }'
}

for suite in dpc3 gap gms ligra ml qmm; do
  echo "=== $suite ==="
  srrip=${SRRIP_DIR[$suite]}
  label=${suite}_scoring_modes_${DATE}
  for mode in mode0_ref mode0_flat3 mode3_decoup mode4_cal; do
    geomean_mode "$BASE/results/$label/$mode" "$srrip" "$mode"
  done
  echo ""
done
