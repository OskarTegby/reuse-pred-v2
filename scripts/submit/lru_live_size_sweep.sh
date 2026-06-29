#!/bin/bash
set -euo pipefail
# LRU-Live history-table SIZE sweep, at a FIXED threshold (THD_DOA=16).
#
# Studies how the many-PC workloads (QMM, SPEC/dpc3, Google) degrade as the LLC
# history table is capacity-bounded below "fits all PCs", with TIERED eviction.
# Config is identical to the dueling threshold sweep at doa16 (so that study's
# UNBOUNDED point is this sweep's ceiling) — only REPL_HIST_LLC_CAP changes.
#
# Distinct-PC counts (from the unbounded threshold runs) set the upper ranges:
#   many-PC: google 140k, qmm 36k, dpc3 13k       -> up to 16384
#   few-PC : gap 529, gms 363, ml 356, ligra 276  -> up to 1024 (fits all)
# The low end (8..128) runs for ALL suites to capture degenerate-table behaviour.
#
# Staged (edit CAPS):
#   low : (8 16 32 64 128)  all suites
#   g1  : (256 512)  g2: (1024)  [all suites]
#   g3  : (2048 4096)  g4: (8192 16384)  [many-PC only]
BASE=/home/users/otegby/ChampSim-dev
BIN=champsim_lru_live
W=50000000; S=100000000
LABEL="lru_live_size_sweep_20260629"
THD_DOA=16
FEW_MAX_CAP=1024     # few-PC suites fit by 1024; skip larger caps for them

CAPS=(8 16 32 64 128)

declare -A DEAD=([gap]=4 [ligra]=16 [gms]=4 [ml]=2 [qmm]=2 [dpc3]=4 [google]=8)  # all <= 16, no clamp

# suite : trace_dir : ext : n_traces : group(many|few)
SUITES=(
  "dpc3:/home/users/shared/traces/dpc3_traces:champsimtrace.xz:95:many"
  "qmm:trace-files/QMM:champsimtrace.xz:45:many"
  "google:/home/users/shared/traces/Google_Traces_v2:champsim.gz:43:many"
  "gap:trace-files/gap:trace.gz:9:few"
  "gms:trace-files/gms:champsimtrace.gz:11:few"
  "ligra:trace-files/ligra:champsimtrace.xz:18:few"
  "ml:trace-files/ml:champsimtrace.gz:31:few"
)

DUEL="LRU_LIVE_DOA_INS=2n3,LRU_LIVE_DOA_INS_B=lru,DUEL_N_SAMPLERS=32,DUEL_METRIC=latency"

submit() {
  local label="$1" jobname="$2" n="$3" tdir="$4" ext="$5" extra="$6"
  mkdir -p "${BASE}/results/${label}" "${BASE}/logs/${label}"
  local jid
  jid=$(qsub -t "1-${n}" -N "${jobname}" \
       -o "${BASE}/logs/${label}/" -e "${BASE}/logs/${label}/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "${BASE}" \
       -v "WARMUP=${W},SIM=${S},TRACE_DIR=${tdir},TRACE_EXT=${ext},RUN_LABEL=${label},BINARY=${BIN},${extra}" \
       "${BASE}/scripts/submit/run_cs.sh" \
    | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${label} (${n} tasks)"
}

echo "=== LRU-Live history-table size sweep (THD_DOA=${THD_DOA}, tiered) ==="
echo "Label: ${LABEL}   caps: ${CAPS[*]}"; echo ""
total=0
for cap in "${CAPS[@]}"; do
  echo "--- REPL_HIST_LLC_CAP=${cap} ---"
  for spec in "${SUITES[@]}"; do
    IFS=: read -r suite tdir ext n grp <<< "${spec}"
    if [ "${grp}" = "few" ] && [ "${cap}" -gt "${FEW_MAX_CAP}" ]; then continue; fi
    dead="${DEAD[$suite]}"
    env="SCORING_MODE=5,THD_DOA=${THD_DOA},THD_DEAD=${dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,REPL_HIST_LLC_CAP=${cap},REPL_HIST_REPL=tiered,${DUEL}"
    submit "${LABEL}/size/cap${cap}/${suite}" "sz${cap}${suite:0:2}" "${n}" "${tdir}" "${ext}" "${env}"
    total=$((total+n))
  done
done
echo ""
echo "Total tasks this group: ${total}"
echo "Results: ${BASE}/results/${LABEL}/"
