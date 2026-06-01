#!/usr/bin/env python3
"""Plot LLC threshold scaling for three-policy comparison.

Generates threshold sensitivity plots for:
- LRU baseline
- Standard SRRIP (no liveness)
- SRRIP-Live (liveness guidance in LLC)

Shows how SRRIP-Live performance varies across thresholds {1,2,4,8,16},
normalized against LRU baseline.
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
    """Load IPC results for a policy across traces and optionally thresholds."""
    results = {}

    if thresholds:
        # Threshold-sensitive policy (SRRIP-Live)
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
        # Threshold-insensitive policy (LRU, SRRIP)
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


def plot_suite(suite_name, result_dir, output_path):
    """Generate threshold scaling plot for a suite."""

    # Load results for all three policies
    lru_results = load_policy_results(result_dir, "lru_baseline")
    srrip_results = load_policy_results(result_dir, "srrip_default")
    srrip_live_results = load_policy_results(result_dir, "srrip_live_llc", thresholds=[1, 2, 4, 8, 16])

    if not lru_results or not srrip_results or not srrip_live_results:
        print(f"  {suite_name}: Missing data for one or more policies")
        return False

    # Extract LRU baseline (only one result, keyed by None)
    lru_ipcs = lru_results[None]
    lru_geomean = geometric_mean(lru_ipcs.values())

    # Extract SRRIP default (only one result, keyed by None)
    srrip_ipcs = srrip_results[None]
    srrip_geomean = geometric_mean(srrip_ipcs.values())

    # Extract SRRIP-Live results per threshold
    thresholds = sorted(srrip_live_results.keys())
    srrip_live_geomeans = []
    for thd in thresholds:
        ipcs = srrip_live_results[thd]
        # Use only common traces
        common_traces = set(lru_ipcs.keys()) & set(ipcs.keys())
        if common_traces:
            speedups = [ipcs[t] / lru_ipcs[t] for t in common_traces]
            geomean_speedup = geometric_mean(speedups)
            srrip_live_geomeans.append(geomean_speedup)
        else:
            srrip_live_geomeans.append(1.0)

    # Create plot
    fig, ax = plt.subplots(figsize=(10, 5))

    x = np.arange(len(thresholds))
    width = 0.25

    # Plot geomean speedups vs LRU
    lru_speedup = (srrip_geomean / lru_geomean - 1) * 100
    srrip_live_speedups = [(gm / lru_geomean - 1) * 100 for gm in srrip_live_geomeans]

    ax.bar(x - width/2, [lru_speedup] * len(thresholds), width, label="SRRIP", color="#1f77b4", alpha=0.8)
    ax.bar(x + width/2, srrip_live_speedups, width, label="SRRIP-Live", color="#2ca02c", alpha=0.8)

    ax.set_xlabel("Threshold (DoA classification)", fontsize=11)
    ax.set_ylabel("Speedup vs LRU (%)", fontsize=11)
    ax.set_title(f"{suite_name.upper()}: LLC Threshold Sensitivity", fontweight="bold", fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(thresholds)
    ax.axhline(y=0, color='k', linestyle='-', linewidth=0.8)
    ax.grid(axis='y', alpha=0.3, linestyle='--', linewidth=0.5)
    ax.legend(fontsize=10)
    ax.tick_params(labelsize=10)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"  {suite_name}: Saved to {output_path}")
    return True


def main():
    repo_root = Path(__file__).parent.parent.parent
    results_dir = repo_root / "results"
    plots_dir = results_dir / "plots"
    plots_dir.mkdir(exist_ok=True)

    suites = ["dpc3", "google", "qmm", "gap", "gms"]

    print("Generating LLC threshold scaling plots...\n")

    for suite in suites:
        suite_result_dir = results_dir / f"{suite}_policy_sweep_pc_20260601_0015"
        if not suite_result_dir.exists():
            print(f"  {suite}: Results directory not found")
            continue

        output_path = plots_dir / f"llc_threshold_scaling_{suite}.png"
        plot_suite(suite, suite_result_dir, output_path)

    print("\n✓ Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
