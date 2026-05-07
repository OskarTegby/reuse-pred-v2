#!/usr/bin/env python3
"""plot_doa_correlation.py — STLB DoA rate vs LLC DoA-on-DoA-page fraction.

Two modes:

  --bar  (default)
      Bar chart: one bar per workload showing the % of LLC DoA cache blocks
      that landed on a DoA STLB page translation, plus a geomean bar.
      Useful for understanding how strongly LLC dead-on-arrival behaviour is
      explained by STLB liveness.  Uses the lru/ config by default.

  --scatter
      Scatter plot with one point per trace: STLB DoA rate (x) vs
      LLC DoA-on-page rate (y).  Overlaying multiple configs shows how the
      mid-insertion threshold shifts the relationship.

Usage
-----
    # Bar chart — lru baseline only (default)
    python3 scripts/analysis/plot_doa_correlation.py results/qmm_pol_<date>/ --configs

    # Scatter — all mid_thd configs overlaid
    python3 scripts/analysis/plot_doa_correlation.py results/qmm_mid_<date>/ --scatter

    # Scatter — specific configs only
    python3 scripts/analysis/plot_doa_correlation.py results/qmm_mid_<date>/ \\
        --scatter --configs mid_thd1 mid_thd3 mid_thd5

Output saved to <results_dir>/plots/doa_correlation_bar.png or doa_correlation.png
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

from spec_weights import SPEC_WEIGHTS, benchmark_name


def _benchmark_weighted_geomean(vals_by_wl: "dict[str, float]") -> float:
    """Benchmark-weighted geomean of absolute values (e.g. DoA rates).

    For SPEC traces: weighted geomean within benchmark, equal-weight across.
    For others: flat equal-weight geomean.
    """
    eps = 1e-9
    groups: dict = {}
    for wl, v in vals_by_wl.items():
        groups.setdefault(benchmark_name(wl), []).append(wl)
    per_bench = []
    for wl_list in groups.values():
        if SPEC_WEIGHTS:
            pairs = [(vals_by_wl[wl], SPEC_WEIGHTS.get(wl)) for wl in wl_list]
            if any(w is not None for _, w in pairs):
                pairs = [(v, w) for v, w in pairs if w is not None]
                total_w = sum(w for _, w in pairs)
                if total_w > 0:
                    per_bench.append(float(np.exp(
                        sum((w / total_w) * np.log(max(v, eps)) for v, w in pairs))))
                    continue
        vals = [vals_by_wl[wl] for wl in wl_list]
        per_bench.append(float(np.exp(np.mean(np.log(np.clip(vals, eps, None))))))
    if not per_bench:
        return float("nan")
    return float(np.exp(np.mean(np.log(np.clip(per_bench, eps, None)))))


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


def geomean(vals):
    arr = np.clip(np.asarray(vals, dtype=float), 1e-9, None)
    return float(np.exp(np.mean(np.log(arr))))


def plot_bar(rows, title, out_path: Path):
    """
    rows : list of (trace_name, stlb_doa_rate, llc_on_page_rate)
    Plots llc_on_page_rate per workload + geomean bar.
    """
    traces = [r[0] for r in rows]
    values = [r[2] for r in rows]
    gm     = _benchmark_weighted_geomean(dict(zip(traces, values)))

    xlabels = traces + ["GeoMean"]
    xvals   = list(values) + [gm]
    x       = np.arange(len(xlabels))

    colors = ["#2166ac"] * len(traces) + ["#d73027"]

    fig_w = max(10, len(xlabels) * 0.45 + 2)
    fig, ax = plt.subplots(figsize=(fig_w, 5))

    bars = ax.bar(x, xvals, color=colors, edgecolor="black", linewidth=0.5)

    # Annotate each bar
    for bar, v in zip(bars, xvals):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                f"{v:.1f}%", ha="center", va="bottom", fontsize=7)

    ax.axvline(len(traces) - 0.5, color="black", linewidth=1.0, linestyle="--")
    ax.set_xticks(x)
    ax.set_xticklabels(xlabels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("LLC DoA blocks on a DoA STLB page (%)", fontsize=11)
    ax.set_ylim(0, min(105, max(xvals) * 1.2))
    ax.set_title(title, fontsize=11)
    ax.grid(axis="y", alpha=0.25)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")
    print(f"  GeoMean: {gm:.1f}%  (n={len(traces)} workloads)")


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
    ap.add_argument("--scatter", action="store_true",
                    help="Scatter plot mode (default: bar chart per workload)")
    ap.add_argument("--configs", nargs="*", default=None,
                    help="Config subdirs to overlay (default: auto-discover; "
                         "pass with no args to show lru baseline only)")
    ap.add_argument("--out", default=None,
                    help="Output PNG path (default: <results_dir>/plots/doa_correlation{_bar}.png)")
    args = ap.parse_args()

    base = Path(args.results_dir)
    if not base.is_dir():
        sys.exit(f"ERROR: not a directory: {base}")

    plots_dir = base / "plots"
    plots_dir.mkdir(exist_ok=True)

    # Always load lru/ as the baseline
    baseline_dir = base / "lru" if (base / "lru").is_dir() else base / "baseline"
    if not baseline_dir.is_dir():
        sys.exit(f"ERROR: no baseline found under {base} (expected lru/ or baseline/)")
    print(f"Loading baseline 'lru' from {baseline_dir} ...")
    lru_rows = load_config(baseline_dir)
    if not lru_rows:
        sys.exit("ERROR: no usable data in lru/")
    print(f"  {len(lru_rows)} traces")

    label = base.name

    # ── Bar mode (default) ────────────────────────────────────────────────────
    if not args.scatter:
        out_path = Path(args.out) if args.out else plots_dir / "doa_correlation_bar.png"
        plot_bar(lru_rows,
                 f"LLC DoA blocks on a DoA STLB page — {label} / lru",
                 out_path)
        return

    # ── Scatter mode ──────────────────────────────────────────────────────────
    suite_data = [("lru", lru_rows)]

    if args.configs is not None:
        configs = args.configs  # may be empty → lru only
    else:
        all_dirs = [d.name for d in base.iterdir()
                    if d.is_dir() and d.name not in ("plots", "lru", "baseline")]
        def sort_key(name):
            m = re.match(r"mid_thd(\d+)$", name)
            return int(m.group(1)) if m else float("inf")
        configs = sorted(all_dirs, key=sort_key)

    print(f"Overlay configs: {configs or '(none)'}")
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

    out_path = Path(args.out) if args.out else plots_dir / "doa_correlation.png"
    plot_correlation(suite_data, f"STLB DoA → LLC DoA-on-page correlation — {label}", out_path)


if __name__ == "__main__":
    main()
