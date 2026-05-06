#!/usr/bin/env python3
"""plot_mid_thd_sweep.py — IPC speedup vs threshold N for all four design choices.

Three panels stacked vertically (one per suite), each showing four config groups:
  addr, no-promote | addr, promote | PC, no-promote | PC, promote
Within each group, bars are shaded light→dark for N=1..5.

Output: results/plots/mid_lru/mid_thd.png
"""

import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.transforms as mtrans
import numpy as np
from matplotlib.ticker import FixedFormatter, FixedLocator

from spec_weights import benchmark_weighted_geomean_pct
from champsim_utils import parse_ipc


def _geomean_speedup(sweep_dir: Path, n: int):
    lru_dir = sweep_dir / "lru"
    baselines: dict = {}
    for f in sorted(lru_dir.glob("*/champsim.out")):
        v = parse_ipc(f)
        if v is not None:
            baselines[f.parent.name] = v
    if not baselines:
        return None
    thd_dir = sweep_dir / f"mid_thd{n}"
    if not thd_dir.is_dir():
        return None
    ratios: dict = {}
    for wl, b in baselines.items():
        v = parse_ipc(thd_dir / wl / "champsim.out")
        if v is not None and b > 0:
            ratios[wl] = v / b
    if not ratios:
        return None
    result = benchmark_weighted_geomean_pct(ratios)
    import math
    return None if math.isnan(result) else result


def shade(hex_color, n, n_max):
    import matplotlib.colors as mc
    rgb = np.array(mc.to_rgb(hex_color))
    t = (n - 1) / max(n_max - 1, 1)
    white = np.ones(3)
    return tuple(white * (1 - t) * 0.55 + rgb * (1 - (1 - t) * 0.55))


BASE = Path("results")

CONFIGS = [
    ("addr\nno-promote", "#5B7FA6", "s", "--"),
    ("addr\npromote",    "#1A4A7A", "^", "-"),
    ("PC\nno-promote",   "#E09B6A", "o", "--"),
    ("PC\npromote",      "#B03000", "D", "-"),
]

SUITES = [
    {
        "label": "SPEC (DPC3)",
        "dirs": [
            BASE / "lru_mid_new/dpc3_mid_addr_20260406_1251",
            BASE / "mid_lru_study/dpc3_mid_addr_20260401_2359",
            BASE / "lru_mid_new/dpc3_mid_pc_20260406_1251",
            BASE / "mid_lru_study/dpc3_mid_pc_20260401_2359",
        ],
    },
    {
        "label": "Google",
        "dirs": [
            BASE / "lru_mid_new/google_mid_addr_20260406_1251",
            BASE / "mid_lru_study/google_mid_addr_20260402_0000",
            BASE / "lru_mid_new/google_mid_pc_20260406_1251",
            BASE / "mid_lru_study/google_mid_pc_promote_20260407_1031",
        ],
    },
    {
        "label": "Qualcomm",
        "dirs": [
            BASE / "lru_mid_new/qmm_mid_addr_20260406_1251",
            BASE / "mid_lru_study/qmm_mid_addr_20260401_1625",
            BASE / "lru_mid_new/qmm_mid_pc_20260406_1251",
            BASE / "mid_lru_study/qmm_mid_pc_20260401_1625",
        ],
    },
]

MAX_N = 5


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="results/plots/mid_lru/mid_thd.png")
    ap.add_argument("--max-n", type=int, default=MAX_N, dest="max_n")
    args = ap.parse_args()

    ns = list(range(1, args.max_n + 1))
    bar_w     = 0.20
    group_gap = 0.50

    fig, axes = plt.subplots(len(SUITES), 1, figsize=(9, 3.3 * len(SUITES)), sharey=False)

    for ax, suite in zip(axes, SUITES):
        all_vals = []
        major_pos, major_lbl = [], []
        minor_pos, minor_lbl = [], []

        for ci, ((lbl, color, _marker, _ls), sweep_dir) in enumerate(
                zip(CONFIGS, suite["dirs"])):
            g_start = ci * (args.max_n * bar_w + group_gap)

            for ni, n in enumerate(ns):
                x = g_start + ni * bar_w
                minor_pos.append(x)
                minor_lbl.append(str(n))
                gm = _geomean_speedup(sweep_dir, n)
                if gm is None:
                    print(f"  WARNING: no data — {suite['label']} / {lbl} / mid_thd{n}",
                          file=sys.stderr)
                    continue
                c = shade(color, n, args.max_n)
                ax.bar(x, gm, bar_w * 0.88, color=c, edgecolor="black",
                       linewidth=0.4, zorder=3)
                all_vals.append(gm)

            major_pos.append(g_start + (args.max_n - 1) * bar_w / 2)
            major_lbl.append(lbl)

        ax.axhline(0, color="black", linewidth=0.8, linestyle="--", zorder=1)

        ax.xaxis.set_minor_locator(FixedLocator(minor_pos))
        ax.xaxis.set_minor_formatter(FixedFormatter(minor_lbl))
        ax.tick_params(axis="x", which="minor", length=3, width=0.6,
                       labelsize=8.5, pad=2)
        ax.xaxis.set_major_locator(FixedLocator([]))
        ax.tick_params(axis="x", which="major", length=0)

        blend = mtrans.blended_transform_factory(ax.transData, ax.transAxes)
        for cx, lbl in zip(major_pos, major_lbl):
            ax.text(cx, -0.18, lbl, transform=blend,
                    ha="center", va="top", fontsize=10)

        ax.set_xlabel("N  (mid-insertion threshold)", fontsize=10, labelpad=36)
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

    ref_color = CONFIGS[0][1]
    n_patches = [mpatches.Patch(facecolor=shade(ref_color, n, args.max_n),
                                edgecolor="black", linewidth=0.4,
                                label=f"N={n}") for n in ns]
    fig.legend(handles=n_patches,
               loc="lower center", ncol=args.max_n, fontsize=10,
               framealpha=0.9, bbox_to_anchor=(0.5, 0.0))

    fig.suptitle(
        r"IPC speedup vs.\ LRU as a function of threshold $N$" + "\n"
        r"(addr vs.\ PC key, promote vs.\ no-promote)",
        fontsize=11, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0.05, 1, 1])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
