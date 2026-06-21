#!/usr/bin/env bash
# sweep_doa_threshold.sh — DoA threshold sensitivity study.
#
# Sweeps THD_DOA ∈ {2, 4, 6, 8, 12, 20} with THD_DEAD fixed at 10.
# Uses the calibrated SCORING_MODE=5 (falling 5/3/1), BHIST_MODE=pc,
# unbounded history table (no REPL_HIST_LLC_CAP) to isolate threshold effect.
# Baseline SRRIP already in bypass_allsuites_20260610_2312/{suite}/srrip/.
#
# Suites: dpc3 (95), gap (9), gms (11), ligra (18), ml (31), qmm (45)
# Thresholds: 6 values × 209 traces = 1254 jobs

set -euo pipefail
BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
SHARED=/home/users/shared/traces
LIVE_BASE="SCORING_MODE=5,THD_DEAD=10,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"

declare -A TRACES EXT N
TRACES=([dpc3]="${SHARED}/dpc3_traces" [gap]="${BASE}/trace-files/gap"
        [gms]="${BASE}/trace-files/gms" [ligra]="${BASE}/trace-files/ligra"
        [ml]="${BASE}/trace-files/ml"   [qmm]="${BASE}/trace-files/QMM")
EXT=([dpc3]="champsimtrace.xz" [gap]="trace.gz" [gms]="champsimtrace.gz"
     [ligra]="champsimtrace.xz" [ml]="champsimtrace.gz" [qmm]="champsimtrace.xz")
N=([dpc3]=95 [gap]=9 [gms]=11 [ligra]=17 [ml]=31 [qmm]=45)

THD_DOA_VALUES=(2 4 6 8 12 20)
total=0

echo "=== DoA threshold sweep — 6 thresholds × 6 suites, unbounded ==="
echo "Date label: ${DATE}"

for suite in dpc3 gap gms ligra ml qmm; do
  echo "--- ${suite} ---"
  n="${N[$suite]}"
  for thd in "${THD_DOA_VALUES[@]}"; do
    runlabel="${suite}_thd_sweep_${DATE}/thd${thd}"
    mkdir -p "${BASE}/results/${runlabel}" "${BASE}/logs/${suite}_thd_sweep_${DATE}"
    jid=$(qsub -t "1-${n}" -N "ts_${suite:0:3}_t${thd}" \
      -o "${BASE}/logs/${suite}_thd_sweep_${DATE}/" \
      -e "${BASE}/logs/${suite}_thd_sweep_${DATE}/" \
      -l h_rt=24:00:00 -l mem_free=4G -wd "${BASE}" \
      -v "WARMUP=${W},SIM=${S},TRACE_DIR=${TRACES[$suite]},TRACE_EXT=${EXT[$suite]},\
RUN_LABEL=${runlabel},BINARY=champsim_srrip_live,${LIVE_BASE},THD_DOA=${thd}" \
      "${BASE}/scripts/submit/run_cs.sh" \
      | awk '/Your job/ {print $3}' | cut -d. -f1)
    echo "  [jid=${jid}] ${runlabel}  (n=${n})"
    total=$((total + n))
  done
done

echo ""
echo "Total jobs: ${total}"
echo "Label prefix: {suite}_thd_sweep_${DATE}/thd{N}/"
