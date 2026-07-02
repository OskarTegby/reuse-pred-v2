#!/bin/bash
set -euo pipefail
# Duel signal quality study: 32 vs 64 samplers, with/without hysteresis.
# All three policies at theta=6, all 7 suites.
# Run BEFORE threshold sweeps — determines best duel config to use for those.
#
# Arms per policy (3 new variants; baseline d32_h0 already exists):
#   d64_h0   : 64 samplers, no hysteresis
#   d32_hyst : 32 samplers, DUEL_HYST (250000 latency / 50 PSEL)
#   d64_hyst : 64 samplers, DUEL_HYST
#
# Policies:
#   SRRIP-Live: hit-count duel (champsim_srrip_live), cfgA=ins2/hit2 vs cfgB=ins3/hit0
#   LRU-Live:   latency duel  (champsim_lru_live),   cfgA=2n3 vs cfgB=lru
#   IPV-Live:   latency duel  (champsim_ipv_live),   cfgA={0,1,2,2,2} vs ilB={0,1,2,2,3}
#
# Note: DUEL_HYST has different scales per metric:
#   latency metric (LRU/IPV): 250000 (cycles)
#   hit-count/PSEL (SRRIP):   50 (PSEL units, range 0-1023)

BASE=/home/users/otegby/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL="duel_signal_quality_${DATE}"

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

submit() {
  local label="$1" bin="$2" jobname="$3" n="$4" tdir="$5" ext="$6" extra="$7"
  mkdir -p "${BASE}/results/${label}" "${BASE}/logs/${label}"
  local jid
  jid=$(qsub -t "1-${n}" -N "${jobname}" \
       -o "${BASE}/logs/${label}/" -e "${BASE}/logs/${label}/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "${BASE}" \
       -v "WARMUP=${W},SIM=${S},TRACE_DIR=${tdir},TRACE_EXT=${ext},RUN_LABEL=${label},BINARY=${bin},${extra}" \
       "${BASE}/scripts/submit/run_cs.sh" \
    | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${label} (${n} tasks)"
}

echo "=== Duel signal quality study: 32 vs 64 samplers, with/without hysteresis ==="
echo "Label: ${LABEL}"
echo ""

for suite_spec in "${SUITES[@]}"; do
  IFS=: read -r suite tdir ext n <<< "${suite_spec}"
  dead="${THD_DEAD[$suite]}"
  s="${suite:0:2}"
  base_env="SCORING_MODE=5,THD_DOA=6,THD_DEAD=${dead},BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc"
  echo "--- ${suite} ---"

  # SRRIP-Live: hit-count duel, cfgA=ins2/hit2 vs cfgB=ins3/hit0
  SL_DUEL="SRRIP_DOA_INS_RRPV=2,SRRIP_DOA_HIT_RRPV=2,SRRIP_DOA_INS_RRPV_B=3,SRRIP_DOA_HIT_RRPV_B=0"
  submit "${LABEL}/srrip/d64_h0/${suite}"   champsim_srrip_live "s64${s}"  "${n}" "${tdir}" "${ext}" "${base_env},${SL_DUEL},DUEL_N_SAMPLERS=64,DUEL_HYST=0"
  submit "${LABEL}/srrip/d32_hyst/${suite}" champsim_srrip_live "sh32${s}" "${n}" "${tdir}" "${ext}" "${base_env},${SL_DUEL},DUEL_N_SAMPLERS=32,DUEL_HYST=50"
  submit "${LABEL}/srrip/d64_hyst/${suite}" champsim_srrip_live "sh64${s}" "${n}" "${tdir}" "${ext}" "${base_env},${SL_DUEL},DUEL_N_SAMPLERS=64,DUEL_HYST=50"

  # LRU-Live: latency duel, cfgA=2n3 vs cfgB=lru
  LL_DUEL="LRU_LIVE_DOA_INS=2n3,LRU_LIVE_DOA_INS_B=lru,DUEL_METRIC=latency"
  submit "${LABEL}/lru/d64_h0/${suite}"     champsim_lru_live   "l64${s}"  "${n}" "${tdir}" "${ext}" "${base_env},${LL_DUEL},DUEL_N_SAMPLERS=64,DUEL_HYST=0"
  submit "${LABEL}/lru/d32_hyst/${suite}"   champsim_lru_live   "lh32${s}" "${n}" "${tdir}" "${ext}" "${base_env},${LL_DUEL},DUEL_N_SAMPLERS=32,DUEL_HYST=250000"
  submit "${LABEL}/lru/d64_hyst/${suite}"   champsim_lru_live   "lh64${s}" "${n}" "${tdir}" "${ext}" "${base_env},${LL_DUEL},DUEL_N_SAMPLERS=64,DUEL_HYST=250000"

  # IPV-Live: latency duel, cfgA={0,1,2,2,2} vs ilB={0,1,2,2,3}
  IPV_DUEL="DUEL_N_CONFIGS=2,IPV_DOA_0=0:1:2:2:2,IPV_DOA_1=0:1:2:2:3,IPV_MOSTLY_DEAD=0:1:1:2:2,DUEL_METRIC=latency"
  submit "${LABEL}/ipv/d64_h0/${suite}"     champsim_ipv_live   "i64${s}"  "${n}" "${tdir}" "${ext}" "${base_env},${IPV_DUEL},DUEL_N_SAMPLERS=64,DUEL_HYST=0"
  submit "${LABEL}/ipv/d32_hyst/${suite}"   champsim_ipv_live   "ih32${s}" "${n}" "${tdir}" "${ext}" "${base_env},${IPV_DUEL},DUEL_N_SAMPLERS=32,DUEL_HYST=250000"
  submit "${LABEL}/ipv/d64_hyst/${suite}"   champsim_ipv_live   "ih64${s}" "${n}" "${tdir}" "${ext}" "${base_env},${IPV_DUEL},DUEL_N_SAMPLERS=64,DUEL_HYST=250000"
done

echo ""
echo "Arrays: 9 arms * 7 suites = 63"
echo "Total tasks: 9 * (9+18+11+31+45+95+43) = 2268"
