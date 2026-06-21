#!/usr/bin/env bash
# test_mode5_targeted.sh — Run mode3_decoup and mode5_recal on the most
# informative traces per suite (highest spread in overnight scoring mode sweep).
#
# Creates per-suite symlink directories containing only target traces, then
# submits normally with -t 1-N. Symlinks are cleaned up after submission.
#
# mode5 config: SCORING_MODE=5, THD_DEAD=10, THD_DOA=20
set -euo pipefail
BASE=~/ChampSim-dev
W=50000000; S=100000000
DATE=$(date +%Y%m%d_%H%M)
LABEL=mode5_targeted_${DATE}
SHARED=/home/users/shared/traces

declare -A TDIR EXT TARGET_NAMES
TDIR[dpc3]=$SHARED/dpc3_traces
TDIR[gap]=$BASE/trace-files/gap
TDIR[gms]=$BASE/trace-files/gms
TDIR[ligra]=$BASE/trace-files/ligra
TDIR[ml]=$BASE/trace-files/ml
TDIR[qmm]=$BASE/trace-files/QMM
EXT[dpc3]="champsimtrace.xz"
EXT[gap]="trace.gz"
EXT[gms]="champsimtrace.gz"
EXT[ligra]="champsimtrace.xz"
EXT[ml]="champsimtrace.gz"
EXT[qmm]="champsimtrace.xz"

# High-spread trace names from overnight sweep analysis
TARGET_NAMES[dpc3]="605.mcf_s-1152B 605.mcf_s-665B 605.mcf_s-782B 605.mcf_s-994B 607.cactuBSSN_s-3477B 607.cactuBSSN_s-4004B 619.lbm_s-2676B 619.lbm_s-2677B 619.lbm_s-3766B 619.lbm_s-4268B"
TARGET_NAMES[gap]="bc-0 bc-12 cc-13 cc-14 cc-5"
TARGET_NAMES[gms]="gms.k_clique_list_danisch_edge_parallel.soc-pokec-relationships.slice-367 gms.k_clique_list_danisch_edge_parallel.soc-pokec-relationships.slice-80"
TARGET_NAMES[ligra]="ligra_BFSCC.com-lj.ungraph.gcc_6.3.0_O3.drop_17000M.length_250M ligra_Components-Shortcut.com-lj.ungraph.gcc_6.3.0_O3.drop_17000M.length_250M ligra_PageRank.com-lj.ungraph.gcc_6.3.0_O3.drop_51000M.length_250M ligra_PageRankDelta.com-lj.ungraph.gcc_6.3.0_O3.drop_17000M.length_250M"
TARGET_NAMES[ml]="bark.cpp-bark-small.coarse_token_gen.5 llama2.c-stories15M.2 llama2.c-stories15M.3 stable-diffusion.cpp-sd-v1-4.ckpt.1 stable-diffusion.cpp-v2-1_768-nonema-pruned.2 vit.cpp-large-ggml-model-f16.gguf.armadillo.1"
TARGET_NAMES[qmm]="srv_617 srv_669 srv_715 srv_73"

SYMLINK_BASE=$BASE/trace-files/targeted_${DATE}
total=0

echo "=== Mode5 targeted run — high-spread traces, 8h wall ==="
echo "Label: $LABEL"
echo ""

for suite in dpc3 gap gms ligra ml qmm; do
  ext="${EXT[$suite]}"
  symdir="$SYMLINK_BASE/$suite"
  mkdir -p "$symdir"

  # Create symlinks for target traces only
  for name in ${TARGET_NAMES[$suite]}; do
    src="${TDIR[$suite]}/${name}.${ext}"
    [ -f "$src" ] && ln -sf "$src" "$symdir/${name}.${ext}"
  done

  n=$(ls "$symdir"/*."$ext" 2>/dev/null | wc -l)
  [ "$n" -eq 0 ] && echo "  $suite: no traces found, skipping" && continue

  echo "--- $suite ($n traces) ---"

  for cfg in "mode3_decoup:SCORING_MODE=3,THD_DEAD=2,THD_DOA=4" \
             "mode5_recal:SCORING_MODE=5,THD_DEAD=10,THD_DOA=20"; do
    name="${cfg%%:*}"; extra="${cfg#*:}"
    runlabel="$LABEL/${suite}_${name}"
    mkdir -p "$BASE/results/$runlabel" "$BASE/logs/$LABEL"
    raw=$(qsub -t "1-${n}" \
               -N "${name:0:15}" \
               -o "$BASE/logs/$LABEL/" \
               -e "$BASE/logs/$LABEL/" \
               -l h_rt=8:00:00 \
               -l mem_free=1G \
               -wd "$BASE" \
               -v WARMUP=$W,SIM=$S,TRACE_DIR="$symdir",TRACE_EXT="$ext",\
RUN_LABEL="$runlabel",BINARY=champsim_srrip_live,\
BHIST_MODE=pc,SRRIP_LIVE_TARGET=llc,${extra} \
               "$BASE/scripts/submit/run_cs.sh")
    jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
    echo "  [jid=$jid]  ${suite}/${name}  (n=$n)"
    total=$((total + n))
  done
  echo ""
done

echo "Total tasks: $total"
echo "Results:     $BASE/results/$LABEL/"
echo "Symlinks:    $SYMLINK_BASE  (safe to remove after jobs complete)"
