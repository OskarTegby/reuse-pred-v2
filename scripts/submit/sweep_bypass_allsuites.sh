#!/usr/bin/env bash
set -euo pipefail
# sweep_bypass_allsuites.sh — LLC bypass threshold sweep across all 6 benchmark suites.
#
# Configs (6 per suite):
#   srrip         : plain SRRIP baseline (no liveness prediction)
#   repl_only     : SRRIP-Live replacement only, no bypass
#   bypass_thd4   : LIVENESS_BYPASS=1, BYPASS_THD=4  (= THD_DOA)
#   bypass_thd8   : LIVENESS_BYPASS=1, BYPASS_THD=8
#   bypass_thd16  : LIVENESS_BYPASS=1, BYPASS_THD=16
#   bypass_thd32  : LIVENESS_BYPASS=1, BYPASS_THD=32
#
# DPC3 uses trace-files/dpc3_llc_pressured/ (35 high-LLC-pressure traces).
# All runs: SCORING_MODE=3, THD_DEAD=2, THD_DOA=4, champsim_srrip_live_hrp.
BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="bypass_allsuites_${DATE}"

COMMON="BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,SCORING_MODE=5,THD_DEAD=10,THD_DOA=6"

total=0

submit() {
  local label="$1" binary="$2" jobname="$3" n="$4" traces="$5" ext="$6"; shift 6
  local extra="${*:+,$*}"   # ",extra_vars" if any; empty string if none
  mkdir -p "$BASE/results/$label" "$BASE/logs/$LABEL"
  local raw
  raw=$(qsub -t "1-${n}" -N "${jobname}" \
       -o "$BASE/logs/$LABEL/" -e "$BASE/logs/$LABEL/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "$BASE" \
       -v WARMUP=$W,SIM=$S,TRACE_DIR="${traces}",TRACE_EXT="${ext}",\
RUN_LABEL="${label}",BINARY="${binary}""${extra}" \
       "$BASE/scripts/submit/run_cs.sh")
  local jid
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=$jid n=$n] $label"
  total=$((total + n))
}

# Suite definitions: name traces ext n
declare -a SUITES=(
  "qmm    $BASE/trace-files/QMM                    champsimtrace.xz 45"
  "dpc3   $BASE/trace-files/dpc3_llc_pressured     champsimtrace.xz 35"
  "gap    $BASE/trace-files/gap                    trace.gz          9"
  "gms    $BASE/trace-files/gms                    champsimtrace.gz 11"
  "ligra  $BASE/trace-files/ligra                  champsimtrace.xz 18"
  "ml     $BASE/trace-files/ml                     champsimtrace.gz 31"
)

echo "=== Bypass threshold sweep — all 6 suites ==="
echo "Label: $LABEL"
echo ""

for entry in "${SUITES[@]}"; do
  read -r suite traces ext n <<< "$entry"

  echo "--- $suite ($n traces) ---"

  submit "$LABEL/${suite}/srrip"       champsim_srrip_live_hrp "bp_srrip"  $n "$traces" "$ext"
  submit "$LABEL/${suite}/repl_only"   champsim_srrip_live_hrp "bp_repl"   $n "$traces" "$ext" \
    "$COMMON"
  submit "$LABEL/${suite}/bypass_thd4" champsim_srrip_live_hrp "bp_t4"     $n "$traces" "$ext" \
    "$COMMON,LIVENESS_BYPASS=1,BYPASS_THD=4"
  submit "$LABEL/${suite}/bypass_thd8" champsim_srrip_live_hrp "bp_t8"     $n "$traces" "$ext" \
    "$COMMON,LIVENESS_BYPASS=1,BYPASS_THD=8"
  submit "$LABEL/${suite}/bypass_thd16" champsim_srrip_live_hrp "bp_t16"   $n "$traces" "$ext" \
    "$COMMON,LIVENESS_BYPASS=1,BYPASS_THD=16"
  submit "$LABEL/${suite}/bypass_thd32" champsim_srrip_live_hrp "bp_t32"   $n "$traces" "$ext" \
    "$COMMON,LIVENESS_BYPASS=1,BYPASS_THD=32"
  echo ""
done

echo "Total tasks submitted: $total"
echo "Results: $BASE/results/$LABEL/"
