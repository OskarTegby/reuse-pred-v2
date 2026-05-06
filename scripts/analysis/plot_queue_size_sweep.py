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
from pathlib import Path

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


def _benchmark_weighted_geomean_pct(ratios_by_wl: "dict[str, float]") -> float:
    """Simpoint-weighted geomean speedup (%).

    For SPEC traces with weights: weighted geomean within each benchmark
    (re-normalised for missing simpoints), then equal-weight geomean across
    benchmarks.  For other traces: flat equal-weight geomean.
    ratios_by_wl values are raw ratios (ipc_new/ipc_base), not percentages.
    """
    groups: dict = {}
    for wl, r in ratios_by_wl.items():
        groups.setdefault(_benchmark_name(wl), []).append(wl)
    per_bench = []
    for wl_list in groups.values():
        if _SPEC_WEIGHTS:
            pairs = [(ratios_by_wl[wl], _SPEC_WEIGHTS.get(wl)) for wl in wl_list]
            if any(w is not None for _, w in pairs):
                pairs = [(r, w) for r, w in pairs if w is not None and r > 0]
                total_w = sum(w for _, w in pairs)
                if total_w > 0:
                    per_bench.append(
                        float(np.exp(sum((w / total_w) * np.log(r) for r, w in pairs))))
                    continue
        vals = [ratios_by_wl[wl] for wl in wl_list if ratios_by_wl[wl] > 0]
        if vals:
            per_bench.append(float(np.exp(np.mean(np.log(vals)))))
    if not per_bench:
        return float("nan")
    return (float(np.exp(np.mean(np.log([r for r in per_bench if r > 0])))) - 1) * 100


def geomean_speedup(exp_dir, baseline_dir):
    """Simpoint-weighted geomean IPC speedup (%), benchmark-weighted fallback."""
    ratios: dict = {}
    for trace in os.listdir(exp_dir):
        exp_file  = os.path.join(exp_dir, trace, "champsim.out")
        base_file = os.path.join(baseline_dir, trace, "champsim.out")
        ipc_exp  = parse_ipc(exp_file)
        ipc_base = parse_ipc(base_file)
        if ipc_exp is not None and ipc_base is not None and ipc_base > 0:
            ratios[trace] = ipc_exp / ipc_base
    if not ratios:
        return float("nan")
    return _benchmark_weighted_geomean_pct(ratios)


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
