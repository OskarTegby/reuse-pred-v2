#!/usr/bin/env python3
"""
plot_queue_size_sweep.py — IPC speedup vs PFQ/ST queue size for the
sweep_queue_size study.

Produces two line plots side by side:
  Left:  IPC speedup vs PFQ capacity (ST fixed at original size)
  Right: IPC speedup vs ST size (PFQ fixed at original size)

Both use hashed history tables.  A horizontal reference line marks the
baseline (no predictor) and, where present, pfq_inf / st_inf.

Usage:
    python3 plot_queue_size_sweep.py <results_dir> [--out-dir DIR]

    results_dir   Base directory from sweep_queue_size.sh, e.g.
                  results/dpc3_queue_size_20260504_1200/
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


def _benchmark_name(wl: str) -> str:
    """Strip simpoint suffix so all simpoints of one benchmark share a key.
    SPEC: 600.perlbench_s-1273B → 600.perlbench_s
    Google: arizona_0000 → arizona
    Other (QMM, etc.): returned unchanged.
    """
    m = re.match(r'^(.+)-\d+[A-Z]+$', wl)
    if m:
        return m.group(1)
    m = re.match(r'^(.+)_\d{4}$', wl)
    if m:
        return m.group(1)
    return wl


def geomean_speedup(exp_dir, baseline_dir):
    """Benchmark-weighted geomean IPC speedup (%).

    Groups simpoints by benchmark, takes geomean within each group, then
    geomean across groups so SPEC simpoint count doesn't skew the result.
    """
    from collections import defaultdict
    groups: dict = defaultdict(list)
    for trace in os.listdir(exp_dir):
        exp_file  = os.path.join(exp_dir, trace, "champsim.out")
        base_file = os.path.join(baseline_dir, trace, "champsim.out")
        ipc_exp  = parse_ipc(exp_file)
        ipc_base = parse_ipc(base_file)
        if ipc_exp is not None and ipc_base is not None and ipc_base > 0:
            groups[_benchmark_name(trace)].append(ipc_exp / ipc_base)
    if not groups:
        return float("nan")
    bench_means = [np.exp(np.mean(np.log(rs))) for rs in groups.values()]
    return (np.exp(np.mean(np.log(bench_means))) - 1.0) * 100.0


# ── Data collection ───────────────────────────────────────────────────────────

def collect_queue_sweep(results_dir):
    """
    Returns:
        pfq_sizes   : sorted list of finite PFQ capacities found
        pfq_speedups: corresponding IPC speedups
        pfq_inf     : speedup for pfq_inf (or nan)
        st_sizes    : sorted list of finite ST sizes found
        st_speedups : corresponding IPC speedups
        st_inf      : speedup for st_inf (or nan)
    """
    baseline_dir = os.path.join(results_dir, "baseline")

    pfq_data = {}
    st_data  = {}
    pfq_inf  = float("nan")
    st_inf   = float("nan")

    for entry in os.listdir(results_dir):
        exp_dir = os.path.join(results_dir, entry)
        if not os.path.isdir(exp_dir):
            continue
        if entry == "baseline":
            continue

        if entry == "pfq_inf":
            pfq_inf = geomean_speedup(exp_dir, baseline_dir)
        elif entry == "st_inf":
            st_inf = geomean_speedup(exp_dir, baseline_dir)
        elif re.fullmatch(r"pfq_\d+", entry):
            size = int(entry.split("_")[1])
            pfq_data[size] = geomean_speedup(exp_dir, baseline_dir)
        elif re.fullmatch(r"st_\d+", entry):
            size = int(entry.split("_")[1])
            st_data[size] = geomean_speedup(exp_dir, baseline_dir)

    pfq_sizes    = sorted(pfq_data)
    pfq_speedups = [pfq_data[s] for s in pfq_sizes]
    st_sizes     = sorted(st_data)
    st_speedups  = [st_data[s] for s in st_sizes]

    return pfq_sizes, pfq_speedups, pfq_inf, st_sizes, st_speedups, st_inf


# ── Plotting ──────────────────────────────────────────────────────────────────

def _queue_line(ax, sizes, speedups, inf_val, xlabel, title, color):
    xs = list(range(len(sizes)))
    ax.plot(xs, speedups, "o-", color=color, label="finite sizes")
    ax.axhline(0, color="black", linewidth=0.6)

    if not np.isnan(inf_val):
        # Draw inf as an extra point to the right
        ax.plot([len(sizes)], [inf_val], "D", color=color, markersize=8, label="inf")
        ax.axhline(inf_val, color=color, linestyle="--", linewidth=0.8, alpha=0.5)
        xtick_labels = [str(s) for s in sizes] + ["∞"]
        ax.set_xticks(xs + [len(sizes)])
    else:
        xtick_labels = [str(s) for s in sizes]
        ax.set_xticks(xs)

    ax.set_xticklabels(xtick_labels, rotation=45, ha="right")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("IPC speedup vs baseline (%)")
    ax.set_title(title, fontsize=9)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)


def find_test_dir(suite):
    import glob
    pattern = os.path.join("results", f"{suite}_queue_size_*_test")
    matches = sorted(glob.glob(pattern))
    if not matches:
        print(f"No _test results found matching {pattern}", file=sys.stderr)
        sys.exit(1)
    return matches[-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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

    pfq_sizes, pfq_speedups, pfq_inf, st_sizes, st_speedups, st_inf = \
        collect_queue_sweep(results_dir)

    if not pfq_sizes and not st_sizes:
        print(f"ERROR: no queue-sweep configs found in {results_dir}", file=sys.stderr)
        sys.exit(1)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)

    _queue_line(axes[0], pfq_sizes, pfq_speedups, pfq_inf,
                "PFQ capacity (entries)", "PFQ size sweep (ST fixed at original)",
                "#1a9850")
    _queue_line(axes[1], st_sizes, st_speedups, st_inf,
                "Shadow-table size (entries)", "ST size sweep (PFQ fixed at original)",
                "#4393c3")

    fig.suptitle(f"Queue size sweep — {label}", fontsize=11)
    fig.tight_layout()
    out = os.path.join(out_dir, f"queue_size_{label}.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Written: {out}")


if __name__ == "__main__":
    main()
