#!/bin/bash
set -euo pipefail
# Check whether the LRU-Live per-suite threshold relationship established on
# the original architecture still holds on Redwood Cove, using a 2-point
# subset (THD_DOA=2 and THD_DOA=30, the extremes of the original 8-point
# sweep) instead of a full re-sweep. On the original config these two values
# bracket the clearest per-suite separation: GAP/Ligra prefer the low end,
# Google/ML/GMS/SPEC prefer the high end, QMM is roughly flat. If that
# low-vs-high ranking is unchanged here, the established threshold choice
# generalizes; if it flips for any suite, run the fuller sweep for that one.
#
# Everything else matches arch_rerun_zen4_redwoodcove.sh exactly (per-suite
# THD_DEAD, set dueling at latency metric, 2n3 vs lru, 32 samplers) --
# only THD_DOA and the arch/policy scope differ.

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="arch_rerun_lru_live_thd_subset_${DATE}"

ARCH=redwoodcove
THDS=(2 30)

declare -A THD_DEAD=([gap]=4 [ligra]=16 [gms]=4 [ml]=2 [qmm]=2 [dpc3]=4 [google]=8)

LRU_LIVE_DUEL="LRU_LIVE_DOA_INS=2n3,LRU_LIVE_DOA_INS_B=lru,DUEL_METRIC=latency,DUEL_N_SAMPLERS=32"

SUITES=(
  "gap:trace-files/gap:trace.gz:9"
  "ligra:trace-files/ligra:champsimtrace.xz:18"
  "gms:trace-files/gms:champsimtrace.gz:11"
  "ml:trace-files/ml:champsimtrace.gz:31"
  "qmm:trace-files/QMM:champsimtrace.xz:45"
  "dpc3:/home/users/shared/traces/dpc3_traces:champsimtrace.xz:95"
  "google:/home/users/shared/traces/Google_Traces_v2:champsim.gz:43"
)

submit() {
  local label="$1" jobname="$2" n="$3" tdir="$4" ext="$5" binary="$6" extra="$7"
  mkdir -p "${BASE}/results/${label}" "${BASE}/logs/${label}"
  local jid
  jid=$(qsub -t "1-${n}" -N "${jobname}" \
       -o "${BASE}/logs/${label}/" -e "${BASE}/logs/${label}/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "${BASE}" \
       -v "WARMUP=${W},SIM=${S},TRACE_DIR=${tdir},TRACE_EXT=${ext},RUN_LABEL=${label},BINARY=${binary}${extra:+,${extra}}" \
       "${BASE}/scripts/submit/run_cs.sh" \
    | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${label} (${n} tasks, bin=${binary})"
}

echo "=== LRU-Live threshold-relationship subset check: ${ARCH}, THD_DOA={${THDS[*]}} ==="
echo "Label: ${LABEL}"
echo ""

a="${ARCH:0:2}"
for thd in "${THDS[@]}"; do
  echo "--- THD_DOA=${thd} ---"
  for suite_spec in "${SUITES[@]}"; do
    IFS=: read -r suite tdir ext n <<< "${suite_spec}"
    s="${suite:0:2}"
    dead="${THD_DEAD[$suite]}"
    env="SCORING_MODE=5,THD_DOA=${thd},THD_DEAD=${dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,${LRU_LIVE_DUEL}"
    submit "${LABEL}/${ARCH}/lru_live/doa${thd}/${suite}" "t${a}${thd}${s}" "${n}" "${tdir}" "${ext}" "champsim_lru_live_${ARCH}" "${env}"
  done
done

echo ""
echo "Arrays: 1 arch * 2 thresholds * 7 suites = 14"
echo "Total tasks: 2 * (9+18+11+31+45+95+43) = 2 * 252 = 504"
