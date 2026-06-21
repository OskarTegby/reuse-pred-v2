#!/usr/bin/env bash
# run_baselines_pristine.sh — regenerate the canonical baselines from PRISTINE code.
#
# Binaries champsim_{srrip,lru}_pristine are built from commit ec0e5c710fef
# (the parent of the first liveness change) at the paper cache geometry, static.
# They contain NO liveness instrumentation, so they are the true non-guided
# baselines. No env vars matter (the pristine binary ignores all of them).
#
# One array per (policy, suite). Output: baselines_pristine_<DATE>/<policy>/<suite>/<trace>/
# After completion, copy into results/baselines/{srrip,lru}/.

set -euo pipefail
BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
SHARED=/home/users/shared/traces

declare -A TRACES EXT N
TRACES=([dpc3]="${SHARED}/dpc3_traces" [gap]="trace-files/gap" [gms]="trace-files/gms"
        [google]="${SHARED}/Google_Traces_v2" [ligra]="trace-files/ligra"
        [ml]="trace-files/ml" [qmm]="trace-files/QMM")
EXT=([dpc3]="champsimtrace.xz" [gap]="trace.gz" [gms]="champsimtrace.gz"
     [google]="champsim.gz" [ligra]="champsimtrace.xz" [ml]="champsimtrace.gz"
     [qmm]="champsimtrace.xz")
N=([dpc3]=95 [gap]=9 [gms]=11 [google]=43 [ligra]=17 [ml]=31 [qmm]=45)

total=0
echo "=== Pristine baseline runs (srrip,lru) × 7 suites — label baselines_pristine_${DATE} ==="
for policy in srrip lru; do
  bin="champsim_${policy}_pristine"
  for suite in dpc3 gap gms google ligra ml qmm; do
    n="${N[$suite]}"
    runlabel="baselines_pristine_${DATE}/${policy}/${suite}"
    mkdir -p "${BASE}/results/${runlabel}" "${BASE}/logs/baselines_pristine_${DATE}"
    jid=$(qsub -t "1-${n}" -N "bl_${policy:0:3}_${suite:0:3}" \
      -o "${BASE}/logs/baselines_pristine_${DATE}/" \
      -e "${BASE}/logs/baselines_pristine_${DATE}/" \
      -l h_rt=24:00:00 -l mem_free=4G -wd "${BASE}" \
      -v "WARMUP=${W},SIM=${S},TRACE_DIR=${TRACES[$suite]},TRACE_EXT=${EXT[$suite]},RUN_LABEL=${runlabel},BINARY=${bin}" \
      "${BASE}/scripts/submit/run_cs.sh" \
      | awk '/Your job/ {print $3}' | cut -d. -f1)
    echo "  [jid=${jid}] ${runlabel}  (n=${n})"
    total=$((total + n))
  done
done
echo ""
echo "Total baseline jobs: ${total}"
echo "Label: baselines_pristine_${DATE}/{srrip,lru}/{suite}/"