#!/usr/bin/env bash
# Run the black-box tests on the cluster with automatic queue management.
#
# Usage:
#   bash scripts/submit/blackbox_run_cluster.sh           # compare against expected/
#   bash scripts/submit/blackbox_run_cluster.sh generate  # write new expected/ outputs
#
# Workflow:
#   1. Hold all queued (qw) jobs so bb_ jobs run first.
#   2. Submit 26 full-phase jobs (50M warmup + 100M sim).
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
POLL_INTERVAL=30

SCENARIOS=(
  lru_default lru_2n3 lru_lru lru_bypass lru_bypass_off
  lru_duel_hits lru_duel_lat_hyst lru_cap256
  srrip_default srrip_mode3 srrip_mode4 srrip_mode5 srrip_mode7 srrip_mode8
  srrip_cap256 srrip_duel_cfg0 srrip_bypass_fixed srrip_bypass_duel
  ipv_default ipv_canonical ipv_ins3_comma ipv_ins3_colon ipv_cap256
  duel_ipv_cfg0_ins2 duel_ipv_cfg0_ins3 duel_ipv_3way
)

ca() { ssh -o BatchMode=yes "$ABDET" "ssh otegby@castillo.inf.um.es '$*'"; }

mkdir -p "$LOCAL_OUT_DIR"

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

# ── 2. Submit bb_ jobs ────────────────────────────────────────────────────
echo "[$(date +%T)] Submitting black-box jobs..."
submit_out=$(ca "bash $ROOT/scripts/submit/blackbox_validation.sh 2>&1")
bb_ids=$(echo "$submit_out" | grep -oP '(?<=job )\d+' | tr '\n' '|')
bb_ids="${bb_ids%|}"
n_bb=$(echo "$submit_out" | grep -c 'has been submitted')
echo "[$(date +%T)] Submitted $n_bb jobs (IDs: $(echo "$bb_ids" | tr '|' ' '))"

# ── 3. Poll ───────────────────────────────────────────────────────────────
echo "[$(date +%T)] Waiting (polling every ${POLL_INTERVAL}s)..."
# SGE has a small delay between qsub returning and jobs appearing in qstat.
# Wait until at least one submitted job is visible before entering the poll loop.
for _i in $(seq 1 24); do
    seen=$(ca "qstat -u otegby 2>/dev/null | awk 'NR>1{print \$1}'" \
        | grep -cE "^(${bb_ids})$" || true)
    [ "$seen" -gt 0 ] && break
    sleep 5
done
while true; do
    qstat_out=$(ca "qstat -u otegby 2>/dev/null | awk 'NR>1{print \$1}'" 2>/dev/null || true)
    # If qstat returned nothing at all (SSH failure), skip this poll rather than
    # falsely declaring all jobs done.
    if [ -z "$qstat_out" ]; then
        echo "[$(date +%T)] qstat returned empty (SSH issue?), retrying..."
        sleep "$POLL_INTERVAL"
        continue
    fi
    running=$(echo "$qstat_out" | grep -cE "^(${bb_ids})$" || true)
    echo "[$(date +%T)] ${running}/${n_bb} jobs still in queue"
    [ "$running" -eq 0 ] && break
    sleep "$POLL_INTERVAL"
done

# ── 4. Download ───────────────────────────────────────────────────────────
echo "[$(date +%T)] Downloading outputs..."
ssh "$ABDET" "ssh otegby@castillo.inf.um.es 'tar czf - -C $ROOT/test/blackbox/test_outputs .'" \
    | tar xzf - -C "$LOCAL_OUT_DIR"

# ── 5. Generate or verify ─────────────────────────────────────────────────
if [ "$MODE" = generate ]; then
    echo "[$(date +%T)] Writing reference outputs to expected/..."
    for scen in "${SCENARIOS[@]}"; do
        cp "$LOCAL_OUT_DIR/${scen}.out" "$EXPECTED_DIR/${scen}.out"
    done
    git -C "$REPO" add test/blackbox/expected/
    git -C "$REPO" commit -m "test: update expected outputs from cluster full runs"
    echo "[$(date +%T)] Done — expected/ updated and committed."
else
    echo ""
    echo "══════════════════════════════════════"
    echo "  BLACK-BOX RESULTS (cluster / full)  "
    echo "══════════════════════════════════════"
    pass=0; fail=0
    for scen in "${SCENARIOS[@]}"; do
        expected="$EXPECTED_DIR/${scen}.out"
        actual="$LOCAL_OUT_DIR/${scen}.out"
        if [ ! -f "$actual" ]; then
            printf "  %-32s MISSING\n" "$scen"; ((fail++))
        elif diff -q "$expected" "$actual" > /dev/null 2>&1; then
            printf "  %-32s PASS\n" "$scen"; ((pass++))
        else
            printf "  %-32s FAIL\n" "$scen"
            diff "$expected" "$actual" | head -20
            ((fail++))
        fi
    done
    echo ""
    [ "$fail" -eq 0 ] \
        && echo "  ALL PASSED ($pass/$((pass+fail)))" \
        || echo "  $fail FAILED, $pass passed ($pass/$((pass+fail)))"
    echo "══════════════════════════════════════"
fi

# ── 6. Release held jobs ──────────────────────────────────────────────────
if [ -n "$qw_jobs" ]; then
    echo ""
    echo "[$(date +%T)] Releasing held jobs..."
    ca "qrls $qw_jobs 2>&1 | grep -c 'modified hold'" || true
    echo "[$(date +%T)] Done."
fi
