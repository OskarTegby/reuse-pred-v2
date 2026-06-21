#!/usr/bin/env bash
# test_hist_repl_full.sh — Compare hist table replacement policy variants on full
# LLC-pressured trace sets across all suites.
#
# DPC3 is filtered to traces with LLC load MPKI >= 5 (35 traces).
# Other suites use their complete trace directories.
# All runs use SCORING_MODE=3 to isolate replacement policy from scoring mode.
#
# Usage: $0 [cap]
#   cap : REPL_HIST_LLC_CAP (default 64)
set -euo pipefail

BASE=~/ChampSim-dev
SHARED=/home/users/shared/traces/dpc3_traces
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
CAP=${1:-64}
LABEL=hist_repl_full_cap${CAP}_${DATE}

# DPC3 LLC-pressured traces: MPKI >= 5 from thd_rebaseline LRU baseline
DPC3_NAMES=(
  603.bwaves_s-2609B   603.bwaves_s-1740B   603.bwaves_s-891B    603.bwaves_s-2931B
  605.mcf_s-1554B      605.mcf_s-782B        605.mcf_s-472B       605.mcf_s-1644B
  605.mcf_s-1536B      605.mcf_s-484B        605.mcf_s-1152B      605.mcf_s-994B
  605.mcf_s-665B
  607.cactuBSSN_s-2421B
  619.lbm_s-2677B      619.lbm_s-4268B       619.lbm_s-2676B      619.lbm_s-3766B
  620.omnetpp_s-141B   620.omnetpp_s-874B
  621.wrf_s-6673B
  623.xalancbmk_s-10B  623.xalancbmk_s-202B  623.xalancbmk_s-165B
  602.gcc_s-2226B      602.gcc_s-1850B        602.gcc_s-734B
  649.fotonik3d_s-7084B  649.fotonik3d_s-10881B  649.fotonik3d_s-8225B  649.fotonik3d_s-1176B
  654.roms_s-1390B     654.roms_s-523B        654.roms_s-1070B     654.roms_s-294B
)

# Build a symlink directory for the DPC3 subset (symlinks only, no data copied)
DPC3_DIR="$BASE/trace-files/dpc3_llc_pressured"
mkdir -p "$DPC3_DIR"
for name in "${DPC3_NAMES[@]}"; do
  src="$SHARED/${name}.champsimtrace.xz"
  dst="$DPC3_DIR/${name}.champsimtrace.xz"
  [ -L "$dst" ] || ln -s "$src" "$dst"
done

declare -A TRACE_DIR TRACE_EXT
TRACE_DIR[dpc3]="$DPC3_DIR"
TRACE_DIR[gap]="$BASE/trace-files/gap"
TRACE_DIR[gms]="$BASE/trace-files/gms"
TRACE_DIR[ligra]="$BASE/trace-files/ligra"
TRACE_DIR[qmm]="$BASE/trace-files/QMM"
TRACE_EXT[dpc3]="champsimtrace.xz"
TRACE_EXT[gap]="trace.gz"
TRACE_EXT[gms]="champsimtrace.gz"
TRACE_EXT[ligra]="champsimtrace.xz"
TRACE_EXT[qmm]="champsimtrace.xz"

total=0

echo "=== Hist table replacement policy — full LLC-pressured suite ==="
echo "Cap:   $CAP"
echo "Label: $LABEL"
echo ""

for suite in dpc3 gap gms ligra qmm; do
  dir="${TRACE_DIR[$suite]}"
  ext="${TRACE_EXT[$suite]}"
  n=$(ls "$dir"/*."$ext" 2>/dev/null | wc -l)
  [ "$n" -eq 0 ] && echo "  $suite: no traces in $dir, skipping" && continue

  echo "--- $suite ($n traces) ---"
  mkdir -p "$BASE/logs/$LABEL"

  for cfg in \
      "old_repl:champsim_srrip_live:" \
      "ma_neg2:champsim_srrip_live_hrp:-2" \
      "ma_neg1:champsim_srrip_live_hrp:-1" \
      "ma_0:champsim_srrip_live_hrp:0"; do
    name=$(echo "$cfg"   | cut -d: -f1)
    binary=$(echo "$cfg" | cut -d: -f2)
    ma_pen=$(echo "$cfg" | cut -d: -f3)

    ma_extra=""
    [[ -n "$ma_pen" ]] && ma_extra=",HIST_MA_PENALTY=${ma_pen}"

    runlabel="$LABEL/${suite}_${name}"
    mkdir -p "$BASE/results/$runlabel"
    raw=$(qsub -t "1-${n}" \
               -N "${name:0:15}" \
               -o "$BASE/logs/$LABEL/" \
               -e "$BASE/logs/$LABEL/" \
               -l h_rt=8:00:00 \
               -l mem_free=1G \
               -wd "$BASE" \
               -v WARMUP=$W,SIM=$S,TRACE_DIR="$dir",TRACE_EXT="$ext",\
RUN_LABEL="$runlabel",BINARY="$binary",\
BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,SCORING_MODE=3,THD_DEAD=2,THD_DOA=4,\
REPL_HIST_LLC_CAP=${CAP},REPL_HIST_REPL=lfu_doa${ma_extra} \
               "$BASE/scripts/submit/run_cs.sh")
    jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
    echo "  [jid=$jid]  ${suite}/${name}  (n=$n)"
    total=$((total + n))
  done
  echo ""
done

echo "Total tasks: $total"
echo "Results:     $BASE/results/$LABEL/"
