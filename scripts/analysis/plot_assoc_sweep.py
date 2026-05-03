#!/usr/bin/env python3
"""
plot_assoc_sweep.py — IPC speedup vs associativity for the sweep_assoc study.

For each table (pHIST, bHIST) independently, plots IPC speedup over the
baseline across all associativity levels (direct-mapped → fully associative),
comparing LRU and LFU.  Reference lines are drawn for hash_pred, fa_lru,
and fa_lfu.

Usage:
    python3 plot_assoc_sweep.py <results_dir> [--out-dir DIR]

    results_dir   Base directory from sweep_assoc.sh, e.g.
                  results/dpc3_assoc_p1024_b4096_20260504_1200/

    --out-dir     Where to write PNGs (default: results_dir)
"""

import argparse
import os
import re
import sys

import matplotlib.pyplot as plt
import numpy as np


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_ipc(path):
    in_roi = False
    try:
        with open(path) as f:
            for line in f:
                if "Region of Interest Statistics" in line:
                    in_roi = True
                if in_roi and "cumulative IPC:" in line:
                    m = re.search(r"cumulative IPC:\s+([0-9.]+)", line)
                    if m:
                        return float(m.group(1))
    except OSError:
        pass
    return None


def geomean_speedup(exp_dir, baseline_dir):
    """Return geomean IPC speedup (%) of exp_dir vs baseline_dir over all traces."""
    ratios = []
    for trace in os.listdir(exp_dir):
        exp_file  = os.path.join(exp_dir, trace, "champsim.out")
        base_file = os.path.join(baseline_dir, trace, "champsim.out")
        ipc_exp  = parse_ipc(exp_file)
        ipc_base = parse_ipc(base_file)
        if ipc_exp is not None and ipc_base is not None and ipc_base > 0:
            ratios.append(ipc_exp / ipc_base)
    if not ratios:
        return float("nan")
    return (np.exp(np.mean(np.log(ratios))) - 1.0) * 100.0


# ── Data collection ───────────────────────────────────────────────────────────

def collect_sweep(results_dir, prefix, size):
    """
    Return (ways_list, lru_speedups, lfu_speedups) for one table's sweep.
    prefix: 'phist' or 'bhist'
    size:   table size (1024 for pHIST, 4096 for bHIST)
    """
    baseline_dir = os.path.join(results_dir, "baseline")

    ways_lru = {}
    ways_lfu = {}

    for entry in os.listdir(results_dir):
        m = re.fullmatch(rf"{prefix}_s(\d+)_w(\d+)_(lru|lfu)", entry)
        if not m:
            continue
        ways = int(m.group(2))
        pol  = m.group(3)
        exp_dir = os.path.join(results_dir, entry)
        val = geomean_speedup(exp_dir, baseline_dir)
        if pol == "lru":
            ways_lru[ways] = val
        else:
            ways_lfu[ways] = val

    all_ways = sorted(set(ways_lru) | set(ways_lfu))
    lru_vals = [ways_lru.get(w, float("nan")) for w in all_ways]
    lfu_vals = [ways_lfu.get(w, float("nan")) for w in all_ways]
    return all_ways, lru_vals, lfu_vals


def ref_speedup(results_dir, exp_name):
    baseline_dir = os.path.join(results_dir, "baseline")
    exp_dir      = os.path.join(results_dir, exp_name)
    if not os.path.isdir(exp_dir):
        return float("nan")
    return geomean_speedup(exp_dir, baseline_dir)


# ── Plotting ──────────────────────────────────────────────────────────────────

def plot_table_sweep(results_dir, prefix, size, label, out_path):
    ways, lru_vals, lfu_vals = collect_sweep(results_dir, prefix, size)
    if not ways:
        print(f"  No data found for {prefix} sweep in {results_dir}", file=sys.stderr)
        return

    hash_pred = ref_speedup(results_dir, "hash_pred")
    fa_lru    = ref_speedup(results_dir, "fa_lru")
    fa_lfu    = ref_speedup(results_dir, "fa_lfu")

    fig, ax = plt.subplots(figsize=(8, 4.5))

    ax.plot(range(len(ways)), lru_vals, "o-", color="#1a9850", label="LRU")
    ax.plot(range(len(ways)), lfu_vals, "s--", color="#4393c3", label="LFU")

    if not np.isnan(hash_pred):
        ax.axhline(hash_pred, color="#d73027", linestyle=":", linewidth=1.2, label="hash_pred")
    if not np.isnan(fa_lru):
        ax.axhline(fa_lru, color="#1a9850", linestyle="--", linewidth=0.8, alpha=0.5, label="fa_lru (ref)")
    if not np.isnan(fa_lfu):
        ax.axhline(fa_lfu, color="#4393c3", linestyle="--", linewidth=0.8, alpha=0.5, label="fa_lfu (ref)")

    ax.axhline(0, color="black", linewidth=0.6)
    ax.set_xticks(range(len(ways)))
    ax.set_xticklabels([str(w) for w in ways], rotation=45, ha="right")
    ax.set_xlabel("Associativity (ways)")
    ax.set_ylabel("IPC speedup vs baseline (%)")
    ax.set_title(f"{label} associativity sweep — {os.path.basename(results_dir)}")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  Written: {out_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results_dir", help="Base directory from sweep_assoc.sh")
    ap.add_argument("--out-dir", default=None, help="Output directory for PNGs")
    args = ap.parse_args()

    results_dir = args.results_dir.rstrip("/")
    out_dir     = args.out_dir or results_dir
    os.makedirs(out_dir, exist_ok=True)

    label = os.path.basename(results_dir)

    plot_table_sweep(results_dir, "phist", 1024, "pHIST",
                     os.path.join(out_dir, f"assoc_phist_{label}.png"))
    plot_table_sweep(results_dir, "bhist", 4096, "bHIST",
                     os.path.join(out_dir, f"assoc_bhist_{label}.png"))


if __name__ == "__main__":
    main()
