#!/usr/bin/env bash
# Run the black-box tests on the cluster with automatic queue management.
#
# Usage:
#   bash scripts/submit/blackbox_run_cluster.sh           # compare against expected/
#   bash scripts/submit/blackbox_run_cluster.sh generate  # write new expected/ outputs
#
# Workflow:
#   1. Hold all queued (qw) jobs so bb_ jobs run first.
#   2. Submit the full-phase jobs (50M warmup + 100M sim).
#   3. Poll until done.
#   4. Download outputs.
#   5a. generate: copy to expected/, commit.
#   5b. verify:   diff against expected/, report PASS/FAIL.
#   6. Release held jobs.
#
# Requirements: SSH access via abdet → castillo (BatchMode keys set up).
set -euo pipefail

MODE="${1:-verify}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

ABDET=otegby@abdet.inf.um.es
ROOT=/home/users/otegby/ChampSim-dev
EXPECTED_DIR="$REPO/test/blackbox/expected"
LOCAL_OUT_DIR="$REPO/test/blackbox/test_outputs_cluster"
CHECK="$REPO/test/blackbox/check_progress.sh"
POLL_INTERVAL=30
STUCK_TIMEOUT=900   # seconds of no output progress before a *running* bb job is
                   # treated as hung and cancelled, so the verify loop can finish.
RELEASED=0

# Scenario list is owned by run_scenario.sh (--list), the single source of truth.
mapfile -t SCENARIOS < <(bash "$REPO/test/blackbox/run_scenario.sh" --list)

# Run a command on castillo via the abdet jump host.
# The command is base64-encoded so it survives two layers of SSH quoting intact
# — single quotes inside awk/grep programs would otherwise terminate a naive
# single-quote wrapper and silently break the command.
ca() {
    local cmd b64
    cmd="$*"
    b64=$(printf '%s' "$cmd" | base64 -w0)
    ssh -o BatchMode=yes "$ABDET" "ssh otegby@castillo.inf.um.es \"echo $b64 | base64 -d | bash\""
}

mkdir -p "$LOCAL_OUT_DIR"

# Pull the (possibly in-progress) scenario outputs from the cluster. tar reads
# whatever is on disk now, so partially-written files come down fine.
download_partials() {
    ssh "$ABDET" "ssh otegby@castillo.inf.um.es 'tar czf - -C $ROOT/test/blackbox/test_outputs .'" 2>/dev/null \
        | tar xzf - -C "$LOCAL_OUT_DIR" 2>/dev/null || true
}

# Count submitted bb_ jobs still in the queue. Echoes -1 if qstat/SSH returned
# nothing at all (a transient failure), so the caller does not mistake an SSH
# blip for "queue drained" -- held qw jobs always keep a real qstat non-empty.
jobs_in_queue() {
    local raw
    raw=$(ca "qstat -u otegby 2>/dev/null | awk 'NR>1{print \$1}'" 2>/dev/null || true)
    [ -z "$raw" ] && { echo "-1"; return; }
    echo "$raw" | grep -cE "^(${bb_ids})$" || true
}

# Release the jobs held in step 1 (uses $qw_jobs). Idempotent -- safe to call from
# the poll loop and again at the end.
qrls_held() {
    [ "$RELEASED" = 1 ] && return 0
    RELEASED=1
    [ -n "${qw_jobs:-}" ] || return 0
    echo ""
    echo "[$(date +%T)] Releasing held jobs..."
    ca "qrls $qw_jobs 2>&1 | grep -c 'modified hold'" || true
    echo "[$(date +%T)] Done."
}

# Count submitted bb_ jobs still WAITING for a slot (qw state). Echoes -1 on an
# SSH/qstat blip so a transient failure is not misread as "all launched".
bb_waiting() {
    local raw
    raw=$(ca "qstat -u otegby 2>/dev/null | awk 'NR>1 && \$5 ~ /qw/{print \$1}'" 2>/dev/null || true)
    [ -z "$raw" ] && { echo "-1"; return; }
    echo "$raw" | grep -cE "^(${bb_ids})$" || true
}

# Release the held jobs as soon as every bb job has LAUNCHED (none left waiting for
# a slot). The hold exists only to get the bb jobs started ahead of the queue; once
# none are waiting, holding longer would just starve the queue with no benefit to
# the already-running bb jobs. Releasing strictly at "none waiting" is both
# starvation-free (no bb job loses a slot) and strangle-free (a hung *running* job
# does not delay the release). A bb job that cannot get a slot at all keeps the
# hold -- but that means the cluster is full, so the queue could not run anyway.
release_when_launched() {
    [ "$RELEASED" = 0 ] || return 0
    [ -n "${qw_jobs:-}" ] || { RELEASED=1; return 0; }
    if [ "$(bb_waiting)" = 0 ]; then
        echo "[$(date +%T)] All bb jobs launched; releasing held jobs."
        qrls_held
    fi
}

# ── 1. Hold queued jobs ───────────────────────────────────────────────────
echo "[$(date +%T)] Identifying queued jobs to hold..."
qw_jobs=$(ca 'qstat -u otegby 2>/dev/null | awk "NR>1 && \$5==\"qw\"{print \$1}" | sort -u | tr "\n" " "')
qw_jobs="${qw_jobs%% }"
if [ -n "$qw_jobs" ]; then
    held_count=$(ca "qhold $qw_jobs 2>&1 | grep -c 'modified hold'" || echo 0)
    echo "[$(date +%T)] Held $held_count tasks from: $qw_jobs"
else
    echo "[$(date +%T)] No queued jobs to hold."
fi

# ── 1b. Clear stale outputs ───────────────────────────────────────────────
# Outputs from a previous run must be removed first: otherwise the first poll
# would download already-complete files and report FULL_PASS instantly, before
# this run's jobs have even started -- a false pass on stale data, and the
# incremental progression would never be exercised.
echo "[$(date +%T)] Clearing previous outputs..."
ca "rm -f $ROOT/test/blackbox/test_outputs/*.out" || true
rm -f "$LOCAL_OUT_DIR"/*.out

# ── 2. Submit bb_ jobs ────────────────────────────────────────────────────
echo "[$(date +%T)] Submitting black-box jobs..."
submit_out=$(ca "bash $ROOT/scripts/submit/blackbox_validation.sh 2>&1")
bb_ids=$(echo "$submit_out" | grep -oP '(?<=job )\d+' | tr '\n' '|')
bb_ids="${bb_ids%|}"
n_bb=$(echo "$submit_out" | grep -c 'has been submitted')
echo "[$(date +%T)] Submitted $n_bb jobs (IDs: $(echo "$bb_ids" | tr '|' ' '))"

# ── 3. Wait for jobs to register ──────────────────────────────────────────
# SGE has a small delay between qsub returning and jobs appearing in qstat.
echo "[$(date +%T)] Waiting for jobs to register..."
for _i in $(seq 1 24); do
    [ "$(jobs_in_queue)" -gt 0 ] && break
    sleep 5
done

if [ "$MODE" = generate ]; then
    # ── 4g. Generate: wait for completion, snapshot outputs to expected/ ──
    echo "[$(date +%T)] Waiting for jobs to finish (poll ${POLL_INTERVAL}s)..."
    while true; do
        running=$(jobs_in_queue)
        [ "$running" -ge 0 ] && echo "[$(date +%T)] ${running}/${n_bb} jobs still in queue"
        release_when_launched
        [ "$running" -eq 0 ] && break
        sleep "$POLL_INTERVAL"
    done
    download_partials
    echo "[$(date +%T)] Writing reference outputs to expected/..."
    mkdir -p "$EXPECTED_DIR"   # may not exist if all references were removed
    for scen in "${SCENARIOS[@]}"; do
        cp "$LOCAL_OUT_DIR/${scen}.out" "$EXPECTED_DIR/${scen}.out"
    done
    git -C "$REPO" add test/blackbox/expected/
    git -C "$REPO" commit -m "test: update expected outputs from cluster full runs"
    echo "[$(date +%T)] Done — expected/ updated and committed."
    qrls_held
    exit 0
fi

# ── 4v. Verify: incremental progress checking while jobs run ──────────────
# Each poll pulls the partial outputs and classifies every scenario against its
# reference. A diverged run is reported (and its job cancelled) the moment a
# completed line mismatches -- no need to wait for the full simulation.
echo "[$(date +%T)] Incremental verification (poll ${POLL_INTERVAL}s)."
echo "  states: PENDING < RUNNING < SOFT_PASS (>=30M sim, on track) < FULL_PASS;  FAIL = diverged"
declare -A PREV LINES STALL_SINCE
while true; do
    download_partials
    np=0; nr=0; ns=0; nx=0; nf=0; nz=0
    for scen in "${SCENARIOS[@]}"; do
        st=$(bash "$CHECK" "$LOCAL_OUT_DIR/${scen}.out" "$EXPECTED_DIR/${scen}.out")
        # Watchdog: a job that has started (has output) but whose output has not
        # advanced for STUCK_TIMEOUT is hung -- cancel it so the verify loop can
        # finish. PENDING jobs (just waiting for a slot) are left alone.
        if [ "$st" = RUNNING ] || [ "$st" = SOFT_PASS ]; then
            cur=$(tr -cd '\n' < "$LOCAL_OUT_DIR/${scen}.out" 2>/dev/null | wc -c); cur=${cur:-0}
            if [ "$cur" -gt "${LINES[$scen]:-0}" ]; then
                LINES[$scen]=$cur; STALL_SINCE[$scen]=$(date +%s)
            elif [ "$(( $(date +%s) - ${STALL_SINCE[$scen]:-$(date +%s)} ))" -ge "$STUCK_TIMEOUT" ]; then
                echo "  [$(date +%T)] STUCK      $scen — no output for ${STUCK_TIMEOUT}s; cancelling bb_${scen}"
                ca "qdel bb_${scen}" >/dev/null 2>&1 || true
                st=FAIL
                PREV[$scen]=FAIL   # already reported here; suppress the FAIL announce below
            fi
        fi
        case "$st" in
            PENDING)      np=$((np+1));;
            RUNNING)      nr=$((nr+1));;
            SOFT_PASS)    ns=$((ns+1));;
            FULL_PASS)    nx=$((nx+1));;
            FAIL)         nf=$((nf+1));;
            NO-REFERENCE) nz=$((nz+1));;
        esac
        # Announce each scenario's state transition once.
        if [ "${PREV[$scen]:-}" != "$st" ]; then
            case "$st" in
                SOFT_PASS) echo "  [$(date +%T)] SOFT PASS  $scen — >=30M sim verified, on track";;
                FULL_PASS) echo "  [$(date +%T)] FULL PASS  $scen — fully verified";;
                FAIL)
                    echo "  [$(date +%T)] FAIL       $scen — diverged from expected:"
                    diff "$EXPECTED_DIR/${scen}.out" "$LOCAL_OUT_DIR/${scen}.out" \
                        | grep -E '^[<>]' | head -6 | sed 's/^/      /' || true
                    echo "      cancelling doomed job bb_${scen}"
                    ca "qdel bb_${scen}" >/dev/null 2>&1 || true
                    ;;
            esac
            PREV[$scen]="$st"
        fi
    done
    echo "[$(date +%T)] pending:$np running:$nr soft:$ns full:$nx FAIL:$nf"
    # Release the held queue once every bb job has launched (none waiting) -- the
    # bb jobs keep their slots and finish; the queue resumes behind them.
    release_when_launched
    # Done when every scenario is terminal (fully verified, failed, or no ref).
    [ "$((nx+nf+nz))" -eq "${#SCENARIOS[@]}" ] && break
    # Safety net: if the queue drained but some scenario never completed (a job
    # crashed), stop instead of polling forever; the final report flags it.
    if [ "$(jobs_in_queue)" -eq 0 ]; then
        echo "[$(date +%T)] queue drained; finalizing."
        sleep 3; download_partials; break
    fi
    sleep "$POLL_INTERVAL"
done

# ── 5. Final report ───────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════"
echo "  BLACK-BOX RESULTS (cluster / full)  "
echo "══════════════════════════════════════"
pass=0; fail=0
for scen in "${SCENARIOS[@]}"; do
    st=$(bash "$CHECK" "$LOCAL_OUT_DIR/${scen}.out" "$EXPECTED_DIR/${scen}.out")
    case "$st" in
        FULL_PASS) printf "  %-32s PASS\n" "$scen"; pass=$((pass+1));;
        FAIL)      printf "  %-32s FAIL\n" "$scen"; fail=$((fail+1));;
        *)         printf "  %-32s INCOMPLETE (%s)\n" "$scen" "$st"; fail=$((fail+1));;
    esac
done
echo ""
[ "$fail" -eq 0 ] \
    && echo "  ALL PASSED ($pass/$((pass+fail)))" \
    || echo "  $fail FAILED/INCOMPLETE, $pass passed ($pass/$((pass+fail)))"
echo "══════════════════════════════════════"

# ── 6. Release held jobs ──────────────────────────────────────────────────
qrls_held
