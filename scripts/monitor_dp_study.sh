#!/usr/bin/env bash
# monitor_dp_study.sh — wait for dp_study jobs on castillo, download, analyse.
#
# Polls qstat until jobs 1397491-1397499 are gone, then:
#   1. Verifies expected output counts
#   2. Downloads results via SSH pipe
#   3. Runs plot_dp_cbpred_study.py

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

CASTILLO_HOST="castillo"
REMOTE_ROOT="/home/otegby/repos/code/reuse-pred"

DATE_TAG="20260428_1143"
SUITES=(qmm dpc3 google)
# Expected champsim.out files per suite (3 configs each)
declare -A EXPECTED_COUNTS=([qmm]=135 [dpc3]=285 [google]=129)

JOB_IDS=(1397491 1397492 1397493 1397494 1397495 1397496 1397497 1397498 1397499)

POLL_INTERVAL=120   # seconds between qstat polls
LOCAL_RESULTS="${PROJECT_ROOT}/results/dp_study"
OUT_DIR="${PROJECT_ROOT}/results/plots/dp_cbpred_study"

LOG="${PROJECT_ROOT}/logs/monitor_dp_study_$(date +%Y%m%d_%H%M).log"
mkdir -p "$(dirname "$LOG")"

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

# ── 1. Poll until all jobs are gone ──────────────────────────────────────────

log "Monitoring dp_study jobs: ${JOB_IDS[*]}"
log "Polling every ${POLL_INTERVAL}s. Log: $LOG"

while true; do
    running_ids=()
    for jid in "${JOB_IDS[@]}"; do
        if ssh -q "$CASTILLO_HOST" "qstat -j ${jid}" &>/dev/null; then
            running_ids+=("$jid")
        fi
    done

    if [ "${#running_ids[@]}" -eq 0 ]; then
        log "All jobs finished."
        break
    fi

    log "Still running: ${running_ids[*]} (${#running_ids[@]} remaining)"
    sleep "$POLL_INTERVAL"
done

# ── 2. Verify output completeness ────────────────────────────────────────────

log "Verifying output file counts on castillo…"
all_ok=1
for suite in "${SUITES[@]}"; do
    remote_dir="${REMOTE_ROOT}/results/${suite}_dp_study_${DATE_TAG}"
    count=$(ssh -q "$CASTILLO_HOST" "find '${remote_dir}' -name champsim.out 2>/dev/null | wc -l")
    expected="${EXPECTED_COUNTS[$suite]}"
    if [ "$count" -eq "$expected" ]; then
        log "  $suite: $count/$expected ✓"
    else
        log "  $suite: $count/$expected  ← INCOMPLETE"
        all_ok=0
    fi
done

if [ "$all_ok" -eq 0 ]; then
    log "WARNING: some suites are incomplete — downloading anyway."
fi

# ── 3. Download via SSH pipe ──────────────────────────────────────────────────

mkdir -p "$LOCAL_RESULTS"

for suite in "${SUITES[@]}"; do
    remote_dir="${REMOTE_ROOT}/results/${suite}_dp_study_${DATE_TAG}"
    local_dir="${LOCAL_RESULTS}/${suite}_dp_study_${DATE_TAG}"

    if [ -d "$local_dir" ]; then
        log "  $suite already downloaded — skipping (delete to re-fetch)"
        continue
    fi

    log "Downloading $suite …"
    mkdir -p "$local_dir"
    ssh -q "$CASTILLO_HOST" \
        "tar czf - -C '${REMOTE_ROOT}/results' '${suite}_dp_study_${DATE_TAG}'" \
        | tar xzf - -C "$LOCAL_RESULTS"
    log "  → $local_dir"
done

# ── 4. Run analysis ───────────────────────────────────────────────────────────

log "Running plot_dp_cbpred_study.py …"
python3 "${SCRIPT_DIR}/analysis/plot_dp_cbpred_study.py" \
    --qmm    "${LOCAL_RESULTS}/qmm_dp_study_${DATE_TAG}" \
    --dpc3   "${LOCAL_RESULTS}/dpc3_dp_study_${DATE_TAG}" \
    --google "${LOCAL_RESULTS}/google_dp_study_${DATE_TAG}" \
    --out    "$OUT_DIR"

log "Done. Outputs in: $OUT_DIR"
log "  plot : ${OUT_DIR}/dp_cbpred_study.png"
log "  latex: ${OUT_DIR}/explanation.tex"
