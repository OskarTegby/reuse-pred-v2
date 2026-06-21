#!/usr/bin/env bash
# qmm_hash_sweep.sh — PC key hash sweep for bounded repl_hist_pc on QMM.
#
# Motivation: QMM has ~35K unique DoA-generating PCs; even cap=4096 covers only
# ~12% of them, so the unbounded table outperforms any bounded config.  XOR-folding
# the PC to N bits reduces the effective key space to 2^N, letting a cap=2^N table
# reach "full coverage" at the cost of aliasing between PCs that collide.
#
# Configs (all use SCORING_MODE=5, THD_DOA=6, THD_DEAD=10, REPL_HIST_REPL=tiered):
#   h10_c{256,512,1024}    — REPL_HIST_HASH_BITS=10 (1024 slots), cap varies
#   h11_c{512,1024,2048}   — REPL_HIST_HASH_BITS=11 (2048 slots), cap varies
#   h12_c{1024,2048,4096}  — REPL_HIST_HASH_BITS=12 (4096 slots), cap varies
#
# Compare against: allsuites_thd_phase2_*/qmm/tier_c* (no-hash baseline).

set -euo pipefail
BASE=~/ChampSim-dev
W=50000000; S=100000000
LABEL="qmm_hash_sweep_$(date +%Y%m%d_%H%M)"
TRACES="${BASE}/trace-files/QMM"
EXT="champsimtrace.xz"
N=$(find "$TRACES" -name "*.${EXT}" | wc -l)
BINARY="champsim_srrip_live_hash"
SHARED_VARS="SCORING_MODE=5,THD_DOA=6,THD_DEAD=10,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,REPL_HIST_REPL=tiered"

mkdir -p "${BASE}/logs/${LABEL}"
echo "Label  : ${LABEL}"
echo "Binary : ${BINARY}"
echo "Traces : ${N}  (QMM)"
echo ""

submit() {
  local name="$1" cap="$2" bits="$3"
  mkdir -p "${BASE}/results/${LABEL}/${name}"
  jid=$(qsub -t "1-${N}" -N "hsh_${name}" \
    -o "${BASE}/logs/${LABEL}/" -e "${BASE}/logs/${LABEL}/" \
    -l h_rt=24:00:00 -l mem_free=4G -wd "${BASE}" \
    -v "WARMUP=${W},SIM=${S},TRACE_DIR=${TRACES},TRACE_EXT=${EXT},\
RUN_LABEL=${LABEL}/${name},BINARY=${BINARY},\
${SHARED_VARS},REPL_HIST_LLC_CAP=${cap},REPL_HIST_HASH_BITS=${bits}" \
    "${BASE}/scripts/submit/run_cs.sh" \
    | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${name}  (hash_bits=${bits} cap=${cap})"
}

echo "--- hash_bits=10 (1024 effective slots) ---"
submit "h10_c256"  256  10
submit "h10_c512"  512  10
submit "h10_c1024" 1024 10

echo ""
echo "--- hash_bits=11 (2048 effective slots) ---"
submit "h11_c512"  512  11
submit "h11_c1024" 1024 11
submit "h11_c2048" 2048 11

echo ""
echo "--- hash_bits=12 (4096 effective slots) ---"
submit "h12_c1024" 1024 12
submit "h12_c2048" 2048 12
submit "h12_c4096" 4096 12

total_tasks=$(( 9 * N ))
echo ""
echo "Total tasks submitted: ${total_tasks}  (9 configs × ${N} traces)"
echo "Results: ${BASE}/results/${LABEL}/"
echo "Logs   : ${BASE}/logs/${LABEL}/"
