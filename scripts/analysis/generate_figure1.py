#!/usr/bin/env python3
"""Generate Figure 1: Threshold sensitivity across all benchmark suites.

Shows SRRIP-Live speedup vs threshold, per suite, using per-suite baseline.
"""

import sys
from pathlib import Path
from statistics import geometric_mean

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

def extract_ipc(champsim_out):
    """Extract final IPC from champsim.out."""
    if not champsim_out.exists():
        return None
    try:
        with open(champsim_out) as f:
            ipc_value = None
            for line in f:
                if "cumulative IPC:" in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if "IPC:" in part and i + 1 < len(parts):
                            ipc_value = float(parts[i + 1])
            return ipc_value
    except:
        pass
    return None

def load_ipcs(policy_dir):
    """Load all IPC values from a policy directory."""
    ipcs = {}
    if not policy_dir.exists():
        return ipcs

    for trace_dir in sorted(policy_dir.iterdir()):
        if trace_dir.is_dir():
            ipc = extract_ipc(trace_dir / "champsim.out")
            if ipc:
                ipcs[trace_dir.name] = ipc
    return ipcs

def find_baseline(suite_name, results_dir):
    """Find baseline LRU results for this suite."""
    # QMM uses the generic baseline directory
    if suite_name == "qmm":
        baseline_dir = results_dir / "baseline"
        if baseline_dir.exists():
            return load_ipcs(baseline_dir)

    # Others use per-suite corr_baseline
    baseline_dir = results_dir / "corr_baseline_20260528" / suite_name
    if baseline_dir.exists():
        return load_ipcs(baseline_dir)

    return {}

def plot_all_suites(results_dir, output_path):
    """Generate comprehensive threshold sensitivity plot for all suites."""

    # Find all suite directories
    suite_dirs = {}
    for d in sorted(results_dir.glob("*_srrip_live_thd*")):
        suite_name = d.name.split("_srrip_live_thd")[0]
        if suite_name not in suite_dirs:
            suite_dirs[suite_name] = d

    if not suite_dirs:
        print("ERROR: No result directories found!")
        return False

    thresholds = [1, 2, 4, 8, 16]

    print(f"Found {len(suite_dirs)} benchmark suites: {', '.join(sorted(suite_dirs.keys()))}")

    # Determine number of subplots (2 rows x 4 cols = 8 suites max)
    num_suites = len(suite_dirs)
    num_cols = min(4, num_suites)
    num_rows = (num_suites + num_cols - 1) // num_cols

    fig, axes = plt.subplots(num_rows, num_cols, figsize=(14, 3.5 * num_rows))
    if num_suites == 1:
        axes = [axes]
    else:
        axes = axes.flatten()

    for idx, (suite_name, result_dir) in enumerate(sorted(suite_dirs.items())):
        ax = axes[idx]

        # Get baseline for this suite
        baseline_ipcs = find_baseline(suite_name, results_dir)
        if not baseline_ipcs:
            print(f"  {suite_name}: No baseline found, skipping")
            ax.text(0.5, 0.5, "No data", ha='center', va='center', transform=ax.transAxes)
            continue

        srrip_live_speedups = []

        for thd in thresholds:
            # SRRIP-Live at this threshold
            live_dir = result_dir / f"srrip_live_thd{thd}"
            if not live_dir.exists():
                live_dir = result_dir / f"srrip_live_mid{thd}"

            live_ipcs = load_ipcs(live_dir)

            if live_ipcs and baseline_ipcs:
                # Find common workloads between live results and baseline
                common_keys = set(live_ipcs.keys()) & set(baseline_ipcs.keys())
                if common_keys:
                    speedup = (geometric_mean([live_ipcs[k] / baseline_ipcs[k]
                                              for k in common_keys]) - 1) * 100
                    srrip_live_speedups.append(speedup)
                else:
                    # No common workloads - data mismatch
                    srrip_live_speedups.append(0)
            else:
                srrip_live_speedups.append(0)

        # Plot this suite
        x = np.arange(len(thresholds))
        width = 0.6

        ax.bar(x, srrip_live_speedups, width, label="SRRIP-Live",
               color="#2ca02c", alpha=0.8)

        ax.set_title(suite_name.upper(), fontweight="bold", fontsize=10)
        ax.set_xlabel("Threshold θ", fontsize=9)
        ax.set_ylabel("Speedup (%)", fontsize=9)
        ax.set_xticks(x)
        ax.set_xticklabels(thresholds, fontsize=8)
        ax.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
        ax.grid(axis='y', alpha=0.3, linestyle='--', linewidth=0.5)
        ax.tick_params(labelsize=8)

        # Add data labels on bars
        for i, v in enumerate(srrip_live_speedups):
            if v != 0:
                ax.text(i, v + 0.1, f"{v:.1f}%", ha='center', va='bottom', fontsize=7)

    # Hide unused subplots
    for idx in range(num_suites, len(axes)):
        axes[idx].set_visible(False)

    fig.suptitle("SRRIP-Live Threshold Sensitivity: Geomean Speedup per Suite",
                 fontsize=12, fontweight="bold")
    fig.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"✓ Saved: {output_path}")
    return True

def main():
    repo_root = Path(__file__).parent.parent.parent
    results_dir = repo_root / "results"
    output_dir = results_dir / "plots"

    output_dir.mkdir(exist_ok=True)

    print("Generating Figure 1: Threshold Sensitivity...")
    success = plot_all_suites(results_dir, output_dir / "srrip_live_thd_all_pc.png")

    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
