#!/usr/bin/env bash
# estimate_batch.sh — estimate wall-clock time for a pending job batch.
#
# Usage:
#   estimate_batch.sh <n_jobs> [<ref_results_dir> [<save_dir>]]
#
#   n_jobs          total array tasks being submitted
#   ref_results_dir local path to a completed result set whose mean
#                   simulation time is used as the per-task estimate
#   save_dir        if given, writes .batch_estimate into this directory
#                   so report_batch.sh can compare actuals later

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

N_JOBS=${1:?"Usage: $(basename "$0") <n_jobs> [<ref_results_dir> [<save_dir>]]"}
REF_DIR=${2:-}
SAVE_DIR=${3:-}

# ── 1. Resolve reference directory ──────────────────────────────────────────

if [ -z "$REF_DIR" ]; then
  REF_DIR=$(find "${PROJECT_ROOT}/results" -mindepth 3 -maxdepth 3 \
              -name "champsim.out" -printf "%T@ %h\n" 2>/dev/null \
            | sort -n | tail -1 | awk '{print $2}' \
            | xargs dirname 2>/dev/null || true)
fi

# ── 2. Compute mean simulation time (minutes) from reference results ─────────

mean_minutes() {
  python3 - "$1" <<'PYEOF'
import sys, re, glob, statistics

def sim_minutes(path):
    with open(path) as f:
        for line in f:
            if 'Simulation finished' in line:
                m = re.search(r'Simulation time: (\d+) hr (\d+) min (\d+) sec', line)
                if m:
                    return int(m.group(1))*60 + int(m.group(2)) + int(m.group(3))/60
    return None

times = [t for f in glob.glob(f"{sys.argv[1]}/*/champsim.out")
         if (t := sim_minutes(f)) is not None]
if not times:
    sys.exit(1)
print(f"{statistics.mean(times):.2f}")
PYEOF
}

# ── 3. Query working cluster slots (USED + AVAIL) ────────────────────────────

max_slots() {
  ssh -A otegby@abdet.inf.um.es -o BatchMode=yes -o ConnectTimeout=10 \
    "ssh otegby@castillo.inf.um.es 'qstat -g c 2>/dev/null'" \
    | awk '/all\.q/{print $3 + $5}' | head -1
}

# ── 4. Compute estimate ──────────────────────────────────────────────────────

SLOTS=$(max_slots 2>/dev/null || true)
SLOTS=${SLOTS:-0}
REF_LABEL=$(basename "${REF_DIR%/}" 2>/dev/null || echo "unknown")

AVG=0
EST_MIN=0
WAVES=0
if AVG=$(mean_minutes "$REF_DIR" 2>/dev/null) && [ "$SLOTS" -gt 0 ]; then
  read -r WAVES EST_MIN < <(python3 - "$N_JOBS" "$SLOTS" "$AVG" <<'PYEOF'
import sys, math
n, slots, avg = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
waves = math.ceil(n / slots)
print(waves, round(waves * avg))
PYEOF
)
fi

# ── 5. Print summary ─────────────────────────────────────────────────────────

echo ""
echo "Batch estimate:"
echo "  Jobs submitted : ${N_JOBS}"
echo "  Max parallel   : ${SLOTS}"
if [ "$AVG" = "0" ] || [ -z "$AVG" ]; then
  echo "  Per-job time   : unknown (no reference results)"
  echo "  Estimated total: unknown"
else
  AVG_INT=$(printf '%.0f' "$AVG")
  HRS=$(( EST_MIN / 60 ))
  MINS=$(( EST_MIN % 60 ))
  echo "  Per-job time   : ~${AVG_INT} min  (mean from ${REF_LABEL})"
  echo "  Waves          : ${WAVES}  (${N_JOBS} jobs ÷ ${SLOTS} slots)"
  if [ "$HRS" -gt 0 ]; then
    echo "  Estimated total: ~${HRS}h ${MINS}m"
  else
    echo "  Estimated total: ~${MINS}m"
  fi
fi
echo ""

# ── 6. Save estimate for later comparison ────────────────────────────────────

if [ -n "$SAVE_DIR" ] && [ "$EST_MIN" -gt 0 ]; then
  mkdir -p "$SAVE_DIR"
  cat > "${SAVE_DIR}/.batch_estimate" <<EOF
submitted_at=$(date +%s)
n_jobs=${N_JOBS}
max_parallel=${SLOTS}
avg_duration_min=${AVG}
estimated_total_min=${EST_MIN}
reference_dir=${REF_DIR}
EOF
fi
