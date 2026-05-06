#!/usr/bin/env python3
"""analyze_pc_liveness.py — pooled per-PC liveness plots.

Pool per-PC liveness counts across all traces in a benchmark suite (or a single
trace).  Counts are summed before rates are computed, so no averaging occurs: a
PC that appears in 20 traces contributes 20× more weight than one in only one.

Primary plots (always generated)
---------------------------------
1. Dead-rate Lorenz curve
   Sort PCs by combined dead rate = (DoA + mostly-dead) / total evictions,
   largest first.
     X = cumulative % of PCs considered
     Y = cumulative % of total dead (DoA + mostly-dead) evictions covered
   A curve bowing far above the 45° diagonal means a few high-dead-rate PCs
   account for most dead evictions — the PC index is well-focused.
   Multiple suites are overlaid on one axes for direct comparison.

2. Top-K composition bar chart
   Take the PCs (in dead-rate order) that together cover --coverage % of all
   dead evictions, then show each as a horizontal stacked bar split into
   DoA | mostly-dead absolute counts.  Answers: is the concentrated dead
   traffic driven by DoA, mostly-dead, or both?

Secondary plot (--scatter): eviction share vs dead rate
-------------------------------------------------------
Each point = one unique PC.
  X = eviction share (log scale)   Y = combined dead rate
  Colour = DoA fraction of dead (how much of a PC's dead traffic is DoA)

Legacy plot (--lorenz): per-class Lorenz curves
-----------------------------------------------
Separate Lorenz curves for DoA / mostly-dead / mostly-alive, sorted by
per-class eviction count.  Useful for detailed breakdown but harder to read
than the primary dead-rate Lorenz.

Usage
-----
    # Whole suite (pool all traces) — dead-rate Lorenz + composition bar
    python3 scripts/analyze_pc_liveness.py results/maz_<date>/baseline/ \\
        --cache LLC --out maz

    # Compare two suites
    python3 scripts/analyze_pc_liveness.py \\
        results/maz_<date>/baseline/ results/qmm_<date>/baseline/ \\
        --labels maz qmm --cache LLC

    # Also generate scatter and legacy Lorenz
    python3 scripts/analyze_pc_liveness.py results/maz_<date>/baseline/ \\
        --cache LLC --scatter --lorenz

Per-PC stats are read from pc_liveness.csv written alongside champsim.out.
All PCs are captured (no truncation).
"""

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.colors import LogNorm
import numpy as np

from colors import LIVENESS_COLORS

SUITE_COLORS = ["#1f77b4", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f"]

X_COMMON = np.linspace(0, 1, 500)

# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_pc_liveness(path: Path, cache_name: str):
    """Parse per-PC liveness data from pc_liveness.csv next to path.

    Returns (entries, truncated) where entries is a list of
    (ip, doa, mostly_dead, mostly_alive).
    """
    csv_path = path.parent / "pc_liveness.csv"
    if not csv_path.exists():
        return None, False
    entries = []
    try:
        with csv_path.open(newline="") as f:
            for row in csv.DictReader(f):
                if row["cache"] == cache_name:
                    entries.append((
                        int(row["pc"], 16),
                        int(row["doa"]),
                        int(row["mostly_dead"]),
                        int(row["mostly_alive"]),
                    ))
    except Exception:
        return None, False
    return entries or None, False


def pool_suite(results_dir: Path, cache_name: str, trace_filter: str | None):
    """Sum per-PC counts across all matching traces in results_dir.

    trace_filter: if set, only files whose stem contains this substring are used.
    Returns (pool, n_files, n_truncated) where pool maps ip → [doa, md, ma].
    """
    # Support both cluster layout (<dir>/<trace>/champsim.out) and flat layout (<dir>/<trace>.out)
    out_files = sorted(results_dir.glob("*/champsim.out"))
    nested = True
    if not out_files:
        out_files = sorted(results_dir.glob("*.out"))
        nested = False
    if not out_files:
        sys.exit(f"ERROR: no output files found in {results_dir}\n"
                 "Expected either <dir>/*.out or <dir>/*/champsim.out")

    if trace_filter:
        key = lambda f: f.parent.name if nested else f.stem
        out_files = [f for f in out_files if trace_filter in key(f)]
        if not out_files:
            sys.exit(f"ERROR: no files matching '{trace_filter}' in {results_dir}")

    pool = defaultdict(lambda: [0, 0, 0])  # ip → [doa, md, ma]
    n_files = 0
    n_skipped = 0
    n_truncated = 0

    for f in out_files:
        entries, truncated = parse_pc_liveness(f, cache_name)
        if entries is None:
            n_skipped += 1
            continue
        if truncated:
            n_truncated += 1
        for ip, doa, md, ma in entries:
            pool[ip][0] += doa
            pool[ip][1] += md
            pool[ip][2] += ma
        n_files += 1

    if n_skipped:
        print(f"  Note: {n_skipped}/{n_files + n_skipped} files had no PER-PC LIVENESS block "
              f"for {cache_name} — skipped")
    if n_truncated:
        print(f"  Note: {n_truncated}/{n_files} files had truncated per-PC tables")
    return pool, n_files, n_truncated


def pool_to_arrays(pool: dict):
    """Convert pooled dict to numpy arrays (ips, doa, md, ma, total)."""
    if not pool:
        return None
    ips   = np.array(list(pool.keys()), dtype=np.uint64)
    counts= np.array(list(pool.values()), dtype=float)  # (n, 3)
    doa   = counts[:, 0]
    md    = counts[:, 1]
    ma    = counts[:, 2]
    total = doa + md + ma
    return ips, doa, md, ma, total


# ── Scatter plot ──────────────────────────────────────────────────────────────

def plot_scatter(pool: dict, suite_label: str, cache_name: str,
                 n_files: int, out_path: Path):
    """Scatter: X = eviction share, Y = combined dead rate, colour = DoA fraction of dead."""
    arrays = pool_to_arrays(pool)
    if arrays is None:
        print(f"  WARNING: empty pool for {suite_label} — scatter skipped")
        return
    ips, doa, md, ma, total = arrays

    grand_total = total.sum()
    if grand_total == 0:
        print(f"  WARNING: zero evictions in pool for {suite_label} — scatter skipped")
        return

    dead      = doa + md
    ev_share  = total / grand_total * 100                                    # X (log)
    dead_rate = np.where(total > 0, dead / total * 100, 0.0)                # Y (0–100 %)
    # Colour: fraction of a PC's dead traffic that is DoA (vs mostly-dead).
    # 0 = all mostly-dead (orange end), 1 = all DoA (red end).
    doa_frac  = np.where(dead > 0, doa / dead * 100, 0.0)

    n_pcs = len(ips)
    USE_HEXBIN = n_pcs > 3000

    fig, ax = plt.subplots(figsize=(16, 11))

    if USE_HEXBIN:
        log_share = np.log10(np.clip(ev_share, 1e-4, None))
        hb = ax.hexbin(log_share, dead_rate,
                       C=doa_frac, reduce_C_function=np.mean,
                       gridsize=40, cmap="RdYlGn_r", mincnt=1,
                       vmin=0, vmax=100,
                       linewidths=0.2, zorder=3)
        cbar = fig.colorbar(hb, ax=ax, pad=0.02)
        cbar.set_label("DoA fraction of dead (%)")
        x_margin = 0.3
        ax.set_xlim(log_share.min() - x_margin, log_share.max() + x_margin)
        x_lo = int(np.floor(log_share.min()))
        x_hi = int(np.ceil(log_share.max()))
        xtick_vals = list(range(x_lo, x_hi + 1))
        ax.set_xticks(xtick_vals)
        ax.set_xticklabels([f"$10^{{{v}}}$%" for v in xtick_vals])
        ax.set_xlabel("Eviction share (% of all pooled evictions, log scale)")
    else:
        sc = ax.scatter(ev_share, dead_rate,
                        c=doa_frac, cmap="RdYlGn_r",
                        vmin=0, vmax=100,
                        s=22, alpha=0.85,
                        edgecolors="dimgray", linewidths=0.3,
                        zorder=3)
        cbar = fig.colorbar(sc, ax=ax, pad=0.02)
        cbar.set_label("DoA fraction of dead (%)")
        ax.set_xscale("log")
        ax.set_xlabel("Eviction share (% of all pooled evictions, log scale)")

        # Annotate the top-5 most impactful PCs (highest share × dead rate)
        importance = ev_share * dead_rate
        top_idx = np.argsort(importance)[-5:]
        for i in top_idx:
            if ev_share[i] > 0.05 and dead_rate[i] > 10:
                ax.annotate(f"0x{ips[i]:x}",
                            (ev_share[i], dead_rate[i]),
                            textcoords="offset points", xytext=(4, 2),
                            fontsize=6, color="black", zorder=5)

    ax.axhline(50, color="gray", linewidth=0.6, linestyle=":", zorder=1)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.set_ylabel("Dead rate (% of PC's evictions that are DoA or mostly-dead)")
    ax.set_ylim(-2, 102)
    ax.grid(True, alpha=0.2, which="both")

    trace_desc = f"{n_files} trace{'s' if n_files != 1 else ''} pooled"
    mode_tag = " [hexbin]" if USE_HEXBIN else ""
    ax.set_title(
        f"{cache_name} per-PC liveness — {suite_label}{mode_tag}\n"
        f"({trace_desc}, {n_pcs:,} unique PCs, "
        f"{int(grand_total):,} total evictions)"
    )

    fig.tight_layout()
    fig.savefig(out_path, dpi=300)
    plt.close(fig)
    print(f"  Saved: {out_path}  ({len(ips):,} PCs, {int(grand_total):,} evictions)")


# ── Lorenz curve ──────────────────────────────────────────────────────────────

def lorenz_xy(values: np.ndarray):
    v = np.sort(values)[::-1]
    total = v.sum()
    if total == 0:
        return np.array([0.0, 1.0]), np.array([0.0, 1.0])
    x = np.linspace(0, 1, len(v) + 1)
    y = np.concatenate([[0.0], np.cumsum(v) / total])
    return x, y


def plot_lorenz_suite(pool: dict, suite_label: str, cache_name: str,
                      n_files: int, out_path: Path):
    """Lorenz curves for DoA / mostly-dead / mostly-alive from one pooled suite."""
    arrays = pool_to_arrays(pool)
    if arrays is None:
        return
    _, doa, md, ma, _ = arrays

    fig, ax = plt.subplots(figsize=(7, 6))
    ax.plot([0, 100], [0, 100], color="black", linewidth=0.8, linestyle="--",
            label="Equal distribution", zorder=1)
    ax.axvline(10, color="gray", linewidth=0.6, linestyle=":", zorder=1)

    for vals, color, ls, label in [
        (doa, LIVENESS_COLORS["doa"], "-",  "DoA"),
        (md,  LIVENESS_COLORS["mostly_dead"],  "--", "Mostly-dead"),
        (ma,  LIVENESS_COLORS["mostly_alive"],  ":",  "Mostly-alive"),
    ]:
        x, y = lorenz_xy(vals)
        ax.plot(x * 100, y * 100, color=color, linestyle=ls,
                linewidth=2.2, label=label, zorder=3)
        # Annotate x=10% crossing
        idx = np.searchsorted(x, 0.10)
        if idx < len(y):
            y10 = float(y[idx]) * 100
            ax.plot(10, y10, "o", color=color, markersize=4, zorder=5)
            ax.text(11, y10, f"{y10:.0f}%", fontsize=7, color=color, va="center")

    trace_desc = f"{n_files} trace{'s' if n_files != 1 else ''} pooled"
    ax.set_xlabel("Cumulative % of PCs  (sorted by eviction count ↓)")
    ax.set_ylabel("Cumulative % of evictions covered")
    ax.set_title(
        f"{cache_name} eviction concentration — {suite_label}\n"
        f"({trace_desc}, PCs sorted by eviction count)"
    )
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(True, alpha=0.25)

    fig.tight_layout()
    fig.savefig(out_path, dpi=300)
    plt.close(fig)
    print(f"  Saved: {out_path}")


def plot_lorenz_by_class(suite_pools: list, cache_name: str, out_prefix: str):
    """One Lorenz plot per liveness class, comparing all suites."""
    for cls_idx, (cls_name, color_cls, ls) in enumerate([
        ("DoA",         LIVENESS_COLORS["doa"], "-"),
        ("Mostly-dead", LIVENESS_COLORS["mostly_dead"],  "--"),
        ("Mostly-alive",LIVENESS_COLORS["mostly_alive"],  ":"),
    ]):
        fig, ax = plt.subplots(figsize=(7, 6))
        ax.plot([0, 100], [0, 100], color="black", linewidth=0.8, linestyle="--",
                label="Equal distribution", zorder=1)
        ax.axvline(10, color="gray", linewidth=0.6, linestyle=":", zorder=1)

        for i, (label, pool, n_files) in enumerate(suite_pools):
            arrays = pool_to_arrays(pool)
            if arrays is None:
                continue
            _, doa, md, ma, _ = arrays
            vals = [doa, md, ma][cls_idx]
            color = SUITE_COLORS[i % len(SUITE_COLORS)]
            x, y = lorenz_xy(vals)
            ax.plot(x * 100, y * 100, color=color, linewidth=2.2,
                    label=f"{label} ({n_files} traces)", zorder=3)
            idx = np.searchsorted(x, 0.10)
            if idx < len(y):
                y10 = float(y[idx]) * 100
                ax.plot(10, y10, "o", color=color, markersize=4, zorder=5)
                ax.text(11, y10, f"{y10:.0f}%", fontsize=7, color=color, va="center")

        safe_cls = cls_name.lower().replace("-", "_")
        ax.set_xlabel("Cumulative % of PCs  (sorted by eviction count ↓)")
        ax.set_ylabel(f"Cumulative % of {cls_name} evictions covered")
        ax.set_title(
            f"{cache_name} — {cls_name} eviction concentration\n"
            "(pooled per suite, one curve per suite)"
        )
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
        ax.legend(loc="lower right", fontsize=9)
        ax.grid(True, alpha=0.25)

        fig.tight_layout()
        out_path = Path(f"{out_prefix}_{cache_name}_{safe_cls}.png")
        fig.savefig(out_path, dpi=300)
        plt.close(fig)
        print(f"  Saved: {out_path}")


# ── Dead-rate Lorenz ──────────────────────────────────────────────────────────

def plot_lorenz_dead_rate(suite_pools: list, cache_name: str, out_path: Path):
    """Lorenz curve sorted by combined dead rate, all suites overlaid.

    Sort PCs by (doa + md) / total descending.  Y accumulates absolute dead
    eviction counts so low-volume PCs don't dominate even if their rate is 1.0.
    """
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.plot([0, 100], [0, 100], color="black", linewidth=0.8, linestyle="--",
            label="Equal distribution", zorder=1)
    ax.axvline(10, color="gray", linewidth=0.6, linestyle=":", zorder=1)

    for i, (label, pool, n_files) in enumerate(suite_pools):
        arrays = pool_to_arrays(pool)
        if arrays is None:
            continue
        _, doa, md, _, total = arrays
        dead = doa + md
        grand_dead = dead.sum()
        if grand_dead == 0:
            continue

        dead_rate = np.where(total > 0, dead / total, 0.0)
        order = np.argsort(dead_rate)[::-1]
        dead_sorted = dead[order]

        x = np.linspace(0, 1, len(dead_sorted) + 1)
        y = np.concatenate([[0.0], np.cumsum(dead_sorted) / grand_dead])

        color = SUITE_COLORS[i % len(SUITE_COLORS)]
        n_pcs = len(dead_sorted)
        ax.plot(x * 100, y * 100, color=color, linewidth=2.2,
                label=f"{label} ({n_files} trace{'s' if n_files != 1 else ''}, {n_pcs:,} PCs)",
                zorder=3)
        idx = np.searchsorted(x, 0.10)
        if idx < len(y):
            y10 = float(y[idx]) * 100
            ax.plot(10, y10, "o", color=color, markersize=4, zorder=5)
            ax.text(11, y10, f"{y10:.0f}%", fontsize=7, color=color, va="center")

    ax.set_xlabel("Cumulative % of PCs  (sorted by dead rate ↓)")
    ax.set_ylabel("Cumulative % of dead evictions covered")
    ax.set_title(f"{cache_name} dead eviction concentration by PC dead rate")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(True, alpha=0.25)

    fig.tight_layout()
    fig.savefig(out_path, dpi=300)
    plt.close(fig)
    print(f"  Saved: {out_path}")


# ── Top-K composition bar ─────────────────────────────────────────────────────

def plot_top_k_composition(pool: dict, suite_label: str, cache_name: str,
                           n_files: int, coverage: float, out_path: Path):
    """Stacked horizontal bar chart: DoA vs mostly-dead for the top-K PCs.

    Selects PCs in dead-rate order until their combined dead evictions reach
    `coverage` of the grand total.  Bars are sorted by absolute dead count so
    the largest contributors appear at the top.
    """
    arrays = pool_to_arrays(pool)
    if arrays is None:
        return
    ips, doa, md, _, total = arrays
    dead = doa + md
    grand_dead = dead.sum()
    if grand_dead == 0:
        print(f"  WARNING: zero dead evictions for {suite_label} — composition skipped")
        return

    # Select top-K by dead rate until coverage threshold is reached.
    dead_rate = np.where(total > 0, dead / total, 0.0)
    rate_order = np.argsort(dead_rate)[::-1]
    cumsum = np.cumsum(dead[rate_order])
    k = int(np.searchsorted(cumsum, coverage * grand_dead)) + 1
    k = min(k, len(ips), 100)

    idx_k  = rate_order[:k]
    ips_k  = ips[idx_k]
    doa_k  = doa[idx_k]
    md_k   = md[idx_k]
    dead_k = dead[idx_k]

    # Sort bars by absolute dead count ascending so largest sits at the top.
    bar_order = np.argsort(dead_k)
    ips_plot = ips_k[bar_order]
    doa_plot = doa_k[bar_order]
    md_plot  = md_k[bar_order]

    y_pos  = np.arange(k)
    labels = [f"0x{ip:x}" for ip in ips_plot]

    fig, ax = plt.subplots(figsize=(9, max(4, k * 0.40 + 1.5)))
    ax.barh(y_pos, doa_plot, color=LIVENESS_COLORS["doa"], label="DoA",         height=0.6)
    ax.barh(y_pos, md_plot,  left=doa_plot,   color=LIVENESS_COLORS["mostly_dead"],
            label="Mostly-dead", height=0.6)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_xlabel("Dead evictions (pooled count)")
    ax.set_title(
        f"{cache_name} top-{k} PCs by dead rate — DoA vs mostly-dead\n"
        f"({suite_label}, {n_files} trace{'s' if n_files != 1 else ''} pooled, "
        f"covering {coverage * 100:.0f}% of dead evictions)"
    )
    ax.legend(loc="lower right", fontsize=9)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax.grid(True, axis="x", alpha=0.25)

    fig.tight_layout()
    fig.savefig(out_path, dpi=300)
    plt.close(fig)
    print(f"  Saved: {out_path}  (top {k} PCs, {coverage * 100:.0f}% coverage)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("results_dirs", nargs="+",
                    help="One or more directories with *.out files (one per suite)")
    ap.add_argument("--labels",    nargs="*",
                    help="Suite labels (default: directory names)")
    ap.add_argument("--cache",     default="LLC", choices=["LLC", "cpu0_STLB"],
                    help="Cache to analyse (default: LLC)")
    ap.add_argument("--trace",     default=None,
                    help="Only use files whose name contains this substring")
    ap.add_argument("--coverage",  type=float, default=0.80,
                    help="Dead-eviction coverage threshold for composition bar (default: 0.80)")
    ap.add_argument("--scatter",   action="store_true",
                    help="Also generate eviction-share vs dead-rate scatter plots")
    ap.add_argument("--lorenz",    action="store_true",
                    help="Also generate legacy per-class Lorenz plots")
    ap.add_argument("--out",       default=None,
                    help="Output file prefix (default: <run_dir>/plots/pc_liveness)")
    args = ap.parse_args()

    dirs = [Path(d) for d in args.results_dirs]
    for d in dirs:
        if not d.is_dir():
            sys.exit(f"ERROR: {d} is not a directory")

    labels = args.labels or [d.parent.name if d.name == "baseline" else d.name
                              for d in dirs]
    if len(labels) != len(dirs):
        sys.exit("ERROR: --labels count must match number of directories")

    # Default output prefix: <run_dir>/plots/pc_liveness
    # run_dir is the parent of the first input dir (which is a config subdir).
    run_dir = dirs[0].parent
    plots_dir = run_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    out_prefix = args.out or str(plots_dir / "pc_liveness")

    suite_pools = []   # (label, pool_dict, n_files)

    for label, d in zip(labels, dirs):
        print(f"\nPooling suite '{label}' from {d} ...")
        pool, n_files, _ = pool_suite(d, args.cache, args.trace)
        if not pool:
            print(f"  WARNING: empty pool for '{label}' — skipped")
            continue
        suite_pools.append((label, pool, n_files))

    if not suite_pools:
        sys.exit("ERROR: no usable data")

    print("\nGenerating dead-rate Lorenz plot ...")
    plot_lorenz_dead_rate(suite_pools, args.cache,
                          Path(f"{out_prefix}_{args.cache}_dead_rate_lorenz.png"))

    print("\nGenerating top-K composition bar charts ...")
    for label, pool, n_files in suite_pools:
        safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", label)
        plot_top_k_composition(pool, label, args.cache, n_files, args.coverage,
                               Path(f"{out_prefix}_{args.cache}_{safe}_composition.png"))

    if args.scatter:
        print("\nGenerating scatter plots ...")
        for label, pool, n_files in suite_pools:
            safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", label)
            plot_scatter(pool, label, args.cache, n_files,
                         Path(f"{out_prefix}_{args.cache}_{safe}_scatter.png"))

    if args.lorenz:
        print("\nGenerating legacy per-class Lorenz plots ...")
        for label, pool, n_files in suite_pools:
            safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", label)
            plot_lorenz_suite(pool, label, args.cache, n_files,
                              Path(f"{out_prefix}_{args.cache}_{safe}_lorenz.png"))
        if len(suite_pools) > 1:
            print("\nGenerating per-class Lorenz comparison ...")
            plot_lorenz_by_class(suite_pools, args.cache, out_prefix)

    print("\nDone.")


if __name__ == "__main__":
    main()
