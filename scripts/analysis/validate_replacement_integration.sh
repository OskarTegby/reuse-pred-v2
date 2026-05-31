#!/usr/bin/env bash
# validate_replacement_integration.sh — Compare validation vs baseline (both from cluster)
#
# Workflow:
# 1. Download both validation and baseline results from cluster
# 2. Extract geomean IPC for each threshold
# 3. Compare results between branches
# 4. Verify new approach matches original ~8% speedup
# 5. Generate comparison report

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Configuration
VALIDATION_DIR="${1:-qmm_validate_srrip_live_20260531_1948}"
BASELINE_DIR="${2:-qmm_baseline_srrip_live_20260531_2126}"

echo "=========================================="
echo "Validation Results Comparison"
echo "=========================================="
echo ""
echo "Validation: $VALIDATION_DIR (liveness-guided-replacement)"
echo "Baseline:   $BASELINE_DIR (liveness-replacement)"
echo ""

# Check if results are local; download if not
for dir in "$VALIDATION_DIR" "$BASELINE_DIR"; do
  if [ ! -d "$PROJECT_ROOT/results/$dir" ]; then
    echo "Downloading $dir from cluster..."
    bash "$SCRIPT_DIR/../download_validation.sh" "$dir"
  fi
done

# Extract and compare geomeans
echo "Extracting and comparing geomean IPC..."
echo ""

python3 << 'PYTHON'
import json
import sys
from pathlib import Path
from statistics import geometric_mean

def read_results(result_dir):
    """Read all trace results from directory structure."""
    ipcs = {}
    for trace_dir in sorted(result_dir.glob("srv_*")):
        trace_name = trace_dir.name
        stat_file = trace_dir / "stats.json"
        if stat_file.exists():
            try:
                with open(stat_file) as f:
                    data = json.load(f)
                    ipc = None
                    for key in ["sim_IPC", "CPU0_IPC", "IPC"]:
                        if key in data:
                            ipc = float(data[key])
                            break
                    if ipc is not None:
                        ipcs[trace_name] = ipc
            except Exception:
                pass
    return ipcs

results_dir = Path("results")
validation_dir = results_dir / sys.argv[1]
baseline_dir = results_dir / sys.argv[2]

print("BASELINE (liveness-replacement branch):")
baseline_ipcs = {}
for thd in [4, 8]:
    thd_dir = baseline_dir / f"srrip_live_mid{thd}"
    if thd_dir.exists():
        ipcs = read_results(thd_dir)
        if ipcs:
            gm = geometric_mean(ipcs.values())
            baseline_ipcs[thd] = gm
            print(f"  MID_THD={thd}: {gm:.4f} ({len(ipcs)} traces)")

print()
print("VALIDATION (liveness-guided-replacement branch):")
validation_ipcs = {}
for thd in [4, 8]:
    thd_dir = validation_dir / f"srrip_live_mid{thd}"
    if thd_dir.exists():
        ipcs = read_results(thd_dir)
        if ipcs:
            gm = geometric_mean(ipcs.values())
            validation_ipcs[thd] = gm
            print(f"  MID_THD={thd}: {gm:.4f} ({len(ipcs)} traces)")

print()
print("COMPARISON (per threshold):")
for thd in [4, 8]:
    if thd in baseline_ipcs and thd in validation_ipcs:
        base = baseline_ipcs[thd]
        val = validation_ipcs[thd]
        diff_pct = ((val - base) / base) * 100
        match = "✓" if abs(diff_pct) < 2 else "⚠"
        print(f"  THD={thd}: baseline={base:.4f}, validation={val:.4f}, diff={diff_pct:+.2f}% {match}")

print()
if validation_ipcs and baseline_ipcs:
    # Find optimal threshold for each
    opt_baseline_thd = max(baseline_ipcs, key=baseline_ipcs.get)
    opt_validation_thd = max(validation_ipcs, key=validation_ipcs.get)

    base_best = baseline_ipcs[opt_baseline_thd]
    val_best = validation_ipcs[opt_validation_thd]

    print("SUMMARY:")
    print(f"  Baseline optimal:   THD={opt_baseline_thd}, geomean={base_best:.4f}")
    print(f"  Validation optimal: THD={opt_validation_thd}, geomean={val_best:.4f}")

    if base_best > 0:
        diff_pct = ((val_best - base_best) / base_best) * 100
        print(f"  Difference: {diff_pct:+.2f}%")

        if abs(diff_pct) < 2:
            print("  ✓ Results match within 2% — implementation validated")
        elif diff_pct < -5:
            print("  ✗ Results diverge significantly — investigate 2-class vs 3-class design")
        else:
            print(f"  ~ Results close enough ({diff_pct:+.2f}%)")

PYTHON
