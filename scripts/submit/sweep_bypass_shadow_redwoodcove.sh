#!/usr/bin/env bash
set -euo pipefail
# sweep_bypass_shadow_redwoodcove.sh — LLC bypass-shadow (victim cache) size sweep,
# corrected rerun under Redwood Cove with the CURRENT scoring system.
#
# Supersedes shadow_allsuites_20260613_0928, which used the deprecated MID_THD-based
# 3-way mostly-dead/mostly-alive/DoA classification (deleted in commit 6b344a582826,
# 2026-07-08) instead of the current flat THD_DOA scoring system, and predates the
# 2026-07-10 established-theta correction. That "no size trend, neutral" finding was
# drawn on infrastructure that no longer exists -- this rerun is the honest version.
#
# binary: champsim_lru_redwoodcove (plain LRU replacement; bypass/shadow logic in
# cache.cc is independent of replacement policy, so this isolates the bypass+shadow
# effect cleanly, matching the established "bypass-only" methodology in FINDINGS.md).
#
# Arms per suite:
#   bypass_noshadow      : LIVENESS_BYPASS=1, BYPASS_THD=<established theta>, no shadow
#   shadow4/8/16/32/64/128/256 : same + LLC_BYPASS_SHADOW_SIZE=<N>
# "base" (no bypass at all) is NOT resubmitted -- reused as-is from
# results/arch_rerun_zen4_redwoodcove_20260702_2100/redwoodcove/lru (plain LRU never
# reads LIVENESS_BYPASS-gated code, so it's byte-identical regardless of build date).

BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="bypass_shadow_redwoodcove_${DATE}"
BINARY=champsim_lru_redwoodcove_bypass

total=0

submit() {
  local label="$1" jobname="$2" n="$3" traces="$4" ext="$5"; shift 5
  local extra="${*:+,$*}"
  mkdir -p "$BASE/results/$label" "$BASE/logs/$LABEL"
  local raw
  raw=$(qsub -t "1-${n}" -N "${jobname}" \
       -o "$BASE/logs/$LABEL/" -e "$BASE/logs/$LABEL/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "$BASE" \
       -v WARMUP=$W,SIM=$S,TRACE_DIR="${traces}",TRACE_EXT="${ext}",\
RUN_LABEL="${label}",BINARY="${BINARY}""${extra}" \
       "$BASE/scripts/submit/run_cs.sh")
  local jid
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=$jid n=$n] $label"
  total=$((total + n))
}

# suite  traces  ext  n  established_theta (corrected 2026-07-10)
declare -a SUITES=(
  "dpc3   /home/users/shared/traces/dpc3_traces         champsimtrace.xz 95 1"
  "gap    $BASE/trace-files/gap                          trace.gz          9 1"
  "gms    $BASE/trace-files/gms                          champsimtrace.gz 11 6"
  "google /home/users/shared/traces/Google_Traces_v2     champsim.gz      43 6"
  "ligra  $BASE/trace-files/ligra                        champsimtrace.xz 17 1"
  "ml     $BASE/trace-files/ml                           champsimtrace.gz 31 6"
  "qmm    $BASE/trace-files/QMM                          champsimtrace.xz 45 2"
)

echo "=== LLC bypass-shadow (victim cache) size sweep — Redwood Cove, corrected theta ==="
echo "Label: $LABEL"
echo ""

for entry in "${SUITES[@]}"; do
  read -r suite traces ext n theta <<< "$entry"
  echo "--- $suite (n=$n, theta=$theta) ---"
  COMMON="BHIST_MODE=pc,THD_DOA=${theta},LIVENESS_BYPASS=1,BYPASS_THD=${theta}"

  submit "$LABEL/${suite}/bypass_noshadow" "bs_${suite}_ns" "$n" "$traces" "$ext" "$COMMON"
  for size in 4 8 16 32 64 128 256; do
    submit "$LABEL/${suite}/shadow${size}" "bs_${suite}_s${size}" "$n" "$traces" "$ext" \
      "$COMMON,LLC_BYPASS_SHADOW_SIZE=${size}"
  done
  echo ""
done

echo "Total tasks submitted: $total"
echo "Results: $BASE/results/$LABEL/"
echo "Baseline (no bypass) reused from: results/arch_rerun_zen4_redwoodcove_20260702_2100/redwoodcove/lru"
