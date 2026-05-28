#!/usr/bin/env bash
# report_batch.sh — compare estimated vs actual duration for a completed batch.
#
# Usage:
#   report_batch.sh <results_dir>
#
#   results_dir  the top-level result directory for the sweep
#                (must contain .batch_estimate written by estimate_batch.sh)

set -euo pipefail

RESULTS_DIR=${1:?"Usage: $(basename "$0") <results_dir>"}
ESTIMATE_FILE="${RESULTS_DIR}/.batch_estimate"

if [ ! -f "$ESTIMATE_FILE" ]; then
  echo "No .batch_estimate found in ${RESULTS_DIR}" >&2
  echo "Was this batch submitted via a sweep script?" >&2
  exit 1
fi

# Read estimate metadata
source "$ESTIMATE_FILE"

# Compute actual mean job duration from all champsim.out files
read -r ACTUAL_AVG ACTUAL_N < <(python3 - "$RESULTS_DIR" <<'PYEOF'
import sys, re, glob, statistics

def sim_minutes(path):
    with open(path) as f:
        for line in f:
            if 'Simulation finished' in line:
                m = re.search(r'Simulation time: (\d+) hr (\d+) min (\d+) sec', line)
                if m:
                    return int(m.group(1))*60 + int(m.group(2)) + int(m.group(3))/60
    return None

times = [t for f in glob.glob(f"{sys.argv[1]}/*/*/champsim.out")
         if (t := sim_minutes(f)) is not None]
if not times:
    print("0 0")
else:
    print(f"{statistics.mean(times):.2f} {len(times)}")
PYEOF
)

# Compute actual wall-clock time from submit timestamp to last champsim.out mtime
LAST_MTIME=$(find "$RESULTS_DIR" -name "champsim.out" -printf "%T@\n" 2>/dev/null \
             | sort -n | tail -1 | cut -d. -f1)
ACTUAL_WALL_MIN=0
if [ -n "$LAST_MTIME" ] && [ "${submitted_at:-0}" -gt 0 ]; then
  ACTUAL_WALL_MIN=$(( (LAST_MTIME - submitted_at) / 60 ))
fi

# Report
python3 - \
  "$n_jobs" "$max_parallel" \
  "$avg_duration_min" "$estimated_total_min" \
  "$ACTUAL_AVG" "$ACTUAL_N" "$ACTUAL_WALL_MIN" \
  "$RESULTS_DIR" <<'PYEOF'
import sys

n_jobs       = int(sys.argv[1])
max_par      = int(sys.argv[2])
est_avg      = float(sys.argv[3])
est_total    = int(sys.argv[4])
act_avg      = float(sys.argv[5])
act_n        = int(sys.argv[6])
act_wall     = int(sys.argv[7])
label        = sys.argv[8].rstrip("/").split("/")[-1]

def fmt(mins):
    h, m = divmod(int(mins), 60)
    return f"{h}h {m}m" if h else f"{m}m"

def pct_err(est, act):
    if act == 0: return "n/a"
    return f"{(est - act) / act * 100:+.0f}%"

print()
print(f"Batch report: {label}")
print(f"  Jobs             : {n_jobs}  (actuals from {act_n} completed)")
print(f"  Max parallel     : {max_par}")
print()
print(f"  Per-job duration : estimated ~{round(est_avg)} min  →  actual ~{round(act_avg)} min  "
      f"(error {pct_err(est_avg, act_avg)})")
print(f"  Wall-clock total : estimated  {fmt(est_total)}  →  actual  {fmt(act_wall)}  "
      f"(error {pct_err(est_total, act_wall)})")
print()
PYEOF
