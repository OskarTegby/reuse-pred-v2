#!/usr/bin/env python3
"""Generate combined LLC+STLB comparison figure.

Shows four policy configurations for DPC3, Google, QMM (the only suites with
full combined data): LLC-only, STLB-only, LLC+STLB SRRIP-Live, LLC+STLB IPV-Live.
Each bar is at its respective optimal/tested threshold.

Data sources:
  LLC-only:    results/{suite}_srrip_live_thd_pc_*/srrip_live_thd{N}/
  STLB-only:   results/{suite}_stlb_thd_pc_*/stlb_srrip_live_thd{N}/
  Both-SRRIP:  results/cluster/{suite}_srrip_live_both_thd_*/srrip_live_both_thd{N}/
  Both-IPV:    results/cluster/{suite}_ipv_live_both_thd_*/ipv_live_both_thd{N}/
  LRU baseline: results/{suite}_repl_pol_20260522_0722/lru_baseline/
"""

import sys
from pathlib import Path
from statistics import geometric_mean

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


SUITES = ["dpc3", "google", "qmm"]
SUITE_LABELS = {"dpc3": "DPC3 (SPEC)", "google": "Google", "qmm": "QMM"}

base    = None   # set in main()
cluster = None


def extract_ipc(path):
    try:
        with open(path) as f:
            ipc = None
            for line in f:
                if "cumulative IPC:" in line:
                    parts = line.split()
                    for i, p in enumerate(parts):
                        if "IPC:" in p and i + 1 < len(parts):
                            ipc = float(parts[i + 1])
            return ipc
    except Exception:
        return None


def load_ipcs(d):
    ipcs = {}
    d = Path(d)
    if not d.exists():
        return ipcs
    for tr in d.iterdir():
        if tr.is_dir():
            ipc = extract_ipc(tr / "champsim.out")
            if ipc:
                ipcs[tr.name] = ipc
    return ipcs


def geomean_speedup(policy_dir, lru_ipcs):
    pol_ipcs = load_ipcs(policy_dir)
    common = set(lru_ipcs) & set(pol_ipcs)
    if not common:
        return None
    ratios = [pol_ipcs[t] / lru_ipcs[t] for t in common]
    return (geometric_mean(ratios) - 1.0) * 100.0


def main():
    global base, cluster
    repo_root = Path(__file__).resolve().parent.parent.parent
    base    = repo_root / "results"
    cluster = base / "cluster"

    # Policy directories at their respective tested thresholds
    policy_dirs = {
        "dpc3": {
            "LLC-only\n(thd=8)":         base / "dpc3_srrip_live_thd_pc_20260513_0055/srrip_live_thd8",
            "STLB-only\n(thd=16)":       base / "dpc3_stlb_thd_pc_20260514_0025/stlb_srrip_live_thd16",
            "LLC+STLB\nSRRIP (thd=16)":  cluster / "dpc3_srrip_live_both_thd_addr_20260514_2018/srrip_live_both_thd16",
            "LLC+STLB\nIPV (thd=16)":    cluster / "dpc3_ipv_live_both_thd_addr_20260517_2217/ipv_live_both_thd16",
        },
        "google": {
            "LLC-only\n(thd=8)":         base / "google_srrip_live_thd_pc_20260513_0056/srrip_live_thd8",
            "STLB-only\n(thd=16)":       base / "google_stlb_thd_pc_20260514_0025/stlb_srrip_live_thd16",
            "LLC+STLB\nSRRIP (thd=8)":   cluster / "google_srrip_live_both_thd_pc_20260514_2018/srrip_live_both_thd8",
            "LLC+STLB\nIPV (thd=8)":     cluster / "google_ipv_live_both_thd_pc_20260517_2218/ipv_live_both_thd8",
        },
        "qmm": {
            "LLC-only\n(thd=4)":         base / "qmm_srrip_live_thd_pc_20260513_0056/srrip_live_thd4",
            "STLB-only\n(thd=1)":        base / "qmm_stlb_thd_pc_20260514_0025/stlb_srrip_live_thd1",
            "LLC+STLB\nSRRIP (thd=4)":   cluster / "qmm_srrip_live_both_thd_pc_20260514_2018/srrip_live_both_thd4",
            "LLC+STLB\nIPV (thd=2)":     cluster / "qmm_ipv_live_both_thd_pc_20260517_2218/ipv_live_both_thd2",
        },
    }

    # Colors per policy type
    colors = ["#2ca02c", "#d62728", "#1f77b4", "#ff7f0e"]

    # Collect all speedup values for shared y-axis
    all_vals = []
    suite_speedups = {}
    for suite in SUITES:
        lru_ipcs = load_ipcs(base / f"{suite}_repl_pol_20260522_0722/lru_baseline")
        speedups = []
        for pol_dir in policy_dirs[suite].values():
            s = geomean_speedup(pol_dir, lru_ipcs)
            speedups.append(s if s is not None else 0.0)
            if s is not None:
                all_vals.append(s)
        suite_speedups[suite] = speedups

    pad = 0.8
    y_min = min(all_vals) - pad
    y_max = max(all_vals) + pad

    fig, axes = plt.subplots(1, 3, figsize=(14, 5), sharey=True)

    for ax, suite in zip(axes, SUITES):
        lru_ipcs  = load_ipcs(base / f"{suite}_repl_pol_20260522_0722/lru_baseline")
        pol_names = list(policy_dirs[suite].keys())
        speedups  = suite_speedups[suite]
        n = len(lru_ipcs)

        x = np.arange(len(pol_names))
        bars = ax.bar(x, speedups, width=0.6, color=colors, alpha=0.85, edgecolor="white")

        for bar, spd in zip(bars, speedups):
            va = "bottom" if spd >= 0 else "top"
            offset = (y_max - y_min) * 0.02 * (1 if spd >= 0 else -1)
            ax.text(bar.get_x() + bar.get_width() / 2, spd + offset,
                    f"{spd:.1f}%", ha="center", va=va, fontsize=8)

        ax.axhline(y=0, color="black", linewidth=0.8)
        ax.set_ylim(y_min, y_max)
        ax.set_title(SUITE_LABELS[suite], fontweight="bold", fontsize=12)
        ax.set_xticks(x)
        ax.set_xticklabels(pol_names, fontsize=8)
        ax.tick_params(labelsize=9)
        ax.grid(axis="y", alpha=0.3, linestyle="--", linewidth=0.5)
        ax.text(0.98, 0.97, f"n={n}", ha="right", va="top",
                transform=ax.transAxes, fontsize=8, color="gray")

        print(f"{suite}: " + "  ".join(f"{p.split(chr(10))[0]}={s:+.2f}%"
                                        for p, s in zip(pol_names, speedups)))

    axes[0].set_ylabel("Speedup vs LRU (%)", fontsize=10)

    fig.suptitle(
        "LLC-Only vs STLB-Only vs LLC+STLB: Geomean Speedup vs LRU",
        fontsize=13, fontweight="bold", y=1.02,
    )
    plt.tight_layout()

    output = base / "plots" / "combined_llc_stlb_comparison.png"
    plt.savefig(output, dpi=150, bbox_inches="tight")
    print(f"\nSaved: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
