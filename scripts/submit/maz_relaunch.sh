#!/usr/bin/env bash
# maz_relaunch.sh — re-submit missing traces from maz_comparison_20260611_1655.
#
# Original run had time-outs on heavy traces (lbm, Ligra, ML).
# This script re-uses the SAME RUN_LABEL so results land in the existing dirs.
# Only the missing (no IPC line) traces are re-submitted.
set -euo pipefail

BASE=~/ChampSim-dev
W=50000000; S=100000000
LAB="maz_comparison_20260611_1655"
BIN="champsim_srrip_live_hrp"

total=0

submit_filtered() {
  local suite=$1 cfg=$2 tdir=$3 ext=$4 filter=$5 expected_n=$6 extra="${7:-}"
  local label="$LAB/$suite/$cfg"

  # Validate that filter matches exactly expected_n traces
  local actual_n
  actual_n=$(find "$tdir" -name "*.${ext}" | sort | grep -cE "${filter}" || true)
  if [ "$actual_n" -ne "$expected_n" ]; then
    echo "  ERROR: $suite/$cfg filter matched $actual_n traces, expected $expected_n — SKIPPING"
    return
  fi

  mkdir -p "$BASE/results/$label" "$BASE/logs/$LAB"
  local extra_v=""
  [ -n "$extra" ] && extra_v=",${extra}"
  local raw
  raw=$(qsub -t "1-${expected_n}" -N "mrl_${suite:0:3}_${cfg:0:3}" \
       -o "$BASE/logs/$LAB/" -e "$BASE/logs/$LAB/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "$BASE" \
       -v WARMUP=${W},SIM=${S},TRACE_DIR="${tdir}",TRACE_EXT="${ext}",\
TRACE_FILTER="${filter}",RUN_LABEL="${label}",BINARY="${BIN}"${extra_v} \
       "$BASE/scripts/submit/run_cs.sh")
  local jid
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=$jid n=$expected_n] $suite/$cfg"
  total=$((total + expected_n))
}

echo "=== Mazumdar missing-trace relaunch ==="
echo "Label: $LAB"
echo ""

# --------------- DPC3 ---------------
echo "--- dpc3 ---"
submit_filtered dpc3 cbpred_dppred \
  "$BASE/trace-files/dpc3_llc_pressured" champsimtrace.xz \
  "(605\.mcf_s-1644B|619\.lbm_s-2677B|619\.lbm_s-4268B)" 3 "CBPRED=1,DPPRED=1"

submit_filtered dpc3 dppred_only \
  "$BASE/trace-files/dpc3_llc_pressured" champsimtrace.xz \
  "(605\.mcf_s-1644B|605\.mcf_s-782B|619\.lbm_s-2677B|619\.lbm_s-4268B)" 4 "DPPRED=1"

# --------------- GAP ---------------
echo "--- gap ---"
submit_filtered gap dppred_only \
  "$BASE/trace-files/gap" trace.gz \
  "bc-12" 1 "DPPRED=1"

# --------------- Ligra ---------------
echo "--- ligra ---"
# cbpred_dppred: 7 missing (unique drop values disambiguate)
LCBD="(ligra_BellmanFord.*22250|ligra_BFSCC.*15500|ligra_CF.*154750|ligra_Components-Shortcut.*17000|ligra_Components-Shortcut.*22000|ligra_PageRankDelta.*24000|ligra_Radii.*25000)"
submit_filtered ligra cbpred_dppred \
  "$BASE/trace-files/ligra" champsimtrace.xz \
  "$LCBD" 7 "CBPRED=1,DPPRED=1"

# dppred_only: 11 missing
LDPO="(ligra_BellmanFord.*22250|ligra_BFSCC.*17000|ligra_CF.*154750|ligra_Components-Shortcut.*17000|ligra_Components-Shortcut.*22000|ligra_MIS.*15750|ligra_PageRank\..*51000|ligra_PageRankDelta.*17000|ligra_PageRankDelta.*24000|ligra_Radii.*25000|ligra_Triangle.*25000)"
submit_filtered ligra dppred_only \
  "$BASE/trace-files/ligra" champsimtrace.xz \
  "$LDPO" 11 "DPPRED=1"

# --------------- ML ---------------
echo "--- ml ---"
# cbpred_dppred: 19 missing
# Missing: bark/coarse_token_gen.5; biogpt/tocilizumab.{1,2,3}; stories110M.{2,3};
# stories42M.{2,3}; rwkv_{2,3}; sd-v1-4.ckpt.{1,2}; v2-1_768.{1,2,3};
# vit/armadillo.1; whisper_trace_{1,2,3}
MCBD="(coarse_token_gen\.5\.|tocilizumab\.[123]\.|stories110M\.[23]\.|stories42M\.[23]\.|rwkv_trace_[23]\.|sd-v1-4\.ckpt\.[12]\.|v2-1_768-nonema-pruned\.[123]\.|large-ggml.*armadillo\.1\.|whisper_trace_[123]\.)"
submit_filtered ml cbpred_dppred \
  "$BASE/trace-files/ml" champsimtrace.gz \
  "$MCBD" 19 "CBPRED=1,DPPRED=1"

# dppred_only: 11 missing
# Missing: bark/coarse_token_gen.{1,2,4,5}; biogpt/tocilizumab.{1,2,3};
# clip_trace_{1,3}; stories110M.{1,2}
MDPO="(coarse_token_gen\.[1245]\.|tocilizumab\.[123]\.|clip_trace_[13]\.|stories110M\.[12]\.)"
submit_filtered ml dppred_only \
  "$BASE/trace-files/ml" champsimtrace.gz \
  "$MDPO" 11 "DPPRED=1"

echo ""
echo "Total tasks submitted: $total"
echo "Results appended to: $BASE/results/$LAB/"
