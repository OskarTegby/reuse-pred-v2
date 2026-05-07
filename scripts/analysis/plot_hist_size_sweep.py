#!/usr/bin/env python3
"""
plot_hist_size_sweep.py — IPC speedup heatmaps and marginal-return lines
for the sweep_hist_size study.

Produces per-mode heatmaps and a combined marginal-return comparison:
  hist_size_fa_lru_*.png   — IPC speedup heatmap, FA + LRU
  hist_size_fa_lfu_*.png   — IPC speedup heatmap, FA + LFU
  hist_size_hash_dm_*.png  — IPC speedup heatmap, direct-mapped hashed
  hist_size_diff_fa_*.png  — LRU − LFU difference (FA only)
  hist_size_marginal_*.png — FA-LRU, FA-LFU, and Hash-DM on line plots

References (baseline, hash_pred, inf) are annotated on each plot.

Usage:
    python3 plot_hist_size_sweep.py <results_dir> [--out-dir DIR]

    results_dir   Base directory from sweep_hist_size.sh, e.g.
                  results/dpc3_hist_large_20260504_1200/
"""

import argparse
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np

from champsim_utils import geomean_speedup, find_test_dir


# ── Data collection ───────────────────────────────────────────────────────────

def collect_grid(results_dir):
    """
    Returns:
        phist_sizes : sorted list of pHIST sizes found
        bhist_sizes : sorted list of bHIST sizes found
        fa_lru      : 2-D array [len(phist_sizes), len(bhist_sizes)] — FA + LRU
        fa_lfu      : same — FA + LFU
        hash_dm     : same — direct-mapped hashed (hash_p{N}_b{N})
    """
    baseline_dir = os.path.join(results_dir, "baseline")

    fa_data   = {}  # (pol, pn, bn) -> speedup
    hash_data = {}  # (pn, bn)      -> speedup

    for entry in os.listdir(results_dir):
        mh = re.fullmatch(r"hash_p(\d+)_b(\d+)", entry)
        mf = re.fullmatch(r"(lru|lfu)_p(\d+)_b(\d+)", entry)
        if mh:
            pn, bn = int(mh.group(1)), int(mh.group(2))
            hash_data[(pn, bn)] = geomean_speedup(
                os.path.join(results_dir, entry), baseline_dir)
        elif mf:
            pol, pn, bn = mf.group(1), int(mf.group(2)), int(mf.group(3))
            fa_data[(pol, pn, bn)] = geomean_speedup(
                os.path.join(results_dir, entry), baseline_dir)

    all_keys = {(pn, bn) for (_, pn, bn) in fa_data} | set(hash_data)
    phist_sizes = sorted({pn for pn, _ in all_keys})
    bhist_sizes = sorted({bn for _, bn in all_keys})

    def make_fa_grid(pol):
        grid = np.full((len(phist_sizes), len(bhist_sizes)), float("nan"))
        for i, pn in enumerate(phist_sizes):
            for j, bn in enumerate(bhist_sizes):
                grid[i, j] = fa_data.get((pol, pn, bn), float("nan"))
        return grid

    def make_hash_grid():
        grid = np.full((len(phist_sizes), len(bhist_sizes)), float("nan"))
        for i, pn in enumerate(phist_sizes):
            for j, bn in enumerate(bhist_sizes):
                grid[i, j] = hash_data.get((pn, bn), float("nan"))
        return grid

    return phist_sizes, bhist_sizes, make_fa_grid("lru"), make_fa_grid("lfu"), make_hash_grid()


def ref_speedup(results_dir, exp_name):
    baseline_dir = os.path.join(results_dir, "baseline")
    exp_dir      = os.path.join(results_dir, exp_name)
    if not os.path.isdir(exp_dir):
        return float("nan")
    return geomean_speedup(exp_dir, baseline_dir)


# ── Plotting ──────────────────────────────────────────────────────────────────

def _heatmap(ax, grid, phist_sizes, bhist_sizes, title, vmin, vmax):
    im = ax.imshow(grid, aspect="auto", origin="lower",
                   cmap="RdYlGn", vmin=vmin, vmax=vmax)
    ax.set_xticks(range(len(bhist_sizes)))
    ax.set_xticklabels([str(n) for n in bhist_sizes], rotation=45, ha="right")
    ax.set_yticks(range(len(phist_sizes)))
    ax.set_yticklabels([str(n) for n in phist_sizes])
    ax.set_xlabel("bHIST size (entries)")
    ax.set_ylabel("pHIST size (entries)")
    ax.set_title(title, fontsize=10)
    for i in range(len(phist_sizes)):
        for j in range(len(bhist_sizes)):
            v = grid[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.1f}", ha="center", va="center",
                        fontsize=7, color="black")
    return im


def plot_heatmaps(results_dir, phist_sizes, bhist_sizes,
                  fa_lru, fa_lfu, hash_dm, label, out_dir):
    hash_pred = ref_speedup(results_dir, "hash_pred")
    inf_val   = ref_speedup(results_dir, "inf")

    all_grids = [g for g in [fa_lru, fa_lfu, hash_dm] if not np.all(np.isnan(g))]
    valid = np.concatenate([g[~np.isnan(g)] for g in all_grids]) if all_grids else np.array([0.0, 1.0])
    vmin, vmax = np.nanmin(valid), np.nanmax(valid)

    notes = []
    if not np.isnan(hash_pred):
        notes.append(f"hash_pred={hash_pred:.2f}%")
    if not np.isnan(inf_val):
        notes.append(f"inf={inf_val:.2f}%")
    note_str = f"\n({', '.join(notes)})" if notes else ""

    fig_w = max(6, len(bhist_sizes) * 1.2)
    fig_h = max(4, len(phist_sizes) * 0.9)

    for grid, tag, title in [
        (fa_lru,  "fa_lru",  "FA + LRU"),
        (fa_lfu,  "fa_lfu",  "FA + LFU"),
        (hash_dm, "hash_dm", "Hash DM (no replacement)"),
    ]:
        if np.all(np.isnan(grid)):
            continue
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
        im = _heatmap(ax, grid, phist_sizes, bhist_sizes,
                      f"IPC speedup vs baseline (%) — {title} — {label}",
                      vmin, vmax)
        ax.set_xlabel(ax.get_xlabel() + note_str)
        plt.colorbar(im, ax=ax, label="IPC speedup (%)")
        fig.tight_layout()
        out = os.path.join(out_dir, f"hist_size_{tag}_{label}.png")
        fig.savefig(out, dpi=150)
        plt.close(fig)
        print(f"  Written: {out}")

    # ── LRU − LFU difference (FA only) ───────────────────────────────────────
    diff = fa_lru - fa_lfu
    if not np.all(np.isnan(diff)):
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
        lim = max(abs(np.nanmin(diff)), abs(np.nanmax(diff)), 0.01)
        im = ax.imshow(diff, aspect="auto", origin="lower",
                       cmap="RdBu_r", vmin=-lim, vmax=lim)
        ax.set_xticks(range(len(bhist_sizes)))
        ax.set_xticklabels([str(n) for n in bhist_sizes], rotation=45, ha="right")
        ax.set_yticks(range(len(phist_sizes)))
        ax.set_yticklabels([str(n) for n in phist_sizes])
        ax.set_xlabel("bHIST size (entries)")
        ax.set_ylabel("pHIST size (entries)")
        ax.set_title(f"FA: LRU − LFU speedup difference (%) — {label}", fontsize=10)
        for i in range(len(phist_sizes)):
            for j in range(len(bhist_sizes)):
                v = diff[i, j]
                if not np.isnan(v):
                    ax.text(j, i, f"{v:+.2f}", ha="center", va="center",
                            fontsize=7, color="black")
        plt.colorbar(im, ax=ax, label="LRU − LFU (%)")
        fig.tight_layout()
        out = os.path.join(out_dir, f"hist_size_diff_fa_{label}.png")
        fig.savefig(out, dpi=150)
        plt.close(fig)
        print(f"  Written: {out}")


def plot_marginal(results_dir, phist_sizes, bhist_sizes,
                  fa_lru, fa_lfu, hash_dm, label, out_dir):
    """Line plots: fix one table's best value, sweep the other."""
    hash_pred = ref_speedup(results_dir, "hash_pred")
    inf_val   = ref_speedup(results_dir, "inf")

    best_bcol = int(np.nanargmax(np.nanmean(fa_lru, axis=0))) if not np.all(np.isnan(fa_lru)) else 0
    best_prow = int(np.nanargmax(np.nanmean(fa_lru, axis=1))) if not np.all(np.isnan(fa_lru)) else 0

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)

    for ax, (sweep_sizes, lru_line, lfu_line, hash_line,
             sweep_label, fixed_label, fixed_val) in zip(
        axes,
        [
            (phist_sizes,
             fa_lru[:, best_bcol], fa_lfu[:, best_bcol], hash_dm[:, best_bcol],
             "pHIST size", "bHIST", bhist_sizes[best_bcol]),
            (bhist_sizes,
             fa_lru[best_prow, :], fa_lfu[best_prow, :], hash_dm[best_prow, :],
             "bHIST size", "pHIST", phist_sizes[best_prow]),
        ],
    ):
        xs = range(len(sweep_sizes))
        ax.plot(xs, lru_line,  "o-",  color="#1a9850", label="FA + LRU")
        ax.plot(xs, lfu_line,  "o--", color="#a6d96a", label="FA + LFU")
        ax.plot(xs, hash_line, "s-",  color="#4393c3", label="Hash DM")
        if not np.isnan(hash_pred):
            ax.axhline(hash_pred, color="#d73027", linestyle=":", linewidth=1.2, label="hash_pred (ref)")
        if not np.isnan(inf_val):
            ax.axhline(inf_val, color="gray", linestyle="--", linewidth=0.8, label="inf")
        ax.axhline(0, color="black", linewidth=0.6)
        ax.set_xticks(xs)
        ax.set_xticklabels([str(s) for s in sweep_sizes], rotation=45, ha="right")
        ax.set_xlabel(f"{sweep_label} (entries)")
        ax.set_ylabel("IPC speedup vs baseline (%)")
        ax.set_title(f"{sweep_label} sweep ({fixed_label}={fixed_val})", fontsize=9)
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.3)

    fig.suptitle(f"Marginal return — {label}", fontsize=11)
    fig.tight_layout()
    out = os.path.join(out_dir, f"hist_size_marginal_{label}.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Written: {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results_dir",
                    help="Results directory, or suite name (dpc3|google|qmm) with --test")
    ap.add_argument("--test", action="store_true",
                    help="Find and plot the most recent _test run for the given suite")
    ap.add_argument("--range", choices=["small", "large"], default="small",
                    help="Which size range to plot when using --test (default: small)")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    results_dir = (find_test_dir(args.results_dir, f"hist_{args.range}") if args.test
                   else args.results_dir.rstrip("/"))
    out_dir     = args.out_dir or results_dir
    os.makedirs(out_dir, exist_ok=True)

    label = os.path.basename(results_dir)
    phist_sizes, bhist_sizes, fa_lru, fa_lfu, hash_dm = collect_grid(results_dir)

    if not phist_sizes or not bhist_sizes:
        print(f"ERROR: no size-sweep configs found in {results_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"pHIST sizes: {phist_sizes}")
    print(f"bHIST sizes: {bhist_sizes}")

    plot_heatmaps(results_dir, phist_sizes, bhist_sizes,
                  fa_lru, fa_lfu, hash_dm, label, out_dir)
    plot_marginal(results_dir, phist_sizes, bhist_sizes,
                  fa_lru, fa_lfu, hash_dm, label, out_dir)


if __name__ == "__main__":
    main()
