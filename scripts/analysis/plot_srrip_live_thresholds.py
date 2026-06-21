#!/usr/bin/env python3
"""Plot SRRIP-Live threshold sensitivity across all suites.

Shows geomean speedup vs threshold (1,2,4,8,16) for each suite.
Uses LRU baseline from corr_baseline_20260528 directories.
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

def main():
    results_dir = Path("results")
    baseline_root = results_dir / "corr_baseline_20260528"

    # Find all suite threshold directories
    suite_dirs = {}
    for d in sorted(results_dir.glob("*_srrip_live_thd_pc_*")):
        suite_name = d.name.split("_srrip_live_thd")[0]
        if suite_name not in suite_dirs:
            suite_dirs[suite_name] = d

    if not suite_dirs:
        print("ERROR: No threshold directories found!")
        return 1

    thresholds = [1, 2, 4, 8, 16]
    num_suites = len(suite_dirs)
    num_cols = min(4, num_suites)
    num_rows = (num_suites + num_cols - 1) // num_cols

    fig, axes = plt.subplots(num_rows, num_cols, figsize=(14, 3.5 * num_rows))
    if num_suites == 1:
        axes = [axes]
    else:
        axes = axes.flatten()

    print(f"Found {num_suites} suites: {', '.join(sorted(suite_dirs.keys()))}")

    for idx, (suite_name, thd_dir) in enumerate(sorted(suite_dirs.items())):
        ax = axes[idx]

        speedups = []
        all_ipcs = {}  # Store IPC values for each threshold

        # Load SRRIP-Live results at all thresholds
        for thd in thresholds:
            live_dir = thd_dir / f"srrip_live_thd{thd}"
            if not live_dir.exists():
                live_dir = thd_dir / f"srrip_live_mid{thd}"

            live_ipcs = load_ipcs(live_dir)
            if live_ipcs:
                all_ipcs[thd] = live_ipcs

        if not all_ipcs:
            print(f"  {suite_name}: No SRRIP-Live data found")
            ax.text(0.5, 0.5, "No data", ha='center', va='center', transform=ax.transAxes)
            continue

        # Use θ=1 as reference point, compute improvement at other thresholds
        baseline_ipcs = all_ipcs.get(1)
        if not baseline_ipcs:
            print(f"  {suite_name}: No θ=1 baseline")
            ax.text(0.5, 0.5, "No θ=1", ha='center', va='center', transform=ax.transAxes)
            continue

        for thd in thresholds:
            if thd in all_ipcs:
                live_ipcs = all_ipcs[thd]
                common_keys = set(live_ipcs.keys()) & set(baseline_ipcs.keys())
                if common_keys:
                    speedup = (geometric_mean([live_ipcs[k] / baseline_ipcs[k]
                                              for k in common_keys]) - 1) * 100
                    speedups.append(speedup)
                    print(f"  {suite_name} θ={thd}: {speedup:+.1f}% vs θ=1")
                else:
                    speedups.append(0)
            else:
                speedups.append(0)

        # Plot
        x = np.arange(len(thresholds))
        width = 0.6

        ax.bar(x, speedups, width, color="#2ca02c", alpha=0.8)

        ax.set_title(suite_name.upper(), fontweight="bold", fontsize=11)
        ax.set_xlabel("Threshold θ", fontsize=10)
        ax.set_ylabel("Speedup (%)", fontsize=10)
        ax.set_xticks(x)
        ax.set_xticklabels(thresholds, fontsize=9)
        ax.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
        ax.grid(axis='y', alpha=0.3, linestyle='--', linewidth=0.5)
        ax.tick_params(labelsize=9)

        # Add value labels on bars
        for i, v in enumerate(speedups):
            if v != 0:
                ax.text(i, v + (0.3 if v > 0 else -0.5), f"{v:.1f}%",
                       ha='center', va='bottom' if v > 0 else 'top', fontsize=8)

    # Hide unused subplots
    for idx in range(num_suites, len(axes)):
        axes[idx].set_visible(False)

    fig.suptitle("SRRIP-Live Threshold Sensitivity: Improvement Relative to θ=1",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()

    output_path = results_dir / "plots" / "srrip_live_thd_all_pc.png"
    output_path.parent.mkdir(exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"\n✓ Saved: {output_path}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
