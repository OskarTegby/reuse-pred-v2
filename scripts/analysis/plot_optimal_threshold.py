#!/usr/bin/env python3
"""plot_optimal_threshold.py — per-trace oracle-N speedup, strip-chart style.

Matches the style of liveness_corr_strip.png:
  • One column per configuration (scope / key type)
  • Top row: jittered per-trace speedup dots + geomean diamond per suite
  • Bottom row: stacked bar showing the distribution of optimal N per suite
  • Suite order and colours match the liveness strip (SPEC → Google → Qualcomm)

Usage
-----
    python3 scripts/analysis/plot_optimal_threshold.py \\
        --configs \\
          "STLB only:#2166ac:results/stlb_mid_study/qmm_stlb_mid_addr_20260422_1337,results/stlb_mid_study/dpc3_stlb_mid_addr_20260422_1337,results/stlb_mid_study/google_stlb_mid_addr_20260422_1338" \\
          "LLC only:#d6604d:results/llc_repl_pol_study/qmm_mid_addr_20260427_1626,results/llc_repl_pol_study/dpc3_mid_addr_20260427_1626,results/llc_repl_pol_study/google_mid_addr_20260427_1626" \\
          "LLC+STLB:#1a9850:results/both_mid_study/qmm_both_mid_addr_20260426_1113,results/both_mid_study/dpc3_both_mid_addr_20260426_1113,results/both_mid_study/google_both_mid_addr_20260426_1113" \\
        --suite-labels "SPEC (DPC3)" Google Qualcomm \\
        --max-n 10 \\
        --out results/plots/optimal_threshold/optimal_speedup.png

Each --configs value is: "panel_label:scope_colour:dir_suite0,dir_suite1,..."
The scope colour drives the N-shading ramp in the distribution tile below.
"""

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.ticker as mticker
import matplotlib.pyplot as plt
import numpy as np

from colors import SUITE_COLORS
from champsim_utils import parse_ipc

# ── IPC parsing ───────────────────────────────────────────────────────────────

def _load_optimal_data(sweep_dir: Path, max_n: int) -> "dict[str, tuple[float,int]]":
    """Return {trace: (optimal_speedup_%, optimal_n)}."""
    lru_dir = sweep_dir / "lru"
    baselines: dict = {}
    for f in sorted(lru_dir.glob("*/champsim.out")):
        v = parse_ipc(f)
        if v is not None:
            baselines[f.parent.name] = v
    if not baselines:
        print(f"  WARNING: no baseline in {lru_dir}", file=sys.stderr)
        return {}
    result: dict = {}
    for wl, base_ipc in baselines.items():
        if base_ipc <= 0:
            continue
        best_pct, best_n = float("-inf"), -1
        for n in range(1, max_n + 1):
            f = sweep_dir / f"mid_thd{n}" / wl / "champsim.out"
            v = parse_ipc(f)
            if v is not None:
                pct = (v / base_ipc - 1.0) * 100.0
                if pct > best_pct:
                    best_pct, best_n = pct, n
        if best_n >= 1:
            result[wl] = (best_pct, best_n)
    return result


# ── Argument parsing ──────────────────────────────────────────────────────────

def _parse_config_arg(s: str):
    """Parse "label:color:dir0,dir1,..." → (label, color, [Path,...])."""
    label, sep, rest = s.partition(":")
    if not sep:
        sys.exit(f"ERROR: --configs value must be 'label:color:dir0,...' — got: {s!r}")
    color, sep2, dirs_str = rest.partition(":")
    if not sep2:
        sys.exit(f"ERROR: --configs value must be 'label:color:dir0,...' — got: {s!r}")
    dirs = [Path(d.strip()) for d in dirs_str.split(",")]
    return label.strip(), color.strip(), dirs


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--configs", nargs="+", required=True, metavar="SPEC",
                    help='"label:scope_color:dir_suite0,dir_suite1,..." — one per column')
    ap.add_argument("--suite-labels", nargs="+", default=None, metavar="LABEL")
    ap.add_argument("--max-n", type=int, default=10, dest="max_n")
    ap.add_argument("--out", default="results/plots/optimal_threshold/optimal_speedup.png")
    args = ap.parse_args()

    parsed = [_parse_config_arg(s) for s in args.configs]
    n_suites = len(parsed[0][2])
    suite_labels = args.suite_labels or [f"Suite {i}" for i in range(n_suites)]
    if len(suite_labels) != n_suites:
        sys.exit("ERROR: --suite-labels count must match the number of dirs per config")
    for lbl, color, dirs in parsed:
        if len(dirs) != n_suites:
            sys.exit(f"ERROR: config '{lbl}' has {len(dirs)} dirs, expected {n_suites}")

    # Load data: data[cfg_idx][suite_idx] = {wl: (speedup_%, opt_n)}
    data: "list[list[dict]]" = []
    for lbl, color, dirs in parsed:
        suite_data = []
        for si, d in enumerate(dirs):
            if not d.is_dir():
                sys.exit(f"ERROR: not a directory: {d}")
            print(f"Loading [{lbl}] {suite_labels[si]} from {d.name} …")
            wl_data = _load_optimal_data(d, args.max_n)
            if not wl_data:
                sys.exit(f"ERROR: no usable data in {d}")
            print(f"  {len(wl_data)} traces")
            suite_data.append(wl_data)
        data.append(suite_data)

    n_panels = len(parsed)
    xs = np.arange(n_suites)
    rng = np.random.default_rng(0)

    # ── Figure: 2 rows × n_panels cols, strip on top, N-dist tile below ───────
    fig, axes = plt.subplots(
        2, n_panels,
        figsize=(4.5 * n_panels, 8),
        gridspec_kw={"height_ratios": [3, 1.6]},
    )
    # axes[row, col]

    for ci, (cfg_label, scope_color, _dirs) in enumerate(parsed):
        ax_strip = axes[0, ci]
        ax_dist  = axes[1, ci]
        suite_data = data[ci]

        # ── Top: strip chart ─────────────────────────────────────────────────
        for xi, (slbl, color, wl_data) in enumerate(
                zip(suite_labels, SUITE_COLORS, suite_data)):
            vals = np.array([v for v, _ in wl_data.values()])
            jitter = rng.uniform(-0.18, 0.18, size=len(vals))
            ax_strip.scatter(xi + jitter, vals, s=18, color=color,
                             edgecolors="none", alpha=0.55, zorder=2)
            gm = _weighted_geomean_pct({wl: v for wl, (v, _) in wl_data.items()})
            ax_strip.plot(xi, gm, marker="D", markersize=9, color=color,
                          markeredgecolor="black", markeredgewidth=0.8, zorder=4,
                          label=f"{slbl}  ({gm:+.2f}%)")

        ax_strip.axhline(0, color="black", linewidth=0.8, linestyle="--", zorder=1)
        ax_strip.set_xticks(xs)
        ax_strip.set_xticklabels(suite_labels, fontsize=11)
        ax_strip.set_xlim(-0.5, n_suites - 0.5)
        ax_strip.set_ylabel("IPC speedup vs LRU at optimal N (%)", fontsize=10)
        ax_strip.set_title(cfg_label, fontsize=11, fontweight="bold")
        ax_strip.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
        ax_strip.legend(fontsize=8.5, framealpha=0.85, loc="upper right")
        ax_strip.yaxis.grid(True, linestyle="--", color="gray",
                            alpha=0.3, linewidth=0.5, zorder=0)
        ax_strip.set_axisbelow(True)

        # ── Bottom: optimal-N distribution line plot ──────────────────────────
        # One line per suite: x = N, y = % of traces that chose that N as optimal
        ns_range = np.arange(1, args.max_n + 1)
        for si, (slbl, color, wl_data) in enumerate(
                zip(suite_labels, SUITE_COLORS, suite_data)):
            opt_ns = [opt_n for _, opt_n in wl_data.values()]
            total  = max(len(opt_ns), 1)
            fracs  = np.array([100.0 * opt_ns.count(n) / total
                               for n in ns_range])
            ax_dist.plot(ns_range, fracs, color=color, linewidth=1.8,
                         marker="o", markersize=5, zorder=3, label=slbl)

        ax_dist.set_xticks(ns_range)
        ax_dist.set_xlim(0.5, args.max_n + 0.5)
        ax_dist.set_ylim(bottom=0)
        ax_dist.set_xlabel("Optimal $N$", fontsize=9)
        ax_dist.set_ylabel("Traces (%)", fontsize=9)
        ax_dist.set_title("Optimal $N$ distribution", fontsize=9)
        ax_dist.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
        ax_dist.yaxis.grid(True, linestyle="--", color="gray",
                           alpha=0.3, linewidth=0.5, zorder=0)
        ax_dist.set_axisbelow(True)
        ax_dist.legend(fontsize=7.5, framealpha=0.85, loc="upper right")

    fig.suptitle(
        "IPC speedup vs LRU at the per-trace oracle threshold $N$\n"
        "(dots = individual traces · diamond = benchmark-weighted geomean)",
        fontsize=11, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0.05, 1, 1])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=200, bbox_inches="tight")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
