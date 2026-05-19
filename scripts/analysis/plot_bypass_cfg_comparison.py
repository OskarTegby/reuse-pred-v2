#!/usr/bin/env python3
"""plot_bypass_cfg_comparison.py — dpPred / cbPred speedup across cache configurations.

Produces a grouped bar chart: for each suite (SPEC, Google, Qualcomm), shows
geomean IPC speedup over LRU baseline for:
  - dpPred only     (2 MB LLC, current config)
  - dpPred + cbPred (2 MB LLC, current config)
  - dpPred only     (1 MB LLC)
  - dpPred + cbPred (1 MB LLC)

Usage:
    python3 scripts/analysis/plot_bypass_cfg_comparison.py \
        --2mb-dirs   results/cluster/dpc3_pol_20260511_1545 \
                     results/cluster/google_pol_20260511_1545 \
                     results/cluster/qmm_pol_20260511_1545 \
        --1mb-dirs   results/cluster/dpc3_llc_half_20260516_2327 \
                     results/cluster/google_llc_half_20260516_2330 \
                     results/cluster/qmm_llc_half_20260516_2330 \
        --labels     "SPEC (DPC3)" Google Qualcomm \
        --out        results/plots/bypass_cfg_comparison.png
"""

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from champsim_utils import geomean_speedup


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--2mb-dirs", dest="dirs_2mb", nargs="+", required=True)
    ap.add_argument("--1mb-dirs", dest="dirs_1mb", nargs="+", required=True)
    ap.add_argument("--labels",   nargs="+", required=True)
    ap.add_argument("--out",      default="results/plots/bypass_cfg_comparison.png")
    args = ap.parse_args()

    assert len(args.dirs_2mb) == len(args.dirs_1mb) == len(args.labels)
    n = len(args.labels)

    dp_2mb   = []
    both_2mb = []
    dp_1mb   = []
    both_1mb = []

    for d2, d1 in zip(args.dirs_2mb, args.dirs_1mb):
        dp_2mb.append(  geomean_speedup(f"{d2}/lru_dp_only", f"{d2}/lru"))
        both_2mb.append(geomean_speedup(f"{d2}/lru_pred",    f"{d2}/lru"))
        dp_1mb.append(  geomean_speedup(f"{d1}/lru_dp_only", f"{d1}/lru"))
        both_1mb.append(geomean_speedup(f"{d1}/lru_pred",    f"{d1}/lru"))

    x     = np.arange(n)
    width = 0.18
    gap   = 0.04   # extra space between the 2MB and 1MB groups

    offsets = np.array([-1.5 - gap/2, -0.5 - gap/2, 0.5 + gap/2, 1.5 + gap/2]) * width

    C1 = "#9ecae1"   # 2MB dpPred only   (light blue)
    C2 = "#2166ac"   # 2MB dpPred+cbPred (dark blue)
    C3 = "#fdae6b"   # 1MB dpPred only   (light orange)
    C4 = "#d6604d"   # 1MB dpPred+cbPred (dark orange)

    fig, ax = plt.subplots(figsize=(9, 4.5))

    bars = [
        ax.bar(x + offsets[0], dp_2mb,   width, label="dpPred only (LLC 2 MB)",   color=C1, edgecolor="white", linewidth=0.5),
        ax.bar(x + offsets[1], both_2mb, width, label="dpPred+cbPred (LLC 2 MB)", color=C2, edgecolor="white", linewidth=0.5),
        ax.bar(x + offsets[2], dp_1mb,   width, label="dpPred only (LLC 1 MB)",   color=C3, edgecolor="white", linewidth=0.5),
        ax.bar(x + offsets[3], both_1mb, width, label="dpPred+cbPred (LLC 1 MB)", color=C4, edgecolor="white", linewidth=0.5),
    ]

    for bar_group in bars:
        for bar in bar_group:
            h = bar.get_height()
            va = "bottom" if h >= 0 else "top"
            ax.text(bar.get_x() + bar.get_width() / 2, h,
                    f"{h:+.2f}%", ha="center", va=va, fontsize=7, rotation=90,
                    color="black")

    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(args.labels, fontsize=11)
    ax.set_ylabel("Geomean IPC speedup vs LRU baseline (%)", fontsize=10)
    ax.set_title("Bypass predictor benefit: 2 MB vs 1 MB LLC", fontsize=12)
    ax.legend(fontsize=8.5, framealpha=0.85, ncol=2)
    ax.grid(axis="y", alpha=0.3, linewidth=0.5)
    ax.set_xlim(-0.6, n - 0.4)

    fig.tight_layout()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=150)
    plt.close(fig)
    print(f"  Written: {args.out}")


if __name__ == "__main__":
    main()
