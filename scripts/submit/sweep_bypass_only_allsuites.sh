#!/usr/bin/env bash
set -euo pipefail
# sweep_bypass_only_allsuites.sh — LLC bypass-only threshold sweep (no replacement guidance).
#
# Mirrors sweep_bypass_allsuites.sh but uses SRRIP_LIVE_TARGET=none so bypass
# decisions come from the PC history table alone, with no liveness-guided
# insertion RRPV.  Isolates the bypass contribution and lets us measure the
# synergy with replacement guidance from the combined sweep.
#
# Configs (4 per suite — srrip baseline reused from bypass_allsuites_20260610_2312):
#   bypass_only_thd4   : LIVENESS_BYPASS=1, BYPASS_THD=4,  no repl guidance
#   bypass_only_thd8   : LIVENESS_BYPASS=1, BYPASS_THD=8,  no repl guidance
#   bypass_only_thd16  : LIVENESS_BYPASS=1, BYPASS_THD=16, no repl guidance
#   bypass_only_thd32  : LIVENESS_BYPASS=1, BYPASS_THD=32, no repl guidance
#
# All runs: SCORING_MODE=5, THD_DEAD=10, THD_DOA=6, champsim_srrip_live_hrp.
BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="bypass_only_allsuites_${DATE}"

COMMON="BHIST_MODE=pc,SRRIP_LIVE_TARGET=none,SCORING_MODE=5,THD_DEAD=10,THD_DOA=6,LIVENESS_BYPASS=1"

total=0

submit() {
  local label="$1" binary="$2" jobname="$3" n="$4" traces="$5" ext="$6"; shift 6
  local extra="${*:+,$*}"
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

declare -a SUITES=(
  "qmm    $BASE/trace-files/QMM                    champsimtrace.xz 45"
  "dpc3   $BASE/trace-files/dpc3_llc_pressured     champsimtrace.xz 35"
  "gap    $BASE/trace-files/gap                    trace.gz          9"
  "gms    $BASE/trace-files/gms                    champsimtrace.gz 11"
  "ligra  $BASE/trace-files/ligra                  champsimtrace.xz 18"
  "ml     $BASE/trace-files/ml                     champsimtrace.gz 31"
)

echo "=== Bypass-only threshold sweep — all 6 suites ==="
echo "Label: $LABEL"
echo ""

for entry in "${SUITES[@]}"; do
  read -r suite traces ext n <<< "$entry"
  echo "--- $suite ($n traces) ---"
  submit "$LABEL/${suite}/bypass_only_thd4"  champsim_srrip_live_hrp "bo_t4"  $n "$traces" "$ext" \
    "$COMMON,BYPASS_THD=4"
  submit "$LABEL/${suite}/bypass_only_thd8"  champsim_srrip_live_hrp "bo_t8"  $n "$traces" "$ext" \
    "$COMMON,BYPASS_THD=8"
  submit "$LABEL/${suite}/bypass_only_thd16" champsim_srrip_live_hrp "bo_t16" $n "$traces" "$ext" \
    "$COMMON,BYPASS_THD=16"
  submit "$LABEL/${suite}/bypass_only_thd32" champsim_srrip_live_hrp "bo_t32" $n "$traces" "$ext" \
    "$COMMON,BYPASS_THD=32"
  echo ""
done

echo "Total tasks submitted: $total"
echo "Results: $BASE/results/$LABEL/"
