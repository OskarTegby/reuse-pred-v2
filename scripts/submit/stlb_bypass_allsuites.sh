#!/usr/bin/env bash
# stlb_bypass_allsuites.sh — LLC+STLB liveness bypass experiments.
#
# Compares our predictor in STLB-only and LLC+STLB modes against:
#   dppred_only    → stlb_bypass_only_thd16 (STLB bypass, no LLC bypass)
#   cbpred_dppred  → llc_stlb_bypass_thd16  (both LLC and STLB bypass)
#
# Env vars:
#   STLB_LIVENESS_BYPASS=1 : bypass DoA STLB fills using STLB's repl_hist_pc
#   STLB_BYPASS_THD        : DoA threshold for STLB (default=BYPASS_THD=thd_doa)
#   LIVENESS_BYPASS=1      : LLC bypass (already validated)
#   BYPASS_THD=16          : DoA threshold for LLC
#
# Baselines reused from bypass_allsuites_20260610_2312:
#   srrip, bypass_thd16 (LLC bypass only)
# Mazumdar comparison from maz_comparison_20260611_1655:
#   dppred_only, cbpred_dppred
set -euo pipefail

BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="stlb_bypass_allsuites_${DATE}"

# Common liveness settings (same as validated bypass runs)
COMMON="BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,SCORING_MODE=5,THD_DEAD=10,THD_DOA=6"

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

echo "=== STLB liveness bypass — all 6 suites ==="
echo "Label: $LABEL"
echo ""

for entry in "${SUITES[@]}"; do
  read -r suite traces ext n <<< "$entry"
  echo "--- $suite ($n traces) ---"

  # Config 1: STLB-only bypass (our equivalent of Mazumdar dppred_only)
  # LLC bypass disabled; only STLB bypass with THD=16
  submit "$LABEL/${suite}/stlb_bypass_only_thd16" champsim_srrip_live_hrp "sb_stlb" \
    $n "$traces" "$ext" \
    "$COMMON,STLB_LIVENESS_BYPASS=1,STLB_BYPASS_THD=16"

  # Config 2: LLC+STLB bypass (our equivalent of Mazumdar cbpred_dppred)
  # Both LLC bypass (THD=16) and STLB bypass (THD=16)
  submit "$LABEL/${suite}/llc_stlb_bypass_thd16" champsim_srrip_live_hrp "sb_both" \
    $n "$traces" "$ext" \
    "$COMMON,LIVENESS_BYPASS=1,BYPASS_THD=16,STLB_LIVENESS_BYPASS=1,STLB_BYPASS_THD=16"

  echo ""
done

echo "Total tasks submitted: $total"
echo "Arrays: 12 (2 configs × 6 suites)"
echo "Results: $BASE/results/$LABEL/"
echo ""
echo "Baselines for comparison:"
echo "  srrip:               bypass_allsuites_20260610_2312/{suite}/srrip"
echo "  LLC bypass only:     bypass_allsuites_20260610_2312/{suite}/bypass_thd16"
echo "  Mazumdar dppred:     maz_comparison_20260611_1655/{suite}/dppred_only"
echo "  Mazumdar cbpred+dp:  maz_comparison_20260611_1655/{suite}/cbpred_dppred"
