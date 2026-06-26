#!/usr/bin/env bash
# Run the black-box gate tests on the cluster with automatic queue management.
#
# Workflow:
#   1. Hold all currently-queued (qw) jobs so bb_ jobs run first.
#   2. Submit all 26 gate-phase jobs (output saved to cluster test_outputs/).
#   3. Poll until they all finish.
#   4. Download the output files.
#   5. Diff each output against the local expected_cluster/ reference.
#   6. Report PASS/FAIL.
#   7. Release the jobs put on hold in step 1.
#
# Comparison is done locally against test/blackbox/expected_cluster/ so the
# cluster needs no reference files of its own — it is just a compute resource.
#
# Usage:
#   bash scripts/submit/blackbox_run_cluster.sh
#
# Requirements: SSH access via abdet → castillo (BatchMode keys set up).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

ABDET=otegby@abdet.inf.um.es
ROOT=/home/users/otegby/ChampSim-dev
EXPECTED_DIR="$REPO/test/blackbox/expected_cluster"
LOCAL_OUT_DIR="$REPO/test/blackbox/test_outputs_cluster"
POLL_INTERVAL=30

ca() { ssh -o BatchMode=yes "$ABDET" "ssh otegby@castillo.inf.um.es '$*'" 2>/dev/null; }

mkdir -p "$LOCAL_OUT_DIR"

# ── 1. Hold all currently-queued (qw) jobs ────────────────────────────────
echo "[$(date +%T)] Identifying queued jobs to hold..."
qw_jobs=$(ca 'qstat -u otegby 2>/dev/null | awk "NR>1 && \$5==\"qw\"{print \$1}" | sort -u | tr "\n" " "')
qw_jobs="${qw_jobs%% }"

if [ -n "$qw_jobs" ]; then
    held_count=$(ca "qhold $qw_jobs 2>&1 | grep -c 'modified hold'" || echo 0)
    echo "[$(date +%T)] Held $held_count tasks from: $qw_jobs"
else
    echo "[$(date +%T)] No queued jobs to hold."
fi

# ── 2. Submit bb_ jobs ────────────────────────────────────────────────────
echo "[$(date +%T)] Submitting black-box jobs..."
submit_out=$(ca "bash $ROOT/scripts/submit/blackbox_validation.sh 2>&1")
bb_ids=$(echo "$submit_out" | grep -oP '(?<=job )\d+' | tr '\n' '|')
bb_ids="${bb_ids%|}"
n_bb=$(echo "$submit_out" | grep -c 'has been submitted')
echo "[$(date +%T)] Submitted $n_bb jobs (IDs: $(echo "$bb_ids" | tr '|' ' '))"

# ── 3. Poll until all bb_ jobs are done ───────────────────────────────────
echo "[$(date +%T)] Waiting for jobs to finish (polling every ${POLL_INTERVAL}s)..."
while true; do
    running=$(ca "qstat -u otegby 2>/dev/null | awk 'NR>1{print \$1}'" \
        | grep -cE "^(${bb_ids})$" || true)
    echo "[$(date +%T)] ${running}/${n_bb} jobs still in queue"
    [ "$running" -eq 0 ] && break
    sleep "$POLL_INTERVAL"
done

# ── 4. Download output files ───────────────────────────────────────────────
echo "[$(date +%T)] Downloading outputs..."
ca "tar czf /tmp/bb_outputs.tar.gz -C $ROOT/test/blackbox/test_outputs ."
ssh "$ABDET" "scp otegby@castillo.inf.um.es:/tmp/bb_outputs.tar.gz /tmp/"
scp "$ABDET:/tmp/bb_outputs.tar.gz" /tmp/bb_outputs.tar.gz
tar xzf /tmp/bb_outputs.tar.gz -C "$LOCAL_OUT_DIR"

# ── 5 & 6. Diff against local expected_cluster/ and report ────────────────
echo ""
echo "══════════════════════════════════════════"
echo "  BLACK-BOX RESULTS (cluster gate phase)  "
echo "══════════════════════════════════════════"
pass=0; fail=0
for expected in "$EXPECTED_DIR"/*.out; do
    scen=$(basename "$expected" .out)
    actual="$LOCAL_OUT_DIR/${scen}.out"
    if [ ! -f "$actual" ]; then
        printf "  %-32s MISSING OUTPUT\n" "$scen"
        ((fail++))
    elif diff -q "$expected" "$actual" > /dev/null 2>&1; then
        printf "  %-32s PASS\n" "$scen"
        ((pass++))
    else
        printf "  %-32s FAIL\n" "$scen"
        diff "$expected" "$actual" | head -20
        ((fail++))
    fi
done
echo ""
if [ "$fail" -eq 0 ]; then
    echo "  ALL PASSED ($pass/$((pass+fail)))"
else
    echo "  $fail FAILED, $pass passed ($pass/$((pass+fail)))"
fi
echo "══════════════════════════════════════════"

# ── 7. Release the jobs put on hold ───────────────────────────────────────
if [ -n "$qw_jobs" ]; then
    echo ""
    echo "[$(date +%T)] Releasing held jobs..."
    ca "qrls $qw_jobs 2>&1 | grep -c 'modified hold'" || true
    echo "[$(date +%T)] Done."
fi
