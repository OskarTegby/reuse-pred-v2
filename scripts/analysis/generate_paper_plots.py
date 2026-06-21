#!/usr/bin/env python3
"""Generate publication-quality plots for HPCA paper.

Handles:
- QMM (srv_* traces, SRRIP-Live)
- Google (srv_* traces, SRRIP-Live)
- DPC3 (srv_* traces, SRRIP-Live)
- GMS (gms.*.champsimtrace, IPV-Live with STLB)
- Ligra (ligra.*.champsimtrace, IPV-Live with STLB)

Key features:
- Aggressive trace name shortening (saves 40%+ space)
- Removes deprecated policies
- Per-suite geomean view
- Per-workload sorted view
"""

import json
import math
import re
import sys
from pathlib import Path
from statistics import geometric_mean

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Publication colors
COLOR_SRRIP = "#1f77b4"
COLOR_SRRIP_LIVE = "#2ca02c"
COLOR_IPV_LIVE = "#d62728"

def extract_ipc(champsim_out):
    """Extract final IPC from champsim.out (handles multiple formats)."""
    if not champsim_out.exists():
        return None
    try:
        with open(champsim_out) as f:
            # Read entire file to get last relevant line
            ipc_value = None
            for line in f:
                # Format 1: "sim_IPC: X.XXXXX"
                if "sim_IPC" in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if "sim_IPC" in part or i == len(parts) - 1:
                            try:
                                ipc_value = float(parts[-1])
                            except:
                                pass
                # Format 2: "CPU 0 cumulative IPC: X.XXXXX instructions: ..."
                elif "cumulative IPC:" in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if "IPC:" in part and i + 1 < len(parts):
                            try:
                                ipc_value = float(parts[i + 1])
                            except:
                                pass
            return ipc_value
    except:
        pass
    return None

def shorten_trace_name(full_name):
    """
    Aggressively shorten trace names to 2-4 chars.

    Examples:
    - srv_7 → 7
    - srv_743 → 743
    - srv_s10 → s10
    - gms.k_clique_count_set_based.soc-pokec-relationships.slice-4.champsimtrace → g4
    - gms.triangle_count.soc-pokec-relationships.slice-360.champsimtrace → gt360
    - ligra.bfs.twitter.slice-100.champsimtrace → lb100
    """
    # Handle srv_* format
    if full_name.startswith("srv_"):
        return full_name[4:]

    # Handle GMS format: gms.ALGO.GRAPH.slice-N.champsimtrace
    if full_name.startswith("gms."):
        # Extract algorithm and slice number
        parts = full_name.split(".")
        if len(parts) >= 5:
            algo = parts[1]  # e.g., "k_clique_count_set_based"
            slice_num = parts[3].split("-")[-1]  # e.g., "4"

            # Shorten algorithm to 1-2 chars
            if algo.startswith("k_clique"):
                algo_short = "k" if algo.startswith("k_clique_count") else "kc"
            elif algo.startswith("maximal_clique"):
                algo_short = "mc"
            elif algo.startswith("triangle"):
                algo_short = "t"
            else:
                algo_short = algo[0]

            # Return algo+slice (e.g., "g4", "t360")
            return f"g{algo_short}{slice_num}"

    # Handle Ligra format: ligra.ALGO.GRAPH.slice-N.champsimtrace
    if full_name.startswith("ligra."):
        parts = full_name.split(".")
        if len(parts) >= 5:
            algo = parts[1]  # e.g., "bfs", "pagerank"
            slice_num = parts[3].split("-")[-1]

            # Shorten algorithm
            algo_short = algo[0:2]  # First 2 chars: "bf", "pa", etc.
            return f"l{algo_short}{slice_num}"

    # Fallback: keep first 4 chars
    return full_name[:4]

def find_result_dirs(base_dir):
    """Find all result directories and group by suite type."""
    results = {
        "qmm": None,
        "google": None,
        "dpc3": None,
        "gms": None,
        "ligra": None,
    }

    base_dir = Path(base_dir)

    # Look for SRRIP-Live directories (QMM, Google, DPC3)
    for suite in ["qmm", "google", "dpc3"]:
        matches = list(base_dir.glob(f"{suite}_srrip_live_thd_pc_*"))
        if matches:
            results[suite] = matches[0]
            print(f"Found {suite}: {matches[0].name}")

    # Look for IPV-Live directories (GMS, Ligra)
    for suite in ["gms", "ligra"]:
        matches = list(base_dir.glob(f"{suite}_*_ipv_live_thd*"))
        if matches:
            results[suite] = matches[0]
            print(f"Found {suite}: {matches[0].name}")

    return results

def load_suite_results(result_dir, policy_name, thd=None):
    """Load IPC values for a policy/threshold."""
    # Handle different naming conventions
    if policy_name == "lru":
        policy_dir = result_dir / "lru"
    elif policy_name == "srrip":
        policy_dir = result_dir / "srrip"
    elif policy_name == "srrip_live":
        if thd is not None:
            # Try both naming conventions: srrip_live_mid{thd} and srrip_live_thd{thd}
            policy_dir = result_dir / f"srrip_live_mid{thd}"
            if not policy_dir.exists():
                policy_dir = result_dir / f"srrip_live_thd{thd}"
        else:
            policy_dir = result_dir / "srrip_live"
    elif policy_name.startswith("stlb_"):
        # For STLB: stlb_ipv_live_thd1, stlb_ipv_live_thd2, etc.
        if thd is not None:
            policy_dir = result_dir / f"stlb_{policy_name[5:]}_thd{thd}"
        else:
            policy_dir = result_dir / f"stlb_{policy_name[5:]}"
    elif policy_name.startswith("ipv_live"):
        if thd is not None:
            policy_dir = result_dir / f"ipv_live_mid{thd}"
        else:
            policy_dir = result_dir / "ipv_live"
    else:
        policy_dir = result_dir / policy_name

    if not policy_dir.exists():
        return {}

    ipcs = {}

    # Handle srv_* naming (QMM, Google, DPC3)
    for trace_dir in sorted(policy_dir.glob("srv_*")):
        ipc = extract_ipc(trace_dir / "champsim.out")
        if ipc:
            trace_id = shorten_trace_name(trace_dir.name)
            ipcs[trace_id] = ipc

    # Handle gms.* naming
    for trace_dir in sorted(policy_dir.glob("gms.*")):
        ipc = extract_ipc(trace_dir / "champsim.out")
        if ipc:
            trace_id = shorten_trace_name(trace_dir.name)
            ipcs[trace_id] = ipc

    # Handle ligra.* naming
    for trace_dir in sorted(policy_dir.glob("ligra.*")):
        ipc = extract_ipc(trace_dir / "champsim.out")
        if ipc:
            trace_id = shorten_trace_name(trace_dir.name)
            ipcs[trace_id] = ipc

    return ipcs

def load_baseline_results(baseline_dir):
    """Load baseline LRU results from baseline directory."""
    ipcs = {}
    for trace_dir in sorted(baseline_dir.glob("srv_*")):
        ipc = extract_ipc(trace_dir / "champsim.out")
        if ipc:
            trace_id = shorten_trace_name(trace_dir.name)
            ipcs[trace_id] = ipc
    return ipcs

def plot_threshold_sensitivity(base_dir, suite_name, cache_level="LLC", baseline_dir=None):
    """Plot: Geomean IPC vs threshold (per-suite)."""
    thresholds = [1, 2, 4, 8, 16]

    # Try to load baseline from suite dir, fallback to baseline_dir
    lru_ipcs = load_suite_results(base_dir, "lru")
    if not lru_ipcs and baseline_dir:
        lru_ipcs = load_baseline_results(baseline_dir)

    if not lru_ipcs:
        print(f"  No LRU data for {suite_name}")
        return None

    # For SRRIP-Live on LLC
    if cache_level == "LLC":
        srrip_geomeans = []
        srrip_live_geomeans = []

        for thd in thresholds:
            srrip_ipcs = load_suite_results(base_dir, "srrip")
            srrip_live_ipcs = load_suite_results(base_dir, "srrip_live", thd)

            if srrip_ipcs:
                speedup = geometric_mean([srrip_ipcs[k] / lru_ipcs[k]
                                         for k in srrip_ipcs if k in lru_ipcs]) - 1
                srrip_geomeans.append(speedup * 100)
            else:
                srrip_geomeans.append(0)

            if srrip_live_ipcs:
                speedup = geometric_mean([srrip_live_ipcs[k] / lru_ipcs[k]
                                         for k in srrip_live_ipcs if k in lru_ipcs]) - 1
                srrip_live_geomeans.append(speedup * 100)
            else:
                srrip_live_geomeans.append(0)

        return {
            "thresholds": thresholds,
            "srrip": srrip_geomeans,
            "srrip_live": srrip_live_geomeans,
        }

    return None

def plot_per_workload(base_dir, suite_name, policy="srrip_live", thd=4):
    """Plot: Per-workload speedup at optimal threshold."""
    lru_ipcs = load_suite_results(base_dir, "lru")
    policy_ipcs = load_suite_results(base_dir, policy, thd)
    baseline_ipcs = load_suite_results(base_dir, "srrip")

    if not (lru_ipcs and policy_ipcs):
        print(f"  No data for {suite_name}")
        return None

    speedups = []
    speedups_baseline = []
    names = []

    for trace_id in sorted(set(policy_ipcs.keys()) & set(lru_ipcs.keys())):
        names.append(trace_id)
        speedups.append((policy_ipcs[trace_id] / lru_ipcs[trace_id] - 1) * 100)

        if trace_id in baseline_ipcs:
            speedups_baseline.append((baseline_ipcs[trace_id] / lru_ipcs[trace_id] - 1) * 100)
        else:
            speedups_baseline.append(0)

    # Sort by policy speedup (descending)
    sorted_idx = sorted(range(len(speedups)), key=lambda i: speedups[i], reverse=True)

    return {
        "names": [names[i] for i in sorted_idx],
        "speedups": [speedups[i] for i in sorted_idx],
        "speedups_baseline": [speedups_baseline[i] for i in sorted_idx],
    }

def create_threshold_plot(data_dict, suite_names, output_path, cache_level="LLC"):
    """Create threshold sensitivity plot (3 subplots)."""
    fig, axes = plt.subplots(1, 3, figsize=(14, 3.5))
    fig.suptitle(f"{cache_level} Threshold Sensitivity: Geomean Speedup",
                 fontsize=12, fontweight="bold")

    for ax, suite_name in zip(axes, suite_names):
        data = data_dict.get(suite_name)
        if not data:
            ax.text(0.5, 0.5, f"No data", ha='center', va='center')
            continue

        x = np.arange(len(data["thresholds"]))
        width = 0.35

        ax.bar(x - width/2, data["srrip"], width, label="SRRIP",
               color=COLOR_SRRIP, alpha=0.8)
        ax.bar(x + width/2, data["srrip_live"], width, label="SRRIP-Live",
               color=COLOR_SRRIP_LIVE, alpha=0.8)

        ax.set_title(suite_name.upper(), fontweight="bold", fontsize=11)
        ax.set_xlabel("DoA Threshold (θ)", fontsize=10)
        ax.set_ylabel("Speedup (%)", fontsize=10)
        ax.set_xticks(x)
        ax.set_xticklabels(data["thresholds"])
        ax.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
        ax.grid(axis='y', alpha=0.3)
        ax.legend(fontsize=9)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"✓ Saved: {output_path}")
    return output_path

def create_workload_plot(data_dict, suite_names, output_path, policy_name, cache_level="LLC"):
    """Create per-workload plot (3 subplots)."""
    fig, axes = plt.subplots(1, 3, figsize=(15, 3.5))
    fig.suptitle(f"{cache_level} Per-Workload Speedup at Optimal Threshold",
                 fontsize=12, fontweight="bold")

    for ax, suite_name in zip(axes, suite_names):
        data = data_dict.get(suite_name)
        if not data:
            ax.text(0.5, 0.5, f"No data", ha='center', va='center')
            continue

        x = np.arange(len(data["names"]))
        width = 0.35

        ax.bar(x - width/2, data["speedups_baseline"], width,
               label="SRRIP", color=COLOR_SRRIP, alpha=0.8)
        ax.bar(x + width/2, data["speedups"], width,
               label=policy_name, color=COLOR_SRRIP_LIVE, alpha=0.8)

        ax.set_title(suite_name.upper(), fontweight="bold", fontsize=11)
        ax.set_xlabel("Workload", fontsize=10)
        ax.set_ylabel("Speedup (%)", fontsize=10)
        ax.set_xticks(x)
        ax.set_xticklabels(data["names"], rotation=45, ha='right', fontsize=8)
        ax.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
        ax.grid(axis='y', alpha=0.3)
        ax.legend(fontsize=9)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"✓ Saved: {output_path}")
    return output_path

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate paper plots from experimental data")
    parser.add_argument("--results-base", type=Path, default=Path("results"),
                       help="Base results directory")
    parser.add_argument("--output-dir", type=Path, default=Path("results/plots"),
                       help="Output directory")
    parser.add_argument("--suites", nargs="+", default=["dpc3", "qmm", "google"],
                       help="Suites to plot (choose from: qmm, google, dpc3, gms, ligra)")

    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print("Generating paper plots...")
    print(f"  Results base: {args.results_base}")
    print(f"  Output dir: {args.output_dir}")
    print(f"  Suites: {args.suites}")
    print()

    # Find result directories
    suite_dirs = find_result_dirs(args.results_base)

    # Filter to requested suites
    suite_dirs = {k: v for k, v in suite_dirs.items() if k in args.suites and v is not None}

    if not suite_dirs:
        print("ERROR: No result directories found!")
        return 1

    # Generate LLC plots (for SRRIP-Live suites)
    print("\nGenerating LLC plots...")

    llc_suites = [s for s in args.suites if s in ["dpc3", "qmm", "google"]]
    llc_dirs = {s: suite_dirs[s] for s in llc_suites if s in suite_dirs}

    # Try to find baseline directory
    baseline_dir = args.results_base / "baseline"
    if not baseline_dir.exists():
        baseline_dir = None

    if llc_dirs:
        llc_thd_data = {}
        for suite, suite_dir in llc_dirs.items():
            data = plot_threshold_sensitivity(suite_dir, suite, "LLC", baseline_dir)
            if data:
                llc_thd_data[suite] = data

        if llc_thd_data:
            create_threshold_plot(llc_thd_data, llc_suites,
                                args.output_dir / "01_llc_threshold_sensitivity.png",
                                "LLC")

        llc_opt_data = {}
        for suite, suite_dir in llc_dirs.items():
            data = plot_per_workload(suite_dir, suite, "srrip_live", thd=4)
            if data:
                llc_opt_data[suite] = data

        if llc_opt_data:
            create_workload_plot(llc_opt_data, llc_suites,
                               args.output_dir / "02_llc_perworkload_optimal.png",
                               "SRRIP-Live (θ=4)", "LLC")

    print("\n✓ Plot generation complete!")
    print("\nNext steps:")
    print(f"  1. Check plots in {args.output_dir}")
    print("  2. Run 'make pdf' to regenerate paper with new plots")

if __name__ == "__main__":
    sys.exit(main())
