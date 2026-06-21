#!/usr/bin/env bash
# qmm_buf_study.sh — promotion-buffer study for the LLC history table, QMM only.
#
# Tests whether a promotion buffer lets small tables (64–1024 entries) recover
# more of the unbounded speedup for QMM, where DoA traffic is spread across ~35K
# unique PCs and small tables currently under-perform.
#
# Policies: lfu_doa and tiered.
# Main caps: 64, 128, 256, 512, 1024.
# Buf caps: 0, 128, 256.
#   (tiered + buf=0 already exists in size_srrip_live_ext_20260619_1534; re-run
#    here for self-consistent comparison.)
# Fixed: SCORING_MODE=5, THD_DOA=6, THD_DEAD=10, BHIST_MODE=pc, SRRIP_LIVE_TARGET=llc
#
# Total: (2 policies × 3 buf vals × 5 caps) × 45 traces = 1350 jobs.
set -euo pipefail

BASE=~/ChampSim-dev
TRACES="${BASE}/trace-files/QMM"
EXT="champsimtrace.xz"
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="qmm_buf_study_${DATE}"
N=45

LIVE_BASE="SCORING_MODE=5,THD_DOA=6,THD_DEAD=10,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"

mkdir -p "${BASE}/logs/${LABEL}"
echo "=== QMM promotion-buffer study — label: ${LABEL} ==="

total=0
for policy in lfu_doa tiered; do
  for buf in 0 128 256; do
    for cap in 64 128 256 512 1024; do
      run="${LABEL}/${policy}_c${cap}_b${buf}"
      mkdir -p "${BASE}/results/${run}"
      jid=$(qsub -t "1-${N}" -N "buf_${policy:0:3}_${cap}_${buf}" \
        -o "${BASE}/logs/${LABEL}/" -e "${BASE}/logs/${LABEL}/" \
        -l h_rt=24:00:00 -l mem_free=4G -wd "${BASE}" \
        -v "WARMUP=${W},SIM=${S},TRACE_DIR=${TRACES},TRACE_EXT=${EXT},\
RUN_LABEL=${run},BINARY=champsim_srrip_live,\
${LIVE_BASE},REPL_HIST_LLC_CAP=${cap},REPL_HIST_BUF_CAP=${buf},REPL_HIST_REPL=${policy}" \
        "${BASE}/scripts/submit/run_cs.sh" \
        | awk '/Your job/ {print $3}' | cut -d. -f1)
      echo "  [jid=${jid}] ${policy} cap=${cap} buf=${buf}"
      total=$((total + N))
    done
  done
done

echo ""
echo "Total jobs submitted: ${total}"
echo "Label: ${LABEL}"
echo ""
echo "Analysis: scripts/analysis/plot_buf_study.py ${LABEL}"
