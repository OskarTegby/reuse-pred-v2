#!/usr/bin/env bash
# monitor_and_fetch.sh — wait for the April 9 job sweep to finish, download
# results from castillo, and run the standard analysis plots.
#
# Runs unattended in the background; writes a log to /tmp/monitor_fetch.log.
# Notification comes via the Claude Code background-task callback.

set -euo pipefail

LOG=/tmp/monitor_fetch.log
REMOTE="otegby@abdet.inf.um.es"
CASTILLO="otegby@castillo.inf.um.es"
REMOTE_BASE="~/ChampSim-dev/results"
LOCAL_BASE="/home/otegby/repos/code/reuse-pred/results/llc_repl_pol_study"
SCRIPTS="/home/otegby/repos/code/reuse-pred/scripts/analysis"

# Job IDs submitted on 2026-04-09 (1397209 – 1397292)
MIN_JID=1397209
MAX_JID=1397292

POLL_INTERVAL=120   # seconds between qstat checks

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

# ── Result dirs ───────────────────────────────────────────────────────────────
RESULT_DIRS=(
    qmm_pol_20260409_0217
    dpc3_pol_20260409_0218
    google_pol_20260409_0218
    qmm_mid_addr_20260409_0218
    dpc3_mid_addr_20260409_0218
    google_mid_addr_20260409_0218
    qmm_mid_addr_paper_pref_20260409_0218
    dpc3_mid_addr_paper_pref_20260409_0218
    google_mid_addr_paper_pref_20260409_0218
)

# ── Helpers ───────────────────────────────────────────────────────────────────

jobs_still_running() {
    ssh -o BatchMode=yes -o ConnectTimeout=15 "$REMOTE" \
        "ssh $CASTILLO 'qstat -u otegby 2>/dev/null'" 2>/dev/null \
        | awk 'NR>2 {print $1}' \
        | awk -F. '{print $1}' \
        | grep -qE "^(${MIN_JID}|[0-9]+)$" \
    && ssh -o BatchMode=yes -o ConnectTimeout=15 "$REMOTE" \
        "ssh $CASTILLO 'qstat -u otegby 2>/dev/null'" 2>/dev/null \
        | awk 'NR>2 {jid=$1+0} jid>='$MIN_JID' && jid<='$MAX_JID' {found=1} END{exit !found}'
}

fetch_dir() {
    local name="$1"
    local tmp="/tmp/cs_fetch_${name}"
    log "  fetching $name …"
    ssh -o BatchMode=yes "$REMOTE" "rm -rf $tmp"
    ssh -o BatchMode=yes "$REMOTE" \
        "scp -r -o BatchMode=yes $CASTILLO:$REMOTE_BASE/$name $tmp" 2>/dev/null
    mkdir -p "$LOCAL_BASE"
    scp -r "$REMOTE:$tmp" "$LOCAL_BASE/$name" 2>/dev/null
    ssh -o BatchMode=yes "$REMOTE" "rm -rf $tmp" 2>/dev/null || true
    log "  done → results/$name"
}

run_plot() {
    log "  plot: $*"
    python3 "$@" >> "$LOG" 2>&1 && log "  ok" || log "  WARNING: plot exited non-zero"
}

# ── Poll ──────────────────────────────────────────────────────────────────────
log "=== monitor_and_fetch started (jobs $MIN_JID–$MAX_JID) ==="
log "Polling every ${POLL_INTERVAL}s …"

while true; do
    if ! jobs_still_running; then
        log "All jobs finished."
        break
    fi
    remaining=$(ssh -o BatchMode=yes "$REMOTE" \
        "ssh $CASTILLO 'qstat -u otegby 2>/dev/null'" 2>/dev/null \
        | awk 'NR>2' | wc -l || echo "?")
    log "Still running: $remaining tasks queued/running. Sleeping …"
    sleep "$POLL_INTERVAL"
done

# ── Download ──────────────────────────────────────────────────────────────────
log "=== Downloading results ==="
for d in "${RESULT_DIRS[@]}"; do
    if [ -d "$LOCAL_BASE/$d" ]; then
        log "  $d already exists locally, skipping download."
    else
        fetch_dir "$d"
    fi
done

# ── Analysis ─────────────────────────────────────────────────────────────────
log "=== Running analysis ==="
cd /home/otegby/repos/code/reuse-pred

POL_DIRS=(
    "results/llc_repl_pol_study/qmm_pol_20260409_0217"
    "results/llc_repl_pol_study/dpc3_pol_20260409_0218"
    "results/llc_repl_pol_study/google_pol_20260409_0218"
)
POL_LABELS=(QMM DPC3 Google)
SUITES=(qmm dpc3 google)

# Per-suite policy comparison
for i in 0 1 2; do
    suite="${SUITES[$i]}"
    dir="${POL_DIRS[$i]}"
    run_plot "$SCRIPTS/plot_policy_comparison.py" \
        "$dir" \
        --out "results/plots/policy_${suite}"
done

# Cross-suite policy comparison
run_plot "$SCRIPTS/plot_suite_comparison.py" \
    "${POL_DIRS[@]}" \
    --labels "${POL_LABELS[@]}" \
    --out "results/plots/suite_comparison"

# Mid-threshold plots — no-pref
for suite in qmm dpc3 google; do
    dir="results/llc_repl_pol_study/${suite}_mid_addr_20260409_0218"
    run_plot "$SCRIPTS/plot_mid_thd.py" \
        "$dir" \
        --out "results/plots/mid_thd_${suite}_nopref"
done

# Mid-threshold plots — paper_pref
for suite in qmm dpc3 google; do
    dir="results/llc_repl_pol_study/${suite}_mid_addr_paper_pref_20260409_0218"
    run_plot "$SCRIPTS/plot_mid_thd.py" \
        "$dir" \
        --out "results/plots/mid_thd_${suite}_paper_pref"
done

log "=== All done. Results in results/  Plots in results/plots/ ==="
