#!/usr/bin/env bash
set -euo pipefail
# sweep_size_allsuites.sh — History table size + replacement policy sweep.
#
# New suites: DPC3 (35 filtered), GAP (9), GMS (11), Ligra (18)
# ML completion: lfu_c4096, tier_c4096, ref only (rest already done in llc_size_ml_*)
# QMM: SKIP — already complete.
#
# 12 configs per new suite:
#   srrip        : plain SRRIP baseline (no liveness)
#   lfu_c256     : cap=256,  buf=64,   REPL_HIST_REPL=lfu_doa
#   tier_c256    : cap=256,  buf=64,   REPL_HIST_REPL=tiered
#   lfu_c512     : cap=512,  buf=128,  REPL_HIST_REPL=lfu_doa
#   tier_c512    : cap=512,  buf=128,  REPL_HIST_REPL=tiered
#   lfu_c1024    : cap=1024, buf=256,  REPL_HIST_REPL=lfu_doa
#   tier_c1024   : cap=1024, buf=256,  REPL_HIST_REPL=tiered
#   lfu_c2048    : cap=2048, buf=512,  REPL_HIST_REPL=lfu_doa
#   tier_c2048   : cap=2048, buf=512,  REPL_HIST_REPL=tiered
#   lfu_c4096    : cap=4096, buf=1024, REPL_HIST_REPL=lfu_doa
#   tier_c4096   : cap=4096, buf=1024, REPL_HIST_REPL=tiered
#   ref          : unbounded (no REPL_HIST_LLC_CAP), LRU eviction
#
# All liveness configs: SCORING_MODE=3, THD_DEAD=2, THD_DOA=4, champsim_srrip_live_hrp.
BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="size_allsuites_${DATE}"

LIVE_BASE="BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,SCORING_MODE=5,THD_DEAD=10,THD_DOA=6"

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

run_suite() {
  local suite="$1" traces="$2" ext="$3" n="$4"
  echo "--- $suite ($n traces) ---"

  # Baseline: plain SRRIP (no liveness)
  submit "$LABEL/${suite}/srrip" champsim_srrip_live_hrp "sz_srrip" $n "$traces" "$ext"

  # Bounded liveness: LFU-DoA and tiered at 5 cap sizes
  for cap in 256 512 1024 2048 4096; do
    local buf=$((cap / 4))
    submit "$LABEL/${suite}/lfu_c${cap}"  champsim_srrip_live_hrp "sz_lf${cap}" $n "$traces" "$ext" \
      "$LIVE_BASE,REPL_HIST_LLC_CAP=${cap},REPL_HIST_BUF_CAP=${buf},REPL_HIST_REPL=lfu_doa"
    submit "$LABEL/${suite}/tier_c${cap}" champsim_srrip_live_hrp "sz_ti${cap}" $n "$traces" "$ext" \
      "$LIVE_BASE,REPL_HIST_LLC_CAP=${cap},REPL_HIST_BUF_CAP=${buf},REPL_HIST_REPL=tiered"
  done

  # Unbounded reference
  submit "$LABEL/${suite}/ref" champsim_srrip_live_hrp "sz_ref" $n "$traces" "$ext" \
    "$LIVE_BASE"
  echo ""
}

echo "=== History table size + replacement policy sweep ==="
echo "Label: $LABEL"
echo ""

# New suites (full 12-config sweep)
run_suite "dpc3"  "$BASE/trace-files/dpc3_llc_pressured" "champsimtrace.xz" 35
run_suite "gap"   "$BASE/trace-files/gap"                "trace.gz"          9
run_suite "gms"   "$BASE/trace-files/gms"                "champsimtrace.gz" 11
run_suite "ligra" "$BASE/trace-files/ligra"              "champsimtrace.xz" 18

# ML: only the 3 cancelled configs
echo "--- ml (31 traces) — completion only (lfu_c4096, tier_c4096, ref) ---"
ML_TRACES="$BASE/trace-files/ml"; ML_EXT="champsimtrace.gz"; ML_N=31
submit "$LABEL/ml/lfu_c4096"  champsim_srrip_live_hrp "sz_lf4096" $ML_N "$ML_TRACES" "$ML_EXT" \
  "$LIVE_BASE,REPL_HIST_LLC_CAP=4096,REPL_HIST_BUF_CAP=1024,REPL_HIST_REPL=lfu_doa"
submit "$LABEL/ml/tier_c4096" champsim_srrip_live_hrp "sz_ti4096" $ML_N "$ML_TRACES" "$ML_EXT" \
  "$LIVE_BASE,REPL_HIST_LLC_CAP=4096,REPL_HIST_BUF_CAP=1024,REPL_HIST_REPL=tiered"
submit "$LABEL/ml/ref"        champsim_srrip_live_hrp "sz_ref"    $ML_N "$ML_TRACES" "$ML_EXT" \
  "$LIVE_BASE"
echo ""

echo "Total tasks submitted: $total"
echo "Results: $BASE/results/$LABEL/"
echo ""
echo "NOTE: Point ML size analysis at both:"
echo "  - Prior ML results: results/llc_size_ml_20260610_*/"
echo "  - New ML configs:   results/$LABEL/ml/"
