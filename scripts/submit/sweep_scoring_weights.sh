#!/usr/bin/env bash
# sweep_scoring_weights.sh — Compare four scoring weight schemes at cap=256.
#
# All modes use Approach B decoupled (DoA→doa, MD→md+reset_doa, MA→reset both).
# The only thing that varies is the delta applied per observation as a function
# of the current state (MA / MD / DoA):
#
#   mode4_321  : SCORING_MODE=4  δ = 3/2/1 for MA/MD/DoA  (weaker falling)
#   mode5_531  : SCORING_MODE=5  δ = 5/3/1 for MA/MD/DoA  (falling, current best)
#   mode7_111  : SCORING_MODE=7  δ = 1/1/1 for MA/MD/DoA  (uniform)
#   mode8_135  : SCORING_MODE=8  δ = 1/3/5 for MA/MD/DoA  (rising, inverse of mode 5)
#
# Config: THD_DOA=6, THD_DEAD=10, BHIST_MODE=pc, SRRIP_LIVE_TARGET=llc,
#         REPL_HIST_LLC_CAP=256, REPL_HIST_REPL=tiered
#
# Suites: dpc3 (95), gap (9), gms (11), ligra (18), ml (31), qmm (45)
# Total : 4 modes x (95+9+11+18+31+45) = 4 x 209 = 836 jobs

set -euo pipefail
BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
SHARED=/home/users/shared/traces
LIVE_BASE="THD_DOA=6,THD_DEAD=10,BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,REPL_HIST_LLC_CAP=256,REPL_HIST_REPL=tiered"

declare -A TRACES EXT N
TRACES=([dpc3]="${SHARED}/dpc3_traces" [gap]="${BASE}/trace-files/gap"
        [gms]="${BASE}/trace-files/gms" [ligra]="${BASE}/trace-files/ligra"
        [ml]="${BASE}/trace-files/ml"   [qmm]="${BASE}/trace-files/QMM")
EXT=([dpc3]="champsimtrace.xz" [gap]="trace.gz" [gms]="champsimtrace.gz"
     [ligra]="champsimtrace.xz" [ml]="champsimtrace.gz" [qmm]="champsimtrace.xz")
N=([dpc3]=95 [gap]=9 [gms]=11 [ligra]=18 [ml]=31 [qmm]=45)

total=0

submit() {
  local suite="$1" mode_label="$2" job_name="$3" scoring_mode="$4"
  local n="${N[$suite]}"
  local runlabel="${suite}_scoring_weights_${DATE}/${mode_label}"
  mkdir -p "${BASE}/results/${runlabel}" "${BASE}/logs/${suite}_scoring_weights_${DATE}"
  local jid
  jid=$(qsub -t "1-${n}" -N "${job_name:0:15}" \
    -o "${BASE}/logs/${suite}_scoring_weights_${DATE}/" \
    -e "${BASE}/logs/${suite}_scoring_weights_${DATE}/" \
    -l h_rt=24:00:00 -l mem_free=4G -wd "${BASE}" \
    -v "WARMUP=${W},SIM=${S},TRACE_DIR=${TRACES[$suite]},TRACE_EXT=${EXT[$suite]},\
RUN_LABEL=${runlabel},BINARY=champsim_srrip_live,${LIVE_BASE},SCORING_MODE=${scoring_mode}" \
    "${BASE}/scripts/submit/run_cs.sh" \
    | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${runlabel}  (n=${n})"
  total=$((total + n))
}

echo "=== Scoring weight sweep — 4 modes x 6 suites, cap=256 ==="

for suite in dpc3 gap gms ligra ml qmm; do
  echo "--- ${suite} ---"
  submit "$suite" "mode4_321" "sw_${suite:0:3}_m4" 4
  submit "$suite" "mode5_531" "sw_${suite:0:3}_m5" 5
  submit "$suite" "mode7_111" "sw_${suite:0:3}_m7" 7
  submit "$suite" "mode8_135" "sw_${suite:0:3}_m8" 8
  echo ""
done

echo "Total jobs: ${total}"
echo "Label: {suite}_scoring_weights_${DATE}/{mode_label}/"
