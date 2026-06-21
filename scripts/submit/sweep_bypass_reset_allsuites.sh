#!/usr/bin/env bash
set -euo pipefail
# sweep_bypass_reset_allsuites.sh — BYPASS_FIRE_RESET_PERIOD sweep at THD=4.
#
# Motivation: aggressive bypass (THD=4) suffers lock-in on mixed workloads (QMM
# +0.42% vs +1.62% at THD=16). BYPASS_FIRE_RESET_PERIOD resets all repl_hist
# scores every N bypass fires, allowing mixed PCs to escape stale DoA labels.
#
# Re-accumulation cost at THD=4 (mode 5, δ=5 in MA state): 1 eviction suffices
# to re-cross THD=4. Streaming workloads (DPC3, Ligra) barely feel the resets.
#
# Baselines reused (no new srrip runs):
#   srrip           → bypass_allsuites_20260610_2312/{suite}/srrip
#   bypass_thd4     → bypass_allsuites_20260610_2312/{suite}/bypass_thd4
#   bypass_thd16    → bypass_allsuites_20260610_2312/{suite}/bypass_thd16
#
# New configs (all combined bypass+replacement, BYPASS_THD=4):
#   bypass_thd4_reset10k  : BYPASS_FIRE_RESET_PERIOD=10000
#   bypass_thd4_reset30k  : BYPASS_FIRE_RESET_PERIOD=30000
#   bypass_thd4_reset100k : BYPASS_FIRE_RESET_PERIOD=100000
#
# Expected counts per trace:
#   QMM (mean=155K bypasses): reset10k→~15, reset30k→~5, reset100k→~1.5 resets
#   DPC3 (mean=2.7M bypasses): reset10k→~270, reset30k→~90, reset100k→~27 resets
#   (All fast to re-accumulate at THD=4 — only 1 eviction needed per PC after reset)
#
# Verification: grep for "bypass_fire_reset: period=" in champsim.out to confirm
# env var took effect and see how many resets occurred.

BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="bypass_reset_sweep_${DATE}"

COMMON="BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,SCORING_MODE=5,THD_DEAD=10,THD_DOA=6,LIVENESS_BYPASS=1,BYPASS_THD=4"

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

echo "=== BYPASS_FIRE_RESET_PERIOD sweep — THD=4, all 6 suites ==="
echo "Label: $LABEL"
echo ""

for entry in "${SUITES[@]}"; do
  read -r suite traces ext n <<< "$entry"
  echo "--- $suite ($n traces) ---"

  submit "$LABEL/${suite}/bypass_thd4_reset10k" champsim_srrip_live_hrp "br_10k" \
    $n "$traces" "$ext" "$COMMON,BYPASS_FIRE_RESET_PERIOD=10000"
  submit "$LABEL/${suite}/bypass_thd4_reset30k" champsim_srrip_live_hrp "br_30k" \
    $n "$traces" "$ext" "$COMMON,BYPASS_FIRE_RESET_PERIOD=30000"
  submit "$LABEL/${suite}/bypass_thd4_reset100k" champsim_srrip_live_hrp "br_100k" \
    $n "$traces" "$ext" "$COMMON,BYPASS_FIRE_RESET_PERIOD=100000"
  echo ""
done

echo "Total tasks submitted: $total"
echo "Arrays: 18 (3 configs × 6 suites)"
echo "Results: $BASE/results/$LABEL/"
echo ""
echo "Baselines for comparison:"
echo "  srrip (no bypass):      bypass_allsuites_20260610_2312/{suite}/srrip"
echo "  bypass_thd4 (no reset): bypass_allsuites_20260610_2312/{suite}/bypass_thd4"
echo "  bypass_thd16:           bypass_allsuites_20260610_2312/{suite}/bypass_thd16"
