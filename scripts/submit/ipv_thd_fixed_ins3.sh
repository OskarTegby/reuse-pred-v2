#!/bin/bash
set -euo pipefail
# IPV-Live FIXED-config DoA threshold sweep (ilB / ins@3).
# The remaining DoA-threshold study: LRU/SRRIP have a fixed THD_DOA sweep (phase2/3),
# IPV-Live never did. Single fixed insertion config (no dueling), swept over THD_DOA,
# all 7 suites — gives the fixed-vs-dueling contrast for IPV that we have for the others.
#
# Config: champsim_ipv_live_fixed, IPV_DOA=0:1:2:2:3 (ilB), MD=0:1:1:2:2,
# per-suite THD_DEAD UNCLAMPED (IPV convention, matches ipv_thd_sweep_v2).
# Includes doa6 (no fixed IPV anchor exists). Edit THDS to stage.
#   group 1: (2 4)     group 2: (6 8 16 20)     group 3: (25 30)
BASE=/home/users/otegby/ChampSim-dev
BIN=champsim_ipv_live_fixed
W=50000000; S=100000000
LABEL="ipv_thd_fixed_ins3_20260627"

THDS=(2 4)
declare -A THD_DEAD=([gap]=4 [ligra]=16 [gms]=4 [ml]=2 [qmm]=2 [dpc3]=4 [google]=8)

SUITES=(
  "gap:trace-files/gap:trace.gz:9"
  "ligra:trace-files/ligra:champsimtrace.xz:18"
  "gms:trace-files/gms:champsimtrace.gz:11"
  "ml:trace-files/ml:champsimtrace.gz:31"
  "qmm:trace-files/QMM:champsimtrace.xz:45"
  "dpc3:/home/users/shared/traces/dpc3_traces:champsimtrace.xz:95"
  "google:/home/users/shared/traces/Google_Traces_v2:champsim.gz:43"
)

INS3="IPV_DOA=0:1:2:2:3,IPV_MOSTLY_DEAD=0:1:1:2:2"

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

echo "=== IPV-Live fixed (ins@3) DoA threshold sweep ==="
echo "Label: ${LABEL}   thresholds: ${THDS[*]}"; echo ""
total=0
for T in "${THDS[@]}"; do
  echo "--- THD_DOA=${T} ---"
  for spec in "${SUITES[@]}"; do
    IFS=: read -r suite tdir ext n <<< "${spec}"
    dead="${THD_DEAD[$suite]}"
    env="SCORING_MODE=5,THD_DOA=${T},THD_DEAD=${dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,${INS3}"
    submit "${LABEL}/ins3/doa${T}/${suite}" "if${T}${suite:0:2}" "${n}" "${tdir}" "${ext}" "${env}"
    total=$((total+n))
  done
done
echo ""
echo "Total tasks: ${total}"
echo "Results: ${BASE}/results/${LABEL}/"
