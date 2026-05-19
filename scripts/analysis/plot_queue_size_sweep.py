#!/usr/bin/env python3
"""
plot_queue_size_sweep.py — PFQ / shadow-table size study for sweep_queue_size.sh results.

Produces a 4×2 figure:
  Left column  — PFQ sweep (ST fixed at original size 2)
  Right column — ST sweep  (PFQ fixed at original size 8)

  Row 1: bypass rate  (LLC bypasses/kilo-instr | STLB bypasses/kilo-instr)
  Row 2: hit rate     (PFQ hit rate             | ST hit rate)
  Row 3: MPKI         (LLC MPKI                 | STLB MPKI)
  Row 4: IPC speedup vs no-bypass LRU baseline

Usage:
    python3 plot_queue_size_sweep.py <results_dir> [--out-dir DIR]

    results_dir   Base directory from sweep_queue_size.sh, e.g.
                  results/dpc3_queue_size_20260504_1200/
"""

import argparse
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from champsim_utils import geomean_speedup, collect_bypass_stats, find_test_dir


INF_LABEL = "∞"
INF_KEY   = 10 ** 9   # sentinel used internally for the "inf" config


# ── Data collection ───────────────────────────────────────────────────────────

def _parse_size(name, prefix):
    """Return int size from 'prefix_<int>' or INF_KEY from 'prefix_inf'."""
    suffix = name[len(prefix):]
    return INF_KEY if suffix == "inf" else int(suffix)


def collect_sweep(results_dir):
    """Walk results_dir and return per-size metric dicts for PFQ and ST sweeps.

    Returns:
        baseline_ipc  : float (geomean IPC ratio = 1.0 by convention, speedup = 0)
        pfq           : {size: {'speedup', 'llc_bypass_pkis', 'pfq_hit_rate', 'llc_mpki'}}
        st            : {size: {'speedup', 'stlb_bypass_pkis', 'st_hit_rate', 'stlb_mpki'}}
    """
    baseline_dir = os.path.join(results_dir, "baseline")
    pfq = {}
    st  = {}

    for entry in sorted(os.listdir(results_dir)):
        exp_dir = os.path.join(results_dir, entry)
        if not os.path.isdir(exp_dir) or entry == "baseline":
            continue

        if entry.startswith("pfq_"):
            size = _parse_size(entry, "pfq_")
            spd  = geomean_speedup(exp_dir, baseline_dir)
            byp  = collect_bypass_stats(exp_dir)
            pfq[size] = {
                "speedup":         spd,
                "llc_bypass_pct":  byp["llc_bypass_pct"],
                "pfq_hit_rate":    byp["pfq_hit_rate"],
                "llc_mpki":        byp["llc_mpki"],
            }
        elif entry.startswith("st_"):
            size = _parse_size(entry, "st_")
            spd  = geomean_speedup(exp_dir, baseline_dir)
            byp  = collect_bypass_stats(exp_dir)
            st[size] = {
                "speedup":          spd,
                "stlb_bypass_pct":  byp["stlb_bypass_pct"],
                "st_hit_rate":      byp["st_hit_rate"],
                "stlb_mpki":        byp["stlb_mpki"],
            }

    return pfq, st


# ── Plotting helpers ──────────────────────────────────────────────────────────

def _xtick_labels(sizes):
    labels = []
    for s in sizes:
        labels.append(INF_LABEL if s == INF_KEY else str(s))
    return labels


def _plot_metric(ax, sizes, vals, color, ylabel, title, hline=None, hline_label=None):
    xs = list(range(len(sizes)))
    finite_xs = [x for x, s in zip(xs, sizes) if s != INF_KEY]
    finite_ys = [v for s, v in zip(sizes, vals) if s != INF_KEY]
    inf_xs    = [x for x, s in zip(xs, sizes) if s == INF_KEY]
    inf_ys    = [v for s, v in zip(sizes, vals) if s == INF_KEY]

    ax.plot(finite_xs, finite_ys, "o-", color=color, linewidth=1.5, markersize=5)
    if inf_ys:
        ax.plot(inf_xs, inf_ys, "D", color=color, markersize=7)
        ax.axhline(inf_ys[0], color=color, linestyle="--", linewidth=0.7, alpha=0.5)

    if hline is not None:
        ax.axhline(hline, color="black", linewidth=0.8, linestyle=":", label=hline_label)

    ax.set_xticks(xs)
    ax.set_xticklabels(_xtick_labels(sizes), rotation=45, ha="right", fontsize=7)
    ax.set_ylabel(ylabel, fontsize=8)
    ax.set_title(title, fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    ax.tick_params(labelsize=7)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results_dir",
                    help="Results directory or suite name (dpc3|google|qmm) with --test")
    ap.add_argument("--test", action="store_true",
                    help="Find and plot the most recent _test run for the given suite")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    results_dir = (find_test_dir(args.results_dir, "queue_size") if args.test
                   else args.results_dir.rstrip("/"))
    out_dir = args.out_dir or results_dir
    os.makedirs(out_dir, exist_ok=True)
    label = os.path.basename(results_dir)

    pfq, st = collect_sweep(results_dir)

    if not pfq and not st:
        print(f"ERROR: no sweep configs found in {results_dir}", file=sys.stderr)
        sys.exit(1)

    pfq_sizes = sorted(pfq)
    st_sizes  = sorted(st)

    def _get(d, sizes, key):
        return [d[s][key] for s in sizes]

    PFQ_COLOR = "#1a9850"
    ST_COLOR  = "#4393c3"

    fig, axes = plt.subplots(4, 2, figsize=(11, 12))
    fig.suptitle(f"PFQ / Shadow-Table size study — {label}", fontsize=11, y=0.995)

    # Row 0: bypass rate (% of fill opportunities bypassed)
    _plot_metric(axes[0, 0], pfq_sizes,
                 _get(pfq, pfq_sizes, "llc_bypass_pct"),
                 PFQ_COLOR,
                 "LLC bypasses / LLC misses (%)",
                 "PFQ sweep: LLC bypass rate  (ST=2 fixed)")
    _plot_metric(axes[0, 1], st_sizes,
                 _get(st, st_sizes, "stlb_bypass_pct"),
                 ST_COLOR,
                 "STLB bypasses / STLB misses (%)",
                 "ST sweep: STLB bypass rate  (PFQ=8 fixed)")

    # Row 1: structure hit rate
    _plot_metric(axes[1, 0], pfq_sizes,
                 [v * 100 for v in _get(pfq, pfq_sizes, "pfq_hit_rate")],
                 PFQ_COLOR,
                 "PFQ hit rate (%)",
                 "PFQ hit rate (LLC fills whose page is in PFQ)")
    _plot_metric(axes[1, 1], st_sizes,
                 [v * 100 for v in _get(st, st_sizes, "st_hit_rate")],
                 ST_COLOR,
                 "ST hit rate (%)",
                 "Shadow-table hit rate (STLB misses served from ST)")

    # Row 2: MPKI
    _plot_metric(axes[2, 0], pfq_sizes,
                 _get(pfq, pfq_sizes, "llc_mpki"),
                 PFQ_COLOR,
                 "LLC MPKI",
                 "LLC MPKI vs PFQ capacity")
    _plot_metric(axes[2, 1], st_sizes,
                 _get(st, st_sizes, "stlb_mpki"),
                 ST_COLOR,
                 "STLB MPKI",
                 "STLB MPKI vs shadow-table size")

    # Row 3: IPC speedup
    _plot_metric(axes[3, 0], pfq_sizes,
                 _get(pfq, pfq_sizes, "speedup"),
                 PFQ_COLOR,
                 "IPC speedup vs baseline (%)",
                 "IPC speedup vs PFQ capacity",
                 hline=0, hline_label="baseline")
    axes[3, 0].axhline(0, color="black", linewidth=0.8)
    _plot_metric(axes[3, 1], st_sizes,
                 _get(st, st_sizes, "speedup"),
                 ST_COLOR,
                 "IPC speedup vs baseline (%)",
                 "IPC speedup vs shadow-table size",
                 hline=0, hline_label="baseline")
    axes[3, 1].axhline(0, color="black", linewidth=0.8)

    # Shared x-labels
    axes[3, 0].set_xlabel("PFQ capacity (entries)", fontsize=8)
    axes[3, 1].set_xlabel("Shadow-table size (entries)", fontsize=8)

    fig.tight_layout(rect=[0, 0, 1, 0.995])
    out = os.path.join(out_dir, f"queue_size_{label}.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Written: {out}")


if __name__ == "__main__":
    main()
