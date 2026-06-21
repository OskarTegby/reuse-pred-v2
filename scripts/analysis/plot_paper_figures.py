#!/usr/bin/env python3
"""Plot paper-quality figures for HPCA submission.

Generates:
1. Per-suite threshold scaling (geomean vs threshold)
2. Per-workload optimal threshold results
3. Combined policy comparison

Key improvements:
- Removes lru_mid (deprecated policy)
- Better space usage (short workload IDs)
- Consistent per-suite vs per-workload organization
"""

import argparse
import json
import math
import sys
from pathlib import Path
from statistics import geometric_mean

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# Colors: clean, publication-ready palette
COLOR_SRRIP = "#1f77b4"      # blue
COLOR_SRRIP_LIVE = "#2ca02c" # green
COLOR_IPV = "#ff7f0e"        # orange
COLOR_IPV_LIVE = "#d62728"   # red
COLOR_COMBINED = "#9467bd"   # purple

# Workload name shortening
TRACE_SHORT_NAMES = {
    "bwaves": "bw", "cactusADM": "cact", "cam4": "cam", "fotonik3d": "foto",
    "lbm": "lbm", "mcf": "mcf", "omnetpp": "omn", "wrf": "wrf", "xalancbmk": "xal",
    "imagick": "img", "nab": "nab", "xz": "xz",
    # Server workloads - use srv_ prefix
}

def shorten_trace_name(name):
    """Shorten trace name for better space usage."""
    if name in TRACE_SHORT_NAMES:
        return TRACE_SHORT_NAMES[name]
    # For srv_* format, extract just the ID
    if name.startswith("srv_"):
        return name[4:]  # Remove "srv_" prefix
    # For other names, keep first 3-4 chars
    return name[:4].rstrip("_")

def parse_ipc(champsim_out):
    """Extract sim_IPC from champsim.out"""
    try:
        with open(champsim_out) as f:
            for line in f:
                if "sim_IPC" in line:
                    return float(line.split()[-1])
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
            ipc = parse_ipc(champsim_out)
            if ipc:
                trace_id = trace_dir.name.replace("srv_", "")
                ipcs[trace_id] = ipc
    return ipcs

def plot_threshold_scaling_per_suite(result_dirs, suite_names, output_path):
    """Plot: Geomean IPC vs threshold (per-suite comparison)."""
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    fig.suptitle("Threshold Sensitivity: Per-Suite Geomean IPC", fontsize=12, fontweight="bold")

    thresholds = [1, 2, 4, 8, 16]

    for ax, result_dir, suite_name in zip(axes, result_dirs, suite_names):
        lru_ipcs = load_results(result_dir, "lru")

        # Compute geomeans for each threshold
        srrip_geomeans = []
        srrip_live_geomeans = []

        for thd in thresholds:
            srrip_ipcs = load_results(result_dir, "srrip")
            srrip_live_ipcs = load_results(result_dir, f"srrip_live_mid{thd}")

            if srrip_ipcs and lru_ipcs:
                srrip_gm = geometric_mean([srrip_ipcs[k] / lru_ipcs[k]
                                          for k in srrip_ipcs if k in lru_ipcs]) * 100 - 100
                srrip_geomeans.append(srrip_gm)
            else:
                srrip_geomeans.append(0)

            if srrip_live_ipcs and lru_ipcs:
                live_gm = geometric_mean([srrip_live_ipcs[k] / lru_ipcs[k]
                                         for k in srrip_live_ipcs if k in lru_ipcs]) * 100 - 100
                srrip_live_geomeans.append(live_gm)
            else:
                srrip_live_geomeans.append(0)

        x = np.arange(len(thresholds))
        width = 0.35

        ax.bar(x - width/2, srrip_geomeans, width, label="SRRIP", color=COLOR_SRRIP, alpha=0.8)
        ax.bar(x + width/2, srrip_live_geomeans, width, label="SRRIP-Live", color=COLOR_SRRIP_LIVE, alpha=0.8)

        ax.set_xlabel("DoA Threshold (θ)", fontsize=10)
        ax.set_ylabel("Speedup (%)", fontsize=10)
        ax.set_title(suite_name, fontsize=11, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(thresholds)
        ax.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
        ax.legend(fontsize=9)
        ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Saved: {output_path}")

def plot_optimal_per_workload(result_dir, suite_name, output_path, optimal_thd=4):
    """Plot: Per-workload speedup at optimal threshold."""
    fig, ax = plt.subplots(figsize=(12, 4))

    lru_ipcs = load_results(result_dir, "lru")
    srrip_ipcs = load_results(result_dir, "srrip")
    srrip_live_ipcs = load_results(result_dir, f"srrip_live_mid{optimal_thd}")
    ipv_live_ipcs = load_results(result_dir, f"ipv_live_mid{optimal_thd}")

    if not lru_ipcs:
        print(f"No LRU results for {suite_name}")
        return

    # Compute per-workload speedups
    workloads = sorted(set(lru_ipcs.keys()) & set(srrip_live_ipcs.keys()))

    speedups_srrip = []
    speedups_srrip_live = []
    speedups_ipv_live = []
    short_names = []

    for wl in workloads:
        short_names.append(shorten_trace_name(wl))

        if wl in srrip_ipcs and lru_ipcs[wl] > 0:
            speedups_srrip.append((srrip_ipcs[wl] / lru_ipcs[wl] - 1) * 100)
        else:
            speedups_srrip.append(0)

        if wl in srrip_live_ipcs and lru_ipcs[wl] > 0:
            speedups_srrip_live.append((srrip_live_ipcs[wl] / lru_ipcs[wl] - 1) * 100)
        else:
            speedups_srrip_live.append(0)

        if wl in ipv_live_ipcs and lru_ipcs[wl] > 0:
            speedups_ipv_live.append((ipv_live_ipcs[wl] / lru_ipcs[wl] - 1) * 100)
        else:
            speedups_ipv_live.append(0)

    # Sort by SRRIP-Live speedup
    sorted_indices = sorted(range(len(speedups_srrip_live)),
                           key=lambda i: speedups_srrip_live[i], reverse=True)

    short_names = [short_names[i] for i in sorted_indices]
    speedups_srrip = [speedups_srrip[i] for i in sorted_indices]
    speedups_srrip_live = [speedups_srrip_live[i] for i in sorted_indices]
    speedups_ipv_live = [speedups_ipv_live[i] for i in sorted_indices]

    x = np.arange(len(short_names))
    width = 0.25

    ax.bar(x - width, speedups_srrip, width, label="SRRIP", color=COLOR_SRRIP, alpha=0.8)
    ax.bar(x, speedups_srrip_live, width, label=f"SRRIP-Live (θ={optimal_thd})",
           color=COLOR_SRRIP_LIVE, alpha=0.8)
    ax.bar(x + width, speedups_ipv_live, width, label=f"IPV-Live (θ={optimal_thd})",
           color=COLOR_IPV_LIVE, alpha=0.8)

    ax.set_xlabel("Workload", fontsize=10)
    ax.set_ylabel("Speedup (%)", fontsize=10)
    ax.set_title(f"{suite_name}: Per-Workload Speedup at Optimal Threshold",
                 fontsize=11, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(short_names, rotation=45, ha='right', fontsize=8)
    ax.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
    ax.legend(fontsize=9, loc='upper left')
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Saved: {output_path}")

def main():
    parser = argparse.ArgumentParser(description="Generate paper-quality plots")
    parser.add_argument("--type", choices=["threshold", "optimal", "all"],
                       default="all", help="Plot type to generate")
    parser.add_argument("--result-dir", type=Path, help="Base results directory")
    parser.add_argument("--output-dir", type=Path, default=Path("results/plots"),
                       help="Output directory for plots")

    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.result_dir:
        # Single suite mode
        suite_name = args.result_dir.name.split("_")[0].upper()

        if args.type in ["optimal", "all"]:
            plot_optimal_per_workload(
                args.result_dir,
                suite_name,
                args.output_dir / f"{args.result_dir.name}_optimal.png"
            )
    else:
        print("Usage: python3 plot_paper_figures.py --result-dir <suite_dir> --type [threshold|optimal|all]")
        print("\nExample:")
        print("  python3 plot_paper_figures.py --result-dir results/qmm_srrip_live_thd_pc_20260520_*")

if __name__ == "__main__":
    main()
