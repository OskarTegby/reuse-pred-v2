#!/usr/bin/env bash
# fetch_and_plot_20260511.sh — download all 2026-05-11 cluster results and run analysis.
#
# Downloads (or force-re-downloads if incomplete):
#   dpc3/google/qmm  _pol_20260511_1545
#   dpc3/google/qmm  _srrip_live_thd_20260511_2218
#   dpc3/google/qmm  _cache_size_20260511_2342
#
# Runs: plot_policy_comparison, plot_suite_comparison,
#       plot_srrip_live_thd, plot_cache_size_study

set -euo pipefail

LOG=/tmp/fetch_plot_20260511.log
REMOTE="otegby@abdet.inf.um.es"
CASTILLO="otegby@castillo.inf.um.es"
REMOTE_BASE="~/ChampSim-dev/results"
LOCAL_BASE="/home/otegby/repos/code/reuse-pred/results/cluster"
SCRIPTS="/home/otegby/repos/code/reuse-pred/scripts/analysis"
PROJECT="/home/otegby/repos/code/reuse-pred"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

fetch_dir() {
    local name="$1"
    local tarball="/tmp/cs_fetch_${name}.tar.gz"
    log "  fetching $name …"
    # tar on castillo → pipe through abdet → local: avoids per-file SSH overhead
    ssh -o BatchMode=yes "$REMOTE" \
        "ssh $CASTILLO 'tar czf - -C ~/ChampSim-dev/results $name'" \
        > "$tarball"
    mkdir -p "$LOCAL_BASE"
    tar xzf "$tarball" -C "$LOCAL_BASE"
    rm -f "$tarball"
    log "  done → results/cluster/$name"
}

run_plot() {
    log "  plot: $*"
    python3 "$@" >> "$LOG" 2>&1 && log "  ok" || log "  WARNING: plot exited non-zero"
}

log "=== fetch_and_plot_20260511 started ==="

# ── Download ──────────────────────────────────────────────────────────────────
# dpc3_pol is force-re-downloaded: local copy was partial (285 vs 760 remote files).
log "=== Downloading results ==="

FORCE_REDOWNLOAD=()
NEW_DIRS=(
    qmm_pol_20260511_1545
    dpc3_srrip_live_thd_20260511_2218
    google_srrip_live_thd_20260511_2218
    qmm_srrip_live_thd_20260511_2218
    dpc3_cache_size_20260511_2342
    google_cache_size_20260511_2342
    qmm_cache_size_20260511_2342
)

for d in "${FORCE_REDOWNLOAD[@]}"; do
    log "  Force re-downloading $d (was incomplete locally) …"
    rm -rf "$LOCAL_BASE/$d"
    fetch_dir "$d"
done

for d in "${NEW_DIRS[@]}"; do
    if [ -d "$LOCAL_BASE/$d" ]; then
        log "  $d already exists locally, skipping."
    else
        fetch_dir "$d"
    fi
done

# ── Policy comparison ─────────────────────────────────────────────────────────
log "=== Policy comparison plots ==="
cd "$PROJECT"

for suite in dpc3 google qmm; do
    pol_dir="results/cluster/${suite}_pol_20260511_1545"
    if [ ! -d "$pol_dir" ]; then
        log "  WARNING: $pol_dir not found, skipping."
        continue
    fi
    run_plot "$SCRIPTS/plot_policy_comparison.py" \
        "$pol_dir" \
        --out "results/plots/srrip_live_pol_${suite}"
done

run_plot "$SCRIPTS/plot_suite_comparison.py" \
    "results/cluster/dpc3_pol_20260511_1545" \
    "results/cluster/google_pol_20260511_1545" \
    "results/cluster/qmm_pol_20260511_1545" \
    --labels DPC3 Google QMM \
    --out "results/plots/srrip_live_suite_comparison"

# ── srrip_live threshold sweep ────────────────────────────────────────────────
log "=== srrip_live threshold plots ==="

run_plot "$SCRIPTS/plot_srrip_live_thd.py" \
    --thd-dirs \
        "results/cluster/dpc3_srrip_live_thd_20260511_2218" \
        "results/cluster/google_srrip_live_thd_20260511_2218" \
        "results/cluster/qmm_srrip_live_thd_20260511_2218" \
    --pol-dirs \
        "results/cluster/dpc3_pol_20260511_1545" \
        "results/cluster/google_pol_20260511_1545" \
        "results/cluster/qmm_pol_20260511_1545" \
    --labels "SPEC (DPC3)" Google Qualcomm \
    --out "results/plots/srrip_live_thd.png"

# ── Cache / TLB size study ────────────────────────────────────────────────────
log "=== Cache size study plots ==="
mkdir -p results/plots/cache_size_study

declare -A SUITE_LABEL=([dpc3]="dpc3" [google]="google" [qmm]="qmm")

for suite in dpc3 google qmm; do
    cs_dir="results/cluster/${suite}_cache_size_20260511_2342"
    if [ ! -d "$cs_dir" ]; then
        log "  WARNING: $cs_dir not found, skipping."
        continue
    fi
    run_plot "$SCRIPTS/plot_cache_size_study.py" \
        "$cs_dir" \
        --suite "${SUITE_LABEL[$suite]}" \
        --out "results/plots/cache_size_study/${suite}"
done

log "=== All done. Plots in results/plots/ ==="
