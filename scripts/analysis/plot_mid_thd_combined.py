#!/usr/bin/env python3
"""plot_mid_thd_combined.py — IPC speedup vs mid_thd, old vs new data.

Three panels (one per suite), each showing 2 bars per threshold:
  addr, STLB+LLC  — mid_lru_study runs (Apr1, STLB erroneously varied)
  addr, LLC-only  — llc_repl_pol_study runs (Apr9, STLB locked to LRU)

Output: results/plots/mid_lru_llc_only/mid_thd_comparison.png
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

from spec_weights import benchmark_weighted_geomean_pct
from champsim_utils import parse_ipc, load_baseline

BASE = Path("results")

CONFIGS = [
    ("addr, STLB+LLC (old)", "#1A4A7A", "s", "--"),   # dark blue
    ("addr, LLC-only (new)", "#E09B6A", "^", "-"),    # orange
]

SUITES = [
    {
        "label": "SPEC (DPC3)",
        "dirs": [
            BASE / "mid_lru_study/dpc3_mid_addr_20260401_2359",
            BASE / "llc_repl_pol_study/dpc3_mid_addr_20260409_0218",
        ],
    },
    {
        "label": "Google",
        "dirs": [
            BASE / "mid_lru_study/google_mid_addr_20260402_0000",
            BASE / "llc_repl_pol_study/google_mid_addr_20260409_0218",
        ],
    },
    {
        "label": "Qualcomm",
        "dirs": [
            BASE / "mid_lru_study/qmm_mid_addr_20260401_1625",
            BASE / "llc_repl_pol_study/qmm_mid_addr_20260409_0218",
        ],
    },
]

MAX_N = 5


def geomean_speedup(sweep_dir: Path, n: int):
    """Return benchmark-weighted geomean IPC speedup (%) at mid_thd=n.

    For SPEC traces (matched by simpoint weights): weighted geometric mean
    within each benchmark (re-normalised for missing simpoints), then
    equal-weight geomean across benchmarks.
    For all other traces: flat equal-weight geomean.
    """
    baselines = load_baseline(sweep_dir / "lru")
    if not baselines:
        return None

    thd_dir = sweep_dir / f"mid_thd{n}"
    if not thd_dir.is_dir():
        return None

    # Collect per-trace speedup ratios (not %)
    ratios: dict = {}
    for wl, b in baselines.items():
        v = parse_ipc(thd_dir / wl / "champsim.out")
        if v is not None and b > 0:
            ratios[wl] = v / b

    if not ratios:
        return None

    return benchmark_weighted_geomean_pct(ratios)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/plots/mid_lru_llc_only/mid_thd_comparison.png")
    args = ap.parse_args()

    ns = list(range(1, MAX_N + 1))
    n_cfgs = len(CONFIGS)
    bar_w  = 0.18
    group_w = n_cfgs * bar_w   # no extra gap — N values are the visual separator

    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=False)

    # Build a colour ramp from light to dark for N=1..5 within each config's hue
    def shade(hex_color, n, n_max):
        """Lighten for small n, keep full colour at n_max."""
        import matplotlib.colors as mc
        rgb = np.array(mc.to_rgb(hex_color))
        t = (n - 1) / max(n_max - 1, 1)   # 0 (lightest) → 1 (darkest)
        white = np.ones(3)
        return tuple(white * (1 - t) * 0.55 + rgb * (1 - (1 - t) * 0.55))

    group_gap = 0.35   # extra space between config groups

    from matplotlib.ticker import FixedLocator, FixedFormatter

    for ax, suite in zip(axes, SUITES):
        all_vals = []
        major_pos, major_lbl = [], []   # group centres → config names
        minor_pos, minor_lbl = [], []   # bar centres   → N values

        for ci, ((lbl, color, _marker, _ls), sweep_dir) in enumerate(
                zip(CONFIGS, suite["dirs"])):
            g_start = ci * (MAX_N * bar_w + group_gap)

            for ni, n in enumerate(ns):
                x = g_start + ni * bar_w
                minor_pos.append(x)
                minor_lbl.append(str(n))
                gm = geomean_speedup(sweep_dir, n)
                if gm is None:
                    print(f"  WARNING: no data — {suite['label']} / {lbl} / mid_thd{n}",
                          file=sys.stderr)
                    continue
                c = shade(color, n, MAX_N)
                ax.bar(x, gm, bar_w * 0.88, color=c, edgecolor="black",
                       linewidth=0.4, zorder=3)
                all_vals.append(gm)

            # Group centre label
            major_pos.append(g_start + (MAX_N - 1) * bar_w / 2)
            major_lbl.append(lbl)

        ax.axhline(0, color="black", linewidth=0.8, linestyle="--", zorder=1)

        # Minor ticks: N=1..5 under each bar — no major ticks (they would
        # suppress the middle minor label at the coinciding position)
        ax.xaxis.set_minor_locator(FixedLocator(minor_pos))
        ax.xaxis.set_minor_formatter(FixedFormatter(minor_lbl))
        ax.tick_params(axis="x", which="minor", length=3, width=0.6,
                       labelsize=6.5, pad=2)
        ax.xaxis.set_major_locator(FixedLocator([]))
        ax.tick_params(axis="x", which="major", length=0)

        # Config group labels as text below the N labels, in axes-x / data-y
        import matplotlib.transforms as mtrans
        blend = mtrans.blended_transform_factory(ax.transData, ax.transAxes)
        for cx, lbl in zip(major_pos, major_lbl):
            ax.text(cx, -0.30, lbl, transform=blend,
                    ha="center", va="top", fontsize=8.5)

        ax.set_xlabel("N  (mid-insertion threshold)", fontsize=9, labelpad=10)
        ax.set_ylabel("IPC speedup vs LRU (geomean, %)", fontsize=9)
        ax.set_title(suite["label"], fontsize=12, fontweight="bold")
        ax.yaxis.grid(True, linestyle="--", color="gray", alpha=0.60,
                      linewidth=0.9, zorder=0)
        ax.set_axisbelow(True)

        if all_vals:
            lo, hi = min(all_vals), max(all_vals)
            span = max(hi - lo, 0.3)
            ax.set_ylim(lo - 0.18 * span, hi + 0.22 * span)

        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f%%"))

    # Legend: N=1..5 shading using the first config's colour as reference
    import matplotlib.patches as mpatches
    ref_color = CONFIGS[0][1]
    n_patches = [mpatches.Patch(facecolor=shade(ref_color, n, MAX_N),
                                edgecolor="black", linewidth=0.4,
                                label=f"N={n}") for n in ns]
    fig.legend(handles=n_patches,
               loc="lower center", ncol=MAX_N, fontsize=10,
               framealpha=0.9, bbox_to_anchor=(0.5, -0.04))

    fig.suptitle(
        "IPC speedup vs LRU as a function of mid_thd\n"
        "addr-keyed: STLB+LLC (old, Apr1) vs LLC-only (new, Apr9)",
        fontsize=11, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0.12, 1, 1])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
