#!/usr/bin/env python3
"""plot_doa_correlation.py — scatter plot of STLB DoA rate vs LLC DoA-on-DoA-page fraction.

For each trace, parse:
  - STLB DoA rate   : cpu0_STLB DOA / cpu0_STLB total evictions  (x-axis)
  - LLC DoA-on-page : LLC DOA_ON_DOA_STLB_PAGE / LLC total DoA    (y-axis)

Each point is one trace.  Overlaying multiple configs (e.g. baseline, mid_thd1 …)
on the same axes shows how the mid-insertion threshold shifts the relationship.

Usage
-----
    # Single config (e.g. baseline from mid_thd sweep)
    # All mid_thd configs overlaid against the lru/ baseline
    python3 scripts/analysis/plot_doa_correlation.py results/qmm_mid_<date>/

    # Restrict to specific configs
    python3 scripts/analysis/plot_doa_correlation.py results/qmm_mid_<date>/ \\
        --configs mid_thd1 mid_thd3 mid_thd5

Output saved to <results_dir>/plots/doa_correlation.png
"""

import argparse
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_stats(path: Path):
    """Return (stlb_doa_rate, llc_doa_on_page_rate) or None if data missing."""
    text = path.read_text(errors="replace")

    stlb_m = re.search(
        r"cpu0_STLB LIVENESS EVICTIONS:\s+(\d+)\s+DOA:\s+(\d+)",
        text,
    )
    llc_m = re.search(
        r"LLC LIVENESS EVICTIONS:\s+\d+\s+DOA:\s+(\d+)",
        text,
    )
    page_m = re.search(
        r"LLC LIVENESS DOA_ON_DOA_STLB_PAGE:\s+(\d+)",
        text,
    )

    if not (stlb_m and llc_m and page_m):
        return None

    stlb_total = int(stlb_m.group(1))
    stlb_doa   = int(stlb_m.group(2))
    llc_doa    = int(llc_m.group(1))
    llc_on_page= int(page_m.group(1))

    if stlb_total == 0 or llc_doa == 0:
        return None

    return (
        100.0 * stlb_doa    / stlb_total,   # STLB DoA rate (%)
        100.0 * llc_on_page / llc_doa,      # LLC DoA-on-DoA-page rate (%)
    )


def load_config(config_dir: Path):
    """Return list of (trace_name, stlb_doa_rate, llc_on_page_rate)."""
    out_files = sorted(config_dir.glob("*/champsim.out"))
    if not out_files:
        out_files = sorted(config_dir.glob("*.out"))
    rows = []
    n_missing = 0
    for f in out_files:
        trace = f.parent.name if f.name == "champsim.out" else f.stem
        result = parse_stats(f)
        if result is None:
            n_missing += 1
            continue
        rows.append((trace, result[0], result[1]))
    if n_missing:
        print(f"  Note: {n_missing}/{len(out_files)} files skipped (incomplete or missing stat)")
    return rows


# ── Plotting ──────────────────────────────────────────────────────────────────

# Colorblind-friendly palette
PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
           "#9467bd", "#8c564b", "#e377c2", "#7f7f7f"]


def pearson_r(x, y):
    x, y = np.array(x), np.array(y)
    if len(x) < 2:
        return float("nan")
    mx, my = x.mean(), y.mean()
    num = ((x - mx) * (y - my)).sum()
    den = np.sqrt(((x - mx)**2).sum() * ((y - my)**2).sum())
    return num / den if den > 0 else float("nan")


def plot_correlation(suite_data, title, out_path: Path):
    """
    suite_data : list of (config_label, [(trace, stlb_doa, llc_on_page), ...])
    """
    fig, ax = plt.subplots(figsize=(8, 6))

    for i, (label, rows) in enumerate(suite_data):
        if not rows:
            continue
        xs = np.array([r[1] for r in rows])
        ys = np.array([r[2] for r in rows])
        color = PALETTE[i % len(PALETTE)]
        r = pearson_r(xs, ys)
        ax.scatter(xs, ys, s=28, alpha=0.75, color=color, edgecolors="dimgray",
                   linewidths=0.3, zorder=3,
                   label=f"{label}  (r={r:.2f}, n={len(rows)})")

        # Regression line
        if len(xs) >= 2:
            m, b = np.polyfit(xs, ys, 1)
            x_line = np.linspace(xs.min(), xs.max(), 100)
            ax.plot(x_line, m * x_line + b, color=color,
                    linewidth=1.2, linestyle="--", alpha=0.6, zorder=2)

    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.set_xlabel("STLB DoA rate  (% of STLB evictions that are DoA)", fontsize=11)
    ax.set_ylabel("LLC DoA-on-DoA-page rate\n(% of LLC DoA blocks on a DoA STLB page)", fontsize=11)
    ax.set_title(title, fontsize=11)
    ax.legend(fontsize=9, loc="upper left")
    ax.grid(True, alpha=0.25)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("results_dir",
                    help="Top-level sweep results directory")
    ap.add_argument("--configs", nargs="*", default=None,
                    help="Config subdirs to include (default: auto-discover all)")
    ap.add_argument("--out", default=None,
                    help="Output PNG path (default: <results_dir>/plots/doa_correlation.png)")
    args = ap.parse_args()

    base = Path(args.results_dir)
    if not base.is_dir():
        sys.exit(f"ERROR: not a directory: {base}")

    plots_dir = base / "plots"
    plots_dir.mkdir(exist_ok=True)

    # Load lru/ as baseline
    baseline_dir = base / "lru" if (base / "lru").is_dir() else base / "baseline"
    if not baseline_dir.is_dir():
        sys.exit(f"ERROR: no baseline found under {base} (expected lru/ or baseline/)")
    suite_data = []
    print(f"Loading baseline 'lru' from {baseline_dir} ...")
    rows = load_config(baseline_dir)
    if not rows:
        print("  WARNING: no usable data in lru/ — skipped")
    else:
        print(f"  {len(rows)} traces")
        suite_data.append(("lru", rows))

    # Discover or validate configs from results_dir
    if args.configs:
        configs = args.configs
    else:
        # Auto-discover: mid_thd* in numeric order, skip baseline and plots
        all_dirs = [d.name for d in base.iterdir()
                    if d.is_dir() and d.name not in ("plots", "lru", "baseline")]
        def sort_key(name):
            m = re.match(r"mid_thd(\d+)$", name)
            return int(m.group(1)) if m else float("inf")
        configs = sorted(all_dirs, key=sort_key)

    print(f"Configs: {configs}")

    for cfg in configs:
        cfg_dir = base / cfg
        if not cfg_dir.is_dir():
            print(f"  WARNING: {cfg}/ not found — skipped")
            continue
        print(f"Loading '{cfg}' ...")
        rows = load_config(cfg_dir)
        if not rows:
            print(f"  WARNING: no usable data in {cfg}/ — skipped")
            continue
        print(f"  {len(rows)} traces")
        suite_data.append((cfg, rows))

    if not suite_data:
        sys.exit("ERROR: no usable data found")

    out_path = Path(args.out) if args.out else plots_dir / "doa_correlation.png"
    label = base.name
    plot_correlation(suite_data, f"STLB DoA → LLC DoA-on-page correlation — {label}", out_path)


if __name__ == "__main__":
    main()
