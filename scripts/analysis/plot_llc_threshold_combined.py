#!/usr/bin/env python3
"""Generate combined LLC threshold scaling plot for Figure 1.

Creates a 2x3 grid showing three-policy comparison across 5 completed suites:
- DPC3, Google, QMM, GAP, GMS

Each subplot shows:
- SRRIP (blue): constant across thresholds
- SRRIP-Live (green): varies across thresholds 1,2,4,8,16
- All normalized against LRU baseline
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


def load_policy_results(result_dir, policy_name, thresholds=None):
    """Load IPC results for a policy."""
    results = {}

    if thresholds:
        for thd in thresholds:
            thd_dir = result_dir / f"{policy_name}/thd{thd}"
            ipcs = {}
            if thd_dir.exists():
                for trace_dir in sorted(thd_dir.iterdir()):
                    if trace_dir.is_dir():
                        ipc = extract_ipc(trace_dir / "champsim.out")
                        if ipc:
                            ipcs[trace_dir.name] = ipc
            if ipcs:
                results[thd] = ipcs
    else:
        policy_dir = result_dir / policy_name
        ipcs = {}
        if policy_dir.exists():
            for trace_dir in sorted(policy_dir.iterdir()):
                if trace_dir.is_dir():
                    ipc = extract_ipc(trace_dir / "champsim.out")
                    if ipc:
                        ipcs[trace_dir.name] = ipc
        if ipcs:
            results[None] = ipcs

    return results


def main():
    repo_root = Path(__file__).parent.parent.parent
    results_dir = repo_root / "results"
    plots_dir = results_dir / "plots"

    suites = ["dpc3", "google", "qmm", "gap", "gms"]

    # Create 2x3 grid (5 suites fit in 2x3, last slot empty)
    fig, axes = plt.subplots(2, 3, figsize=(14, 8))
    axes = axes.flatten()

    print("Generating combined LLC threshold scaling plot...\n")

    for idx, suite in enumerate(suites):
        suite_result_dir = results_dir / f"{suite}_policy_sweep_pc_20260601_0015"

        if not suite_result_dir.exists():
            print(f"  {suite}: Results directory not found")
            continue

        # Load results
        lru_results = load_policy_results(suite_result_dir, "lru_baseline")
        srrip_results = load_policy_results(suite_result_dir, "srrip_default")
        srrip_live_results = load_policy_results(suite_result_dir, "srrip_live_llc",
                                                  thresholds=[1, 2, 4, 8, 16])

        if not lru_results or not srrip_results or not srrip_live_results:
            print(f"  {suite}: Missing data")
            continue

        # Extract LRU baseline
        lru_ipcs = lru_results[None]
        lru_geomean = geometric_mean(lru_ipcs.values())

        # Extract SRRIP default
        srrip_ipcs = srrip_results[None]
        srrip_geomean = geometric_mean(srrip_ipcs.values())

        # Extract SRRIP-Live per threshold
        thresholds = sorted(srrip_live_results.keys())
        srrip_live_geomeans = []
        for thd in thresholds:
            ipcs = srrip_live_results[thd]
            common_traces = set(lru_ipcs.keys()) & set(ipcs.keys())
            if common_traces:
                speedups = [ipcs[t] / lru_ipcs[t] for t in common_traces]
                geomean_speedup = geometric_mean(speedups)
                srrip_live_geomeans.append(geomean_speedup)
            else:
                srrip_live_geomeans.append(1.0)

        # Plot
        ax = axes[idx]
        x = np.arange(len(thresholds))
        width = 0.25

        lru_speedup = (srrip_geomean / lru_geomean - 1) * 100
        srrip_live_speedups = [(gm / lru_geomean - 1) * 100 for gm in srrip_live_geomeans]

        ax.bar(x - width/2, [lru_speedup] * len(thresholds), width,
               label="SRRIP", color="#1f77b4", alpha=0.8)
        ax.bar(x + width/2, srrip_live_speedups, width,
               label="SRRIP-Live", color="#2ca02c", alpha=0.8)

        ax.set_xlabel("Threshold $\\theta$", fontsize=10)
        ax.set_ylabel("Speedup vs LRU (%)", fontsize=10)
        ax.set_title(suite.upper(), fontweight="bold", fontsize=11)
        ax.set_xticks(x)
        ax.set_xticklabels(thresholds)
        ax.axhline(y=0, color='k', linestyle='-', linewidth=0.8)
        ax.grid(axis='y', alpha=0.3, linestyle='--', linewidth=0.5)
        ax.tick_params(labelsize=9)

        if idx == 0:
            ax.legend(fontsize=9, loc='upper left')

        print(f"  {suite}: Plotted")

    # Hide empty subplot
    axes[5].set_visible(False)

    fig.suptitle("LLC Threshold Sensitivity: Three-Policy Comparison",
                 fontsize=13, fontweight="bold", y=0.98)
    plt.tight_layout(rect=[0, 0, 1, 0.97])

    output_path = plots_dir / "llc_threshold_combined.png"
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"\n✓ Saved combined plot to: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
