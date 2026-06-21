#!/usr/bin/env python3
"""Generate compact threshold sensitivity plots (per-suite geomean only).

Removes lru_mid, focuses on QMM/Google/DPC3 only, compact layout.
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

def load_results(result_dir, policy_subdir):
    """Load IPC values from result directory."""
    ipcs = {}
    policy_dir = result_dir / policy_subdir
    if not policy_dir.exists():
        return ipcs

    for trace_dir in sorted(policy_dir.glob("srv_*")):
        champsim_out = trace_dir / "champsim.out"
        if champsim_out.exists():
            ipc = extract_ipc(champsim_out)
            if ipc:
                ipcs[trace_dir.name] = ipc
    return ipcs

def plot_threshold_sensitivity(base_dir, suite_names, baseline_dir, output_path):
    """Plot geomean speedup vs threshold (compact, per-suite only)."""
    thresholds = [1, 2, 4, 8, 16]

    fig, axes = plt.subplots(1, 3, figsize=(12, 3))
    fig.subplots_adjust(left=0.08, right=0.98, top=0.85, bottom=0.15, wspace=0.3)

    # Load shared baseline
    baseline_ipcs = load_results(baseline_dir, ".")
    if not baseline_ipcs:
        # Fallback: try loading from each result dir
        print("  Warning: baseline directory empty, will try per-suite baselines")

    for ax, suite_name, result_dir in zip(axes, suite_names, base_dir):
        # Load baseline (use shared baseline, fallback to per-suite)
        lru_ipcs = load_results(result_dir, "lru") or baseline_ipcs
        if not lru_ipcs:
            print(f"  No LRU data for {suite_name}")
            continue

        srrip_speedups = []
        srrip_live_speedups = []

        for thd in thresholds:
            # SRRIP baseline (constant across thresholds)
            srrip_ipcs = load_results(result_dir, "srrip")
            if srrip_ipcs:
                speedup = (geometric_mean([srrip_ipcs[k] / lru_ipcs[k]
                                          for k in srrip_ipcs if k in lru_ipcs]) - 1) * 100
                srrip_speedups.append(speedup)
            else:
                srrip_speedups.append(0)

            # SRRIP-Live at this threshold
            live_dir = result_dir / f"srrip_live_thd{thd}"
            if not live_dir.exists():
                live_dir = result_dir / f"srrip_live_mid{thd}"

            live_ipcs = {}
            if live_dir.exists():
                for trace_dir in sorted(live_dir.glob("srv_*")):
                    ipc = extract_ipc(trace_dir / "champsim.out")
                    if ipc:
                        live_ipcs[trace_dir.name] = ipc

            if live_ipcs:
                speedup = (geometric_mean([live_ipcs[k] / lru_ipcs[k]
                                          for k in live_ipcs if k in lru_ipcs]) - 1) * 100
                srrip_live_speedups.append(speedup)
            else:
                srrip_live_speedups.append(0)

        # Plot
        x = np.arange(len(thresholds))
        width = 0.35

        ax.bar(x - width/2, srrip_speedups, width, label="SRRIP", color="#1f77b4", alpha=0.8)
        ax.bar(x + width/2, srrip_live_speedups, width, label="SRRIP-Live", color="#2ca02c", alpha=0.8)

        ax.set_title(suite_name, fontweight="bold", fontsize=11)
        ax.set_xlabel("Threshold θ", fontsize=9)
        ax.set_ylabel("Speedup (%)", fontsize=9)
        ax.set_xticks(x)
        ax.set_xticklabels(thresholds, fontsize=8)
        ax.set_ylim(bottom=0)
        ax.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
        ax.grid(axis='y', alpha=0.3, linestyle='--', linewidth=0.5)
        ax.legend(fontsize=8, loc='upper left')
        ax.tick_params(labelsize=8)

    fig.suptitle("LLC Threshold Sensitivity", fontsize=12, fontweight="bold", y=0.98)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"✓ Saved: {output_path}")

def main():
    base_dir = Path("results")

    # Find result directories
    suites = ["qmm", "google", "dpc3"]
    suite_dirs = []
    suite_names = []

    for suite in suites:
        matches = list(base_dir.glob(f"{suite}_srrip_live_thd_pc_*"))
        if matches:
            suite_dirs.append(matches[0])
            suite_names.append(suite.upper())
            print(f"Found {suite}: {matches[0].name}")

    if not suite_dirs:
        print("ERROR: No result directories found!")
        return 1

    output_dir = base_dir / "plots"
    output_dir.mkdir(exist_ok=True)

    baseline_dir = base_dir / "baseline"

    print("\nGenerating threshold sensitivity plot...")
    plot_threshold_sensitivity(suite_dirs, suite_names, baseline_dir, output_dir / "srrip_live_thd_all_pc.png")

    print("✓ Done!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
