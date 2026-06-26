#!/usr/bin/env bash
# Run the black-box test suite on the cluster with automatic queue management.
#
# Workflow:
#   1. Hold all currently-queued (qw) jobs so bb_ jobs get the slots first.
#   2. Submit the 26 gate-phase verify jobs.
#   3. Poll until they all finish.
#   4. Download logs and report PASS/FAIL.
#   5. Release the jobs put on hold in step 1.
#
# Usage:
#   bash scripts/submit/blackbox_run_cluster.sh
#
# Requirements: SSH access via abdet → castillo (BatchMode keys set up).
set -euo pipefail

ABDET=otegby@abdet.inf.um.es
ROOT=/home/users/otegby/ChampSim-dev
LOCAL_LOGDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/test/blackbox/logs_cluster"
POLL_INTERVAL=30

ca() { ssh -o BatchMode=yes "$ABDET" "ssh otegby@castillo.inf.um.es '$*'" 2>/dev/null; }

mkdir -p "$LOCAL_LOGDIR"

# ── 1. Hold all currently-queued (qw) jobs ────────────────────────────────
echo "[$(date +%T)] Identifying queued jobs to hold..."
qw_jobs=$(ca 'qstat -u otegby 2>/dev/null | awk "NR>1 && \$5==\"qw\"{print \$1}" | sort -u | tr "\n" " "')
qw_jobs="${qw_jobs%% }"  # trim trailing space

if [ -n "$qw_jobs" ]; then
    held_count=$(ca "qhold $qw_jobs 2>&1 | grep -c 'modified hold'" || echo 0)
    echo "[$(date +%T)] Held $held_count tasks from jobs: $qw_jobs"
else
    echo "[$(date +%T)] No queued jobs to hold."
fi

# ── 2. Submit bb_ verify jobs ─────────────────────────────────────────────
echo "[$(date +%T)] Submitting black-box verify jobs..."
submit_out=$(ca "bash $ROOT/scripts/submit/blackbox_validation.sh verify 2>&1")
echo "$submit_out"
bb_ids=$(echo "$submit_out" | grep -oP '(?<=job )\d+' | tr '\n' '|')
bb_ids="${bb_ids%|}"  # trim trailing pipe
n_bb=$(echo "$submit_out" | grep -c 'has been submitted')
echo "[$(date +%T)] Submitted $n_bb jobs (IDs: $(echo "$bb_ids" | tr '|' ' '))"

# ── 3. Poll until all bb_ jobs are done ───────────────────────────────────
echo "[$(date +%T)] Waiting for jobs to finish (polling every ${POLL_INTERVAL}s)..."
while true; do
    running=$(ca "qstat -u otegby 2>/dev/null | awk 'NR>1{print \$1}'" \
        | grep -cE "^(${bb_ids})$" || true)
    echo "[$(date +%T)] ${running}/${n_bb} verify jobs still running"
    [ "$running" -eq 0 ] && break
    sleep "$POLL_INTERVAL"
done

# ── 4. Download logs and report ───────────────────────────────────────────
echo "[$(date +%T)] Downloading logs..."
ca "tar czf /tmp/bb_logs.tar.gz -C $ROOT/test/blackbox/logs ."
scp "$ABDET:/tmp/bb_logs.tar.gz" /tmp/bb_logs.tar.gz 2>/dev/null \
    || ssh "$ABDET" "scp otegby@castillo.inf.um.es:/tmp/bb_logs.tar.gz /tmp/ && cat /tmp/bb_logs.tar.gz" > /tmp/bb_logs.tar.gz
tar xzf /tmp/bb_logs.tar.gz -C "$LOCAL_LOGDIR"

echo ""
echo "══════════════════════════════════════════"
echo "  BLACK-BOX RESULTS (cluster gate phase)  "
echo "══════════════════════════════════════════"
pass=0; fail=0
for f in "$LOCAL_LOGDIR"/*.gate.log; do
    scen=$(basename "$f" .gate.log)
    result=$(grep -oE 'PASS [^ ]+|FAIL [^ ]+' "$f" | tail -1 || echo "NO_RESULT")
    printf "  %-32s %s\n" "$scen" "$result"
    [[ "$result" == PASS* ]] && ((pass++)) || ((fail++))
done
echo ""
if [ "$fail" -eq 0 ]; then
    echo "  ALL PASSED ($pass/$((pass+fail)))"
else
    echo "  $fail FAILED, $pass passed ($pass/$((pass+fail)))"
fi
echo "══════════════════════════════════════════"

# ── 5. Release the jobs put on hold ───────────────────────────────────────
if [ -n "$qw_jobs" ]; then
    echo ""
    echo "[$(date +%T)] Releasing held jobs..."
    released=$(ca "qrls $qw_jobs 2>&1 | grep -c 'modified hold'" || echo 0)
    echo "[$(date +%T)] Released $released tasks."
fi
