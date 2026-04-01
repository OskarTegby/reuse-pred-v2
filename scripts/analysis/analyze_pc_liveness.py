#!/usr/bin/env python3
"""analyze_pc_liveness.py — pooled per-PC liveness scatter and Lorenz curves.

Pool per-PC liveness counts across all traces in a benchmark suite (or a single
trace), then plot the relationship between each PC's eviction share and its DoA
rate.  Because counts are summed before rates are computed, no averaging occurs:
a PC that appears in 20 traces contributes 20× more weight than one that appears
in only one trace.

Primary plot (default): scatter
--------------------------------
Each point = one unique PC across the pooled suite.
  X = eviction share:  PC's total evictions / all evictions in the pool  (%)
  Y = DoA rate:        PC's DoA evictions / PC's total evictions          (%)

The top-right corner identifies the most actionable PCs: high eviction share
AND high DoA rate.  Point colour encodes mostly-dead rate so all three liveness
classes are visible simultaneously.

Secondary plot (--lorenz): concentration summary
-------------------------------------------------
Lorenz curve: sort PCs by eviction count (largest first).
  X = cumulative fraction of PCs considered   (%)
  Y = cumulative fraction of DoA evictions covered  (%)
A curve far above the 45° diagonal means a few PCs drive most DoA evictions.

Usage
-----
    # Whole suite (pool all traces)
    python3 scripts/analyze_pc_liveness.py results/maz_<date>/baseline/ \\
        --cache LLC --out maz

    # Single trace
    python3 scripts/analyze_pc_liveness.py results/maz_<date>/baseline/ \\
        --cache LLC --trace srv_128 --out maz_srv128

    # Multiple suites — one scatter per suite, plus per-class Lorenz comparison
    python3 scripts/analyze_pc_liveness.py \\
        results/maz_<date>/baseline/ results/qmm_<date>/baseline/ \\
        --labels maz qmm --cache LLC --lorenz --out lorenz

Limitation: plain_printer.cc caps output at MAX_PC_ROWS (default 30) PCs per
workload.  Important PCs (high share + high DoA) appear in most workloads and
are therefore captured.  Raise MAX_PC_ROWS for exhaustive coverage.
"""

import argparse
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

# Liveness class colours
DOA_COLOR = "#d62728"
MD_COLOR  = "#ff7f0e"
MA_COLOR  = "#2ca02c"

SUITE_COLORS = ["#1f77b4", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f"]

X_COMMON = np.linspace(0, 1, 500)

# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_pc_liveness(path: Path, cache_name: str):
    """Parse PER-PC LIVENESS block from one *.out file.

    Returns (entries, truncated) where entries is a list of
    (ip, doa, mostly_dead, mostly_alive) and truncated is True if the
    plain_printer MAX_PC_ROWS cap was hit.
    """
    text = path.read_text(errors="replace")
    header_pat = re.compile(
        r"^" + re.escape(cache_name) + r" PER-PC LIVENESS \((\d+) PCs",
        re.MULTILINE,
    )
    m = header_pat.search(text)
    if not m:
        return None, False
    total_pcs = int(m.group(1))
    row_pat = re.compile(
        r"0x([0-9a-fA-F]+)\s+(\d+)\s+"
        r"(\d+)\s+\([\d.]+%\)\s+"
        r"(\d+)\s+\([\d.]+%\)\s+"
        r"(\d+)\s+\([\d.]+%\)"
    )
    entries = [
        (int(rm.group(1), 16), int(rm.group(3)), int(rm.group(4)), int(rm.group(5)))
        for rm in row_pat.finditer(text[m.start():])
    ]
    return entries, len(entries) < total_pcs


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
        print(f"  Note: {n_truncated}/{n_files} files had truncated per-PC tables "
              "(raise MAX_PC_ROWS in plain_printer.cc for full coverage)")
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
    """Scatter: X = eviction share, Y = DoA rate, colour = mostly-dead rate."""
    arrays = pool_to_arrays(pool)
    if arrays is None:
        print(f"  WARNING: empty pool for {suite_label} — scatter skipped")
        return
    ips, doa, md, ma, total = arrays

    grand_total = total.sum()
    if grand_total == 0:
        print(f"  WARNING: zero evictions in pool for {suite_label} — scatter skipped")
        return

    ev_share = total / grand_total * 100                           # X  (log scale)
    doa_rate = np.where(total > 0, doa / total * 100, 0.0)        # Y  (0–100 %)
    md_rate  = np.where(total > 0, md  / total * 100, 0.0)        # colour

    n_pcs = len(ips)
    # Switch to hexbin when there are enough points that individual markers
    # would overlap badly.  Hexbin bins the plane and colours by point density,
    # keeping the plot readable regardless of scale.
    USE_HEXBIN = n_pcs > 3000

    fig, ax = plt.subplots(figsize=(16, 11))

    if USE_HEXBIN:
        # Log-transform X manually so hexbin bins evenly in log-space.
        log_share = np.log10(np.clip(ev_share, 1e-4, None))
        hb = ax.hexbin(log_share, doa_rate,
                       C=md_rate, reduce_C_function=np.mean,
                       gridsize=40, cmap="viridis", mincnt=1,
                       vmin=0, vmax=100,
                       linewidths=0.2, zorder=3)
        cbar = fig.colorbar(hb, ax=ax, pad=0.02)
        cbar.set_label("Mostly-dead rate (%)")
        # Set x-axis limits to the actual data range (with a small margin)
        # so empty log-space on either side is not shown.
        x_margin = 0.3   # in log10 units
        ax.set_xlim(log_share.min() - x_margin, log_share.max() + x_margin)
        # Tick marks at every integer power of 10 within the data range
        x_lo = int(np.floor(log_share.min()))
        x_hi = int(np.ceil(log_share.max()))
        xtick_vals = list(range(x_lo, x_hi + 1))
        ax.set_xticks(xtick_vals)
        ax.set_xticklabels([f"$10^{{{v}}}$%" for v in xtick_vals])
        ax.set_xlabel("Eviction share (% of all pooled evictions, log scale)")
    else:
        # Scatter: colour encodes mostly-dead rate.
        # viridis runs dark-purple (0 %) → yellow (100 %) — both ends clearly
        # visible on a white background.  edgecolors ensures every point has a
        # visible outline even when the face colour is very light.
        sc = ax.scatter(ev_share, doa_rate,
                        c=md_rate, cmap="viridis",
                        vmin=0, vmax=100,
                        s=22, alpha=0.85,
                        edgecolors="dimgray", linewidths=0.3,
                        zorder=3)
        cbar = fig.colorbar(sc, ax=ax, pad=0.02)
        cbar.set_label("Mostly-dead rate (%)")
        ax.set_xscale("log")
        ax.set_xlabel("Eviction share (% of all pooled evictions, log scale)")

        # Annotate the top-5 most impactful PCs (highest share × DoA rate)
        importance = ev_share * doa_rate
        top_idx = np.argsort(importance)[-5:]
        for i in top_idx:
            if ev_share[i] > 0.05 and doa_rate[i] > 10:
                ax.annotate(f"0x{ips[i]:x}",
                            (ev_share[i], doa_rate[i]),
                            textcoords="offset points", xytext=(4, 2),
                            fontsize=6, color="black", zorder=5)

    # Reference lines
    ax.axhline(50, color="gray", linewidth=0.6, linestyle=":", zorder=1)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.set_ylabel("DoA rate (% of PC's evictions that are DoA)")
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
        (doa, DOA_COLOR, "-",  "DoA"),
        (md,  MD_COLOR,  "--", "Mostly-dead"),
        (ma,  MA_COLOR,  ":",  "Mostly-alive"),
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
        ("DoA",         DOA_COLOR, "-"),
        ("Mostly-dead", MD_COLOR,  "--"),
        ("Mostly-alive",MA_COLOR,  ":"),
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("results_dirs", nargs="+",
                    help="One or more directories with *.out files (one per suite)")
    ap.add_argument("--labels", nargs="*",
                    help="Suite labels (default: directory names)")
    ap.add_argument("--cache",  default="LLC", choices=["LLC", "cpu0_STLB"],
                    help="Cache to analyse (default: LLC)")
    ap.add_argument("--trace",  default=None,
                    help="Only use files whose name contains this substring")
    ap.add_argument("--lorenz", action="store_true",
                    help="Also generate Lorenz concentration plots")
    ap.add_argument("--out",    default=None,
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

    print("\nGenerating scatter plots ...")
    for label, pool, n_files in suite_pools:
        safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", label)
        plot_scatter(pool, label, args.cache, n_files,
                     Path(f"{out_prefix}_{args.cache}_{safe}_scatter.png"))

    if args.lorenz:
        print("\nGenerating Lorenz plots ...")
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
