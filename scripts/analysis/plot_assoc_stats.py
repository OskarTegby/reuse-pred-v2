#!/usr/bin/env python3
"""
plot_assoc_stats.py — IPC speedup, LLC MPKI, and table hit-rates vs associativity.

For each suite, produces two figures (pHIST sweep and bHIST sweep), each with
three stacked panels:
  1. IPC speedup over baseline (%)
  2. LLC MPKI
  3. pHIST hit rate (pHIST sweep) or PFQ hit rate (bHIST sweep)

Usage:
    python3 plot_assoc_stats.py <results_dir> [--out-dir DIR]
"""

import argparse
import os
import re
import sys
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from colors import LRU_COLOR, LFU_COLOR
from champsim_utils import geomean_speedup, find_test_dir


def parse_stats(path):
    s = {}
    try:
        with open(path) as f:
            in_roi = False
            for line in f:
                if "Region of Interest Statistics" in line:
                    in_roi = True
                if not in_roi:
                    continue
                m = re.search(r"cumulative IPC:\s+([0-9.]+)\s+instructions:\s+(\d+)", line)
                if m:
                    s["ipc"] = float(m.group(1))
                    s["insns"] = int(m.group(2))
                m = re.search(r"LLC TOTAL\s+ACCESS:\s+\d+\s+HIT:\s+\d+\s+MISS:\s+(\d+)", line)
                if m:
                    s["llc_miss"] = int(m.group(1))
                m = re.search(r"cpu0_STLB PHIST LOOKUPS:\s+(\d+)\s+HITS:\s+(\d+)", line)
                if m:
                    s["phist_lookups"] = int(m.group(1))
                    s["phist_hits"]    = int(m.group(2))
                m = re.search(r"cpu0_STLB BYPASSES:\s+(\d+)", line)
                if m:
                    s["stlb_bypass"] = int(m.group(1))
                m = re.search(r"^LLC BYPASSES:\s+(\d+)", line)
                if m:
                    s["llc_bypass"] = int(m.group(1))
                m = re.search(r"LLC PFQ PROBES:\s+(\d+)\s+HITS:\s+(\d+)", line)
                if m:
                    s["pfq_probes"] = int(m.group(1))
                    s["pfq_hits"]   = int(m.group(2))
    except OSError:
        pass
    return s if "ipc" in s else None


def aggregate(exp_dir):
    ipc_logs = []
    totals = dict(llc_miss=0, insns=0,
                  phist_lookups=0, phist_hits=0,
                  stlb_bypass=0, llc_bypass=0,
                  pfq_probes=0, pfq_hits=0)
    n = 0
    for t in os.listdir(exp_dir):
        p = parse_stats(os.path.join(exp_dir, t, "champsim.out"))
        if p is None:
            continue
        ipc_logs.append(math.log(p["ipc"]))
        for k in totals:
            totals[k] += p.get(k, 0)
        n += 1
    if n == 0:
        return None
    totals["n"] = n
    totals["ipc_geo"] = math.exp(sum(ipc_logs) / n)
    totals["llc_mpki"] = (totals["llc_miss"] / (totals["insns"] / 1000.0)
                          if totals["insns"] > 0 else float("nan"))
    totals["phist_hit_rate"] = (totals["phist_hits"] / totals["phist_lookups"] * 100
                                if totals["phist_lookups"] > 0 else float("nan"))
    totals["pfq_hit_rate"]   = (totals["pfq_hits"] / totals["pfq_probes"] * 100
                                if totals["pfq_probes"] > 0 else float("nan"))
    return totals


def collect_sweep(results_dir, prefix, policies=("lru", "lfu")):
    """Return dict: pol → sorted list of (ways, agg_stats)."""
    baseline_dir = os.path.join(results_dir, "baseline")
    base = aggregate(baseline_dir)

    out = {}
    for pol in policies:
        points = {}
        for entry in os.listdir(results_dir):
            m = re.fullmatch(rf"{prefix}_s(\d+)_w(\d+)_{pol}", entry)
            if not m:
                continue
            ways = int(m.group(2))
            exp_dir = os.path.join(results_dir, entry)
            a = aggregate(exp_dir)
            if a:
                a["ipc_speedup"] = geomean_speedup(exp_dir, baseline_dir)
            points[ways] = a
        if points:
            out[pol] = sorted(points.items())
    return base, out


def plot_sweep(results_dir, prefix, table_label, hit_rate_label, out_path):
    base, sweep = collect_sweep(results_dir, prefix)
    if not sweep:
        print(f"  No data for {prefix} sweep", file=sys.stderr)
        return

    colors = {"lru": LRU_COLOR, "lfu": LFU_COLOR}
    fig, axes = plt.subplots(3, 1, figsize=(8, 9), sharex=True)
    ax_ipc, ax_mpki, ax_hit = axes

    for pol, points in sweep.items():
        ways_list = [w for w, _ in points]
        ipc_sp    = [a["ipc_speedup"]    if a else float("nan") for _, a in points]
        mpki      = [a["llc_mpki"]       if a else float("nan") for _, a in points]
        hit_rate  = ([a["phist_hit_rate"] if a else float("nan") for _, a in points]
                     if prefix == "phist" else
                     [a["pfq_hit_rate"]   if a else float("nan") for _, a in points])

        x = np.arange(len(ways_list))
        marker = "o" if pol == "lru" else "s"
        ls     = "-"  if pol == "lru" else "--"
        c      = colors[pol]

        ax_ipc.plot(x, ipc_sp,   marker + ls, color=c, linewidth=1.8,
                    markersize=5, label=pol.upper())
        ax_mpki.plot(x, mpki,    marker + ls, color=c, linewidth=1.8, markersize=5)
        ax_hit.plot(x,  hit_rate, marker + ls, color=c, linewidth=1.8, markersize=5)

    # Baseline reference lines
    if base:
        ax_mpki.axhline(base["llc_mpki"], color="black", linewidth=0.8,
                        linestyle=":", label="baseline")

    ax_ipc.axhline(0, color="black", linewidth=0.6)

    # x-axis labels: show "1\n(DM)" for 1-way and "{max}\n(FA)" for max ways
    all_ways = sorted({w for pol_pts in sweep.values() for w, _ in pol_pts})
    x_all = np.arange(len(all_ways))
    labels = []
    for w in all_ways:
        if w == min(all_ways):
            labels.append(f"{w}\n(DM)")
        elif w == max(all_ways):
            labels.append(f"{w}\n(FA)")
        else:
            labels.append(str(w))
    ax_hit.set_xticks(x_all)
    ax_hit.set_xticklabels(labels, rotation=45, ha="right")
    ax_hit.set_xlabel(f"{table_label} associativity (ways)")

    ax_ipc.set_ylabel("IPC speedup vs baseline (%)")
    ax_mpki.set_ylabel("LLC MPKI")
    ax_hit.set_ylabel(hit_rate_label)

    ax_ipc.legend(fontsize=8)
    ax_mpki.legend(fontsize=8)

    for ax in axes:
        ax.grid(axis="y", alpha=0.3)

    suite = os.path.basename(results_dir).split("_assoc_")[0].upper()
    fig.suptitle(f"{suite} — {table_label} associativity sweep", fontsize=11)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  Written: {out_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results_dir",
                    help="Results directory, or suite name (dpc3|google|qmm) with --test")
    ap.add_argument("--test", action="store_true",
                    help="Find and plot the most recent _test run for the given suite")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    results_dir = (find_test_dir(args.results_dir, "assoc") if args.test
                   else args.results_dir.rstrip("/"))
    out_dir     = args.out_dir or results_dir
    os.makedirs(out_dir, exist_ok=True)
    label = os.path.basename(results_dir)

    plot_sweep(results_dir, "phist", "pHIST", "pHIST hit rate (%)",
               os.path.join(out_dir, f"assoc_stats_phist_{label}.png"))
    plot_sweep(results_dir, "bhist", "bHIST", "PFQ hit rate (%)",
               os.path.join(out_dir, f"assoc_stats_bhist_{label}.png"))


if __name__ == "__main__":
    main()
