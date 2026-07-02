#!/bin/bash
set -euo pipefail
# Rerun the paper's headline performance results (LRU/SRRIP baselines,
# LRU-Live, SRRIP-Live) on two alternative architecture configurations:
# AMD Zen4 and Intel Redwood Cove (see
# results/paper/ARCHITECTURE_CONFIGURATION.md for the cache/TLB geometries
# and rationale).
#
# No threshold sweep here: every value below is the already-established
# best-performing config, reused as-is. Both guided policies use set
# dueling (not a fixed single arm) at the common THD_DOA=6 anchor, per
# scripts/submit/srrip_live_thd_duel.sh, lru_live_thd_duel.sh, and
# duel_signal_quality.sh:
#   - THD_DOA=6 fixed for BOTH policies, all suites (the per-suite optimal
#     THD_DOA table from the old non-dueling tab:llc_thd sweep is
#     superseded and NOT used here).
#   - THD_DEAD: same per-suite table for both policies (gap=4, ligra=16,
#     gms=4, ml=2, qmm=2, dpc3=4, google=8).
#   - LRU-Live duel:   latency metric, cfgA=2n3 vs cfgB=lru, 32 samplers
#                      (LRU_LIVE_DOA_INS=2n3, LRU_LIVE_DOA_INS_B=lru,
#                      DUEL_METRIC=latency, DUEL_N_SAMPLERS=32).
#   - SRRIP-Live duel: hit-count/PSEL metric, cfgA=ins2/hit2 vs
#                      cfgB=ins3/hit0, 32 samplers (SRRIP_DOA_INS_RRPV=2,
#                      SRRIP_DOA_HIT_RRPV=2, SRRIP_DOA_INS_RRPV_B=3,
#                      SRRIP_DOA_HIT_RRPV_B=0, DUEL_N_SAMPLERS=32).
#
# Binaries: champsim_{lru,srrip,lru_live,srrip_live}_{zen4,redwoodcove},
# built locally from champsim_config_zen4.json / champsim_config_redwoodcove.json
# and copied to bin/ on the cluster (never built on the cluster). Set
# dueling is selected entirely via env vars at runtime (verified with a
# local smoke test against both duel arms before submitting), so no
# separate duel binary is needed.

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="arch_rerun_zen4_redwoodcove_${DATE}"

ARCHS=(zen4 redwoodcove)

declare -A THD_DEAD=([gap]=4 [ligra]=16 [gms]=4 [ml]=2 [qmm]=2 [dpc3]=4 [google]=8)

LRU_LIVE_DUEL="LRU_LIVE_DOA_INS=2n3,LRU_LIVE_DOA_INS_B=lru,DUEL_METRIC=latency,DUEL_N_SAMPLERS=32"
SRRIP_LIVE_DUEL="SRRIP_DOA_INS_RRPV=2,SRRIP_DOA_HIT_RRPV=2,SRRIP_DOA_INS_RRPV_B=3,SRRIP_DOA_HIT_RRPV_B=0,DUEL_N_SAMPLERS=32"

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

echo "=== Architecture rerun: Zen4 + Redwood Cove ==="
echo "Label: ${LABEL}"
echo ""

for arch in "${ARCHS[@]}"; do
  a="${arch:0:2}"
  echo "##### Arch: ${arch} #####"

  echo "--- Baselines ---"
  for suite_spec in "${SUITES[@]}"; do
    IFS=: read -r suite tdir ext n <<< "${suite_spec}"
    s="${suite:0:2}"
    submit "${LABEL}/${arch}/lru/${suite}"   "b${a}L${s}" "${n}" "${tdir}" "${ext}" "champsim_lru_${arch}"   ""
    submit "${LABEL}/${arch}/srrip/${suite}" "b${a}S${s}" "${n}" "${tdir}" "${ext}" "champsim_srrip_${arch}" ""
  done

  echo "--- LRU-Live (THD_DOA=6, per-suite THD_DEAD, set dueling: latency, 2n3 vs lru) ---"
  for suite_spec in "${SUITES[@]}"; do
    IFS=: read -r suite tdir ext n <<< "${suite_spec}"
    s="${suite:0:2}"
    dead="${THD_DEAD[$suite]}"
    env="SCORING_MODE=5,THD_DOA=6,THD_DEAD=${dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,${LRU_LIVE_DUEL}"
    submit "${LABEL}/${arch}/lru_live/${suite}" "l${a}L${s}" "${n}" "${tdir}" "${ext}" "champsim_lru_live_${arch}" "${env}"
  done

  echo "--- SRRIP-Live (THD_DOA=6, per-suite THD_DEAD, set dueling: hit-count, ins2/hit2 vs ins3/hit0) ---"
  for suite_spec in "${SUITES[@]}"; do
    IFS=: read -r suite tdir ext n <<< "${suite_spec}"
    s="${suite:0:2}"
    dead="${THD_DEAD[$suite]}"
    env="SCORING_MODE=5,THD_DOA=6,THD_DEAD=${dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,${SRRIP_LIVE_DUEL}"
    submit "${LABEL}/${arch}/srrip_live/${suite}" "s${a}L${s}" "${n}" "${tdir}" "${ext}" "champsim_srrip_live_${arch}" "${env}"
  done
  echo ""
done

echo "Arrays: 2 archs * 4 policies * 7 suites = 56"
echo "Total tasks: 2 * 4 * (9+18+11+31+45+95+43) = 2 * 4 * 252 = 2016"
