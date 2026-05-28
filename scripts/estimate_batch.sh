#!/usr/bin/env bash
# estimate_batch.sh — estimate wall-clock time for a pending job batch.
#
# Usage:
#   estimate_batch.sh <n_jobs> [<ref_results_dir>]
#
#   n_jobs          total array tasks being submitted
#   ref_results_dir local path to a completed result set whose median
#                   simulation time is used as the per-task estimate;
#                   if omitted, falls back to the most recently modified
#                   result directory under results/
#
# Prints a short human-readable summary to stdout.
# Exits 0 even if the estimate cannot be computed (prints a warning instead).

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

N_JOBS=${1:?"Usage: $(basename "$0") <n_jobs> [<ref_results_dir>]"}
REF_DIR=${2:-}

# ── 1. Resolve reference directory ──────────────────────────────────────────

if [ -z "$REF_DIR" ]; then
  REF_DIR=$(find "${PROJECT_ROOT}/results" -mindepth 2 -maxdepth 2 \
              -name "champsim.out" -printf "%h\n" 2>/dev/null \
            | head -1 | xargs dirname 2>/dev/null || true)
fi

# ── 2. Compute median simulation time (minutes) from reference results ───────

median_minutes() {
  local dir=$1
  python3 - "$dir" <<'PYEOF'
import sys, re, glob, statistics

def sim_minutes(path):
    last = None
    with open(path) as f:
        for line in f:
            if 'Simulation finished' in line:
                m = re.search(r'Simulation time: (\d+) hr (\d+) min (\d+) sec', line)
                if m:
                    last = int(m.group(1))*60 + int(m.group(2)) + int(m.group(3))/60
    return last

times = [t for f in glob.glob(f"{sys.argv[1]}/*/champsim.out")
         if (t := sim_minutes(f)) is not None]
if not times:
    sys.exit(1)
med = statistics.median(times)
print(f"{med:.2f}")
PYEOF
}

# ── 3. Query free cluster slots ──────────────────────────────────────────────

free_slots() {
  ssh -A otegby@abdet.inf.um.es -o BatchMode=yes -o ConnectTimeout=10 \
    "ssh otegby@castillo.inf.um.es 'qstat -g c 2>/dev/null'" \
    | awk '/all\.q/{print $5}' | head -1
}

# ── 4. Compute and print estimate ────────────────────────────────────────────

echo ""
echo "Batch estimate:"
echo "  Jobs submitted : ${N_JOBS}"

SLOTS=$(free_slots 2>/dev/null || true)
SLOTS=${SLOTS:-"?"}
echo "  Free slots     : ${SLOTS}"

if ! MED=$(median_minutes "$REF_DIR" 2>/dev/null); then
  echo "  Per-job time   : unknown (no reference results in ${REF_DIR:-results/})"
  echo "  Estimated total: unknown"
  echo ""
  exit 0
fi

MED_INT=$(printf '%.0f' "$MED")
REF_LABEL=$(basename "${REF_DIR%/}" 2>/dev/null || echo "unknown")

if [ "$SLOTS" = "?" ] || [ "$SLOTS" -eq 0 ] 2>/dev/null; then
  echo "  Per-job time   : ~${MED_INT} min  (median from ${REF_LABEL})"
  echo "  Estimated total: unknown (slot count unavailable)"
else
  python3 - "$N_JOBS" "$SLOTS" "$MED" "$REF_LABEL" <<'PYEOF'
import sys, math
n, slots, med, ref = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
waves = math.ceil(n / slots)
total_min = round(waves * med)
hrs, mins = divmod(total_min, 60)
print(f"  Per-job time   : ~{round(med)} min  (median from {ref})")
print(f"  Waves          : {waves}  ({n} jobs ÷ {slots} slots)")
if hrs:
    print(f"  Estimated total: ~{hrs}h {mins}m")
else:
    print(f"  Estimated total: ~{mins}m")
PYEOF
fi

echo ""
