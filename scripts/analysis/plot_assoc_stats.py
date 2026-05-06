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
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


LRU_COLOR = "#1a9850"
LFU_COLOR = "#4393c3"


# ── SimPoint weights ──────────────────────────────────────────────────────────

_DEFAULT_WEIGHTS_DIR = (
    Path(__file__).parents[2] / ".." / "ChampSim-dev" / "trace-files" / "SPEC2006_weights"
).resolve()


def _load_spec_weights(weights_dir: Path) -> "dict[str, float]":
    result: dict = {}
    if not weights_dir.is_dir():
        return result
    for bm_dir in sorted(weights_dir.iterdir()):
        if not bm_dir.is_dir():
            continue
        w_file = bm_dir / "weights.out"
        s_file = bm_dir / "simpoints.out"
        if not (w_file.exists() and s_file.exists()):
            continue
        w_vals = [float(x) for x in w_file.read_text().split()]
        s_ids  = [int(x)   for x in s_file.read_text().split()]
        for sp_id, w in zip(s_ids, w_vals):
            result[f"{bm_dir.name}-{sp_id}B"] = w
    return result


def _benchmark_name(wl: str) -> str:
    """Strip SPEC simpoint suffix: 602.gcc_s-734B -> 602.gcc_s."""
    m = re.match(r'^(.+)-\d+[A-Z]+$', wl)
    return m.group(1) if m else wl


_SPEC_WEIGHTS: "dict[str, float]" = _load_spec_weights(_DEFAULT_WEIGHTS_DIR)


def _speedup_pct(exp_dir: str, baseline_dir: str) -> float:
    """Simpoint-weighted geomean IPC speedup (%) over baseline."""
    ratios: dict = {}
    for trace in os.listdir(exp_dir):
        exp_file  = os.path.join(exp_dir, trace, "champsim.out")
        base_file = os.path.join(baseline_dir, trace, "champsim.out")
        exp_stats  = parse_stats(exp_file)
        base_stats = parse_stats(base_file)
        if exp_stats and base_stats and base_stats.get("ipc", 0) > 0:
            ratios[trace] = exp_stats["ipc"] / base_stats["ipc"]
    if not ratios:
        return float("nan")
    groups: dict = {}
    for wl, r in ratios.items():
        groups.setdefault(_benchmark_name(wl), []).append(wl)
    per_bench = []
    for wl_list in groups.values():
        if _SPEC_WEIGHTS:
            pairs = [(ratios[wl], _SPEC_WEIGHTS.get(wl)) for wl in wl_list]
            if any(w is not None for _, w in pairs):
                pairs = [(r, w) for r, w in pairs if w is not None and r > 0]
                total_w = sum(w for _, w in pairs)
                if total_w > 0:
                    per_bench.append(
                        float(np.exp(sum((w / total_w) * np.log(r) for r, w in pairs))))
                    continue
        vals = [ratios[wl] for wl in wl_list if ratios[wl] > 0]
        if vals:
            per_bench.append(float(np.exp(np.mean(np.log(vals)))))
    if not per_bench:
        return float("nan")
    return (float(np.exp(np.mean(np.log([r for r in per_bench if r > 0])))) - 1) * 100


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
                a["ipc_speedup"] = _speedup_pct(exp_dir, baseline_dir)
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


def find_test_dir(suite):
    """Return the most recent results/{suite}_assoc_*_test directory."""
    import glob
    pattern = os.path.join("results", f"{suite}_assoc_*_test")
    matches = sorted(glob.glob(pattern))
    if not matches:
        print(f"No _test results found matching {pattern}", file=sys.stderr)
        sys.exit(1)
    return matches[-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results_dir",
                    help="Results directory, or suite name (dpc3|google|qmm) with --test")
    ap.add_argument("--test", action="store_true",
                    help="Find and plot the most recent _test run for the given suite")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    results_dir = (find_test_dir(args.results_dir) if args.test
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
