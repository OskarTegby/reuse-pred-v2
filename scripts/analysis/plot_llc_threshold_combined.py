#!/usr/bin/env python3
"""Generate combined LLC threshold sensitivity plot for Figure 1.

Shows SRRIP-Live and IPV-Live geomean speedup vs LRU across DoA thresholds
{1,2,4,8,16} for all 7 benchmark suites. Grouped bars per threshold.
Layout: 2 rows x 4 cols (last cell hidden). Shared y-axis.

Data sources (6 suites): June 2026 rebaseline dirs
  LRU:        results/{suite}_thd_rebaseline_20260605_2316/lru/
  SRRIP-Live: results/{suite}_thd_rebaseline_20260605_2316/srrip_live_llc/thd{N}/
  IPV-Live:   results/{suite}_thd_rebaseline_20260605_2316/ipv_live_llc/thd{N}/
  (qmm uses qmm_thd_rebaseline_20260604_2307)

Google (no rebaseline):
  LRU:        results/google_repl_pol_20260522_0722/lru_baseline/
  SRRIP-Live: results/google_srrip_live_thd_pc_20260513_0056/srrip_live_thd{N}/
  IPV-Live:   results/cluster/google_ipv_live_thd_pc_20260514_1432/ipv_live_thd{N}/
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

# June 2026 rebaseline directories (Config C, vs LRU)
REBASE_DIRS = {
    "dpc3":  "dpc3_thd_rebaseline_20260605_2316",
    "gap":   "gap_thd_rebaseline_20260605_2316",
    "gms":   "gms_thd_rebaseline_20260605_2316",
    "ligra": "ligra_thd_rebaseline_20260605_2316",
    "ml":    "ml_thd_rebaseline_20260605_2316",
    "qmm":   "qmm_thd_rebaseline_20260604_2307",
}

# Google has no rebaseline — use original sweep directories
GOOGLE_LRU_DIR   = "google_repl_pol_20260522_0722/lru_baseline"
GOOGLE_SRRIP_DIR = "google_srrip_live_thd_pc_20260513_0056"
GOOGLE_IPV_DIR   = "cluster/google_ipv_live_thd_pc_20260514_1432"

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
        if suite == "google":
            lru_ipcs  = load_ipcs(results_dir / GOOGLE_LRU_DIR)
            srrip_spds = speedups_for_policy(
                results_dir / GOOGLE_SRRIP_DIR, "srrip_live_thd", thresholds, lru_ipcs)
            ipv_spds   = speedups_for_policy(
                results_dir / GOOGLE_IPV_DIR, "ipv_live_thd", thresholds, lru_ipcs)
        else:
            rbase     = results_dir / REBASE_DIRS[suite]
            lru_ipcs  = load_ipcs(rbase / "lru")
            srrip_spds = speedups_for_policy(
                rbase / "srrip_live_llc", "thd", thresholds, lru_ipcs)
            ipv_spds   = speedups_for_policy(
                rbase / "ipv_live_llc", "thd", thresholds, lru_ipcs)

        if not lru_ipcs:
            continue

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
