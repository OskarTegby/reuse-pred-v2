#!/usr/bin/env python3
"""Generate combined LLC threshold sensitivity plot for Figure 1.

Shows SRRIP-Live and IPV-Live geomean speedup vs LRU across DoA thresholds
{1,2,4,8,16} for all 7 benchmark suites. Grouped bars per threshold.
Layout: 2 rows x 4 cols (last cell hidden). Shared y-axis.

Data sources:
  SRRIP-Live: results/{suite}_srrip_live_thd_pc_*/srrip_live_thd{N}/
  IPV-Live:   results/{suite}_ipv_live_thd_pc_*/ipv_live_thd{N}/
              results/cluster/{suite}_ipv_live_thd_*/ipv_live_thd{N}/  (dpc3/qmm/google)
  LRU:        results/{suite}_repl_pol_20260522_0722/lru_baseline/
"""

import sys
from pathlib import Path
from statistics import geometric_mean

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np


SUITES = ["dpc3", "qmm", "google", "gap", "gms", "ligra", "ml"]

SUITE_LABELS = {
    "dpc3":   "DPC3 (SPEC)",
    "qmm":    "QMM",
    "google": "Google",
    "gap":    "GAP",
    "gms":    "GMS",
    "ligra":  "Ligra",
    "ml":     "ML",
}

SRRIP_DIRS = {
    "dpc3":   "dpc3_srrip_live_thd_pc_20260513_0055",
    "qmm":    "qmm_srrip_live_thd_pc_20260513_0056",
    "google": "google_srrip_live_thd_pc_20260513_0056",
    "gap":    "gap_srrip_live_thd_pc_20260520_0059",
    "gms":    "gms_srrip_live_thd_pc_20260520_0128",
    "ligra":  "ligra_srrip_live_thd_pc_20260520_0059",
    "ml":     "ml_srrip_live_thd_pc_20260520_0059",
}

# dpc3/qmm/google IPV-Live data lives under results/cluster/
IPV_DIRS = {
    "dpc3":   ("cluster", "dpc3_ipv_live_thd_addr_20260514_1432"),
    "qmm":    ("cluster", "qmm_ipv_live_thd_pc_20260514_1432"),
    "google": ("cluster", "google_ipv_live_thd_pc_20260514_1432"),
    "gap":    ("results", "gap_ipv_live_thd_pc_20260520_0819"),
    "gms":    ("results", "gms_ipv_live_thd_pc_20260520_0819"),
    "ligra":  ("results", "ligra_ipv_live_thd_pc_20260520_0819"),
    "ml":     ("results", "ml_ipv_live_thd_pc_20260520_0819"),
}

LRU_SUBDIRS = {s: f"{s}_repl_pol_20260522_0722/lru_baseline" for s in SUITES}

COLOR_SRRIP = "#2ca02c"
COLOR_IPV   = "#9467bd"
COLOR_SRRIP_BEST = "#1a7a1a"
COLOR_IPV_BEST   = "#5a2d8a"


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
    for tr in sorted(d.iterdir()):
        if tr.is_dir():
            ipc = extract_ipc(tr / "champsim.out")
            if ipc:
                ipcs[tr.name] = ipc
    return ipcs


def speedups_for_policy(base_dir, subdir_prefix, thresholds, lru_ipcs):
    vals = []
    for thd in thresholds:
        pol_ipcs = load_ipcs(base_dir / f"{subdir_prefix}{thd}")
        common = set(lru_ipcs) & set(pol_ipcs)
        spd = (geometric_mean([pol_ipcs[t] / lru_ipcs[t] for t in common]) - 1.0) * 100.0 \
              if common else 0.0
        vals.append(spd)
    return vals


def main():
    repo_root = Path(__file__).resolve().parent.parent.parent
    results_dir = repo_root / "results"
    cluster_dir = results_dir / "cluster"
    plots_dir   = results_dir / "plots"

    thresholds = [1, 2, 4, 8, 16]

    # ── Pass 1: collect all data ──────────────────────────────────────────────
    suite_data = {}
    for suite in SUITES:
        lru_ipcs = load_ipcs(results_dir / LRU_SUBDIRS[suite])
        if not lru_ipcs:
            continue

        srrip_spds = speedups_for_policy(
            results_dir / SRRIP_DIRS[suite], "srrip_live_thd", thresholds, lru_ipcs)

        loc, dirname = IPV_DIRS[suite]
        ipv_base = (cluster_dir if loc == "cluster" else results_dir) / dirname
        ipv_spds = speedups_for_policy(ipv_base, "ipv_live_thd", thresholds, lru_ipcs)

        suite_data[suite] = {
            "srrip": srrip_spds, "ipv": ipv_spds, "n": len(lru_ipcs)
        }

    # ── Shared y-axis ─────────────────────────────────────────────────────────
    all_vals = [v for d in suite_data.values() for v in d["srrip"] + d["ipv"]]
    pad = 1.5
    y_min = min(all_vals) - pad
    y_max = max(all_vals) + pad

    # ── Pass 2: plot ──────────────────────────────────────────────────────────
    fig, axes = plt.subplots(2, 4, figsize=(5.5, 7.5))
    axes = axes.flatten()
    width = 0.12
    gap   = 0.04   # inner gap between the two bars in each pair
    x = np.arange(len(thresholds))

    legend_handles = []
    for idx, suite in enumerate(SUITES):
        ax = axes[idx]

        if suite not in suite_data:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                    transform=ax.transAxes, fontsize=9)
            ax.set_title(SUITE_LABELS[suite], fontweight="bold", fontsize=11)
            continue

        srrip = suite_data[suite]["srrip"]
        ipv   = suite_data[suite]["ipv"]
        n     = suite_data[suite]["n"]

        best_s = int(np.argmax(srrip))
        best_i = int(np.argmax(ipv))

        sc = [COLOR_SRRIP_BEST if i == best_s else COLOR_SRRIP for i in range(len(thresholds))]
        ic = [COLOR_IPV_BEST   if i == best_i else COLOR_IPV   for i in range(len(thresholds))]

        b_s = ax.bar(x - width/2 - gap/2, srrip, width, color=sc, alpha=0.85,
                     edgecolor="white", label="SRRIP-Live")
        b_i = ax.bar(x + width/2 + gap/2, ipv,   width, color=ic, alpha=0.85,
                     edgecolor="white", label="IPV-Live")

        if idx == 0:
            legend_handles = [b_s[0], b_i[0]]

        ax.axhline(y=0, color="black", linewidth=1.2)
        ax.set_ylim(y_min, y_max)
        ax.set_title(SUITE_LABELS[suite], fontweight="bold", fontsize=11)
        ax.set_xlabel("Threshold $\\theta$", fontsize=9)
        ax.set_xticks(x)
        ax.set_xticklabels(thresholds, fontsize=9)
        ax.tick_params(labelsize=9)
        ax.yaxis.set_minor_locator(matplotlib.ticker.MultipleLocator(2))
        ax.grid(axis="y", which="major", alpha=0.6, linestyle="-", linewidth=1.0, color="lightgray", zorder=0)
        ax.grid(axis="y", which="minor", alpha=0.35, linestyle="-", linewidth=0.5, color="lightgray", zorder=0)

        if idx % 4 == 0:
            ax.set_ylabel("Speedup vs LRU (%)", fontsize=9)
        else:
            ax.set_yticklabels([])

        ax.text(0.98, 0.97, f"n={n}", ha="right", va="top",
                transform=ax.transAxes, fontsize=8, color="gray")

        print(f"  {suite}: SRRIP best thd={thresholds[best_s]} {srrip[best_s]:+.2f}%  "
              f"IPV best thd={thresholds[best_i]} {ipv[best_i]:+.2f}%")

    axes[7].set_visible(False)

    fig.legend(handles=legend_handles, labels=["SRRIP-Live", "IPV-Live"],
               loc="lower right", bbox_to_anchor=(0.98, 0.05),
               fontsize=10, framealpha=0.9)
    plt.tight_layout(w_pad=0.0)

    output = plots_dir / "llc_threshold_combined.png"
    plt.savefig(output, dpi=150, bbox_inches="tight")
    print(f"\nSaved: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
