#!/usr/bin/env python3
"""Per-suite bar chart: SRRIP-Live and IPV-Live at optimal THD_DOA vs SRRIP/LRU baseline.

Each group shows two bars (SRRIP-Live green, IPV-Live purple) representing the geomean
speedup at the best threshold for that suite. All bars are normalised to the shared
SRRIP / LRU baseline (lru_baseline directory), which produces identical IPC to plain LRU.
"""

import sys
from pathlib import Path
from statistics import geometric_mean

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

BASE = Path(__file__).resolve().parents[2]
RESULTS = BASE / "results"
CLUSTER = RESULTS / "cluster"
PLOTS = RESULTS / "plots"

# Authoritative rebaseline directories (June 2026 binary, matched LRU+SRRIP baselines)
REBASE_DIRS = {
    "dpc3":  RESULTS / "dpc3_thd_rebaseline_20260605_2316",
    "gap":   RESULTS / "gap_thd_rebaseline_20260605_2316",
    "gms":   RESULTS / "gms_thd_rebaseline_20260605_2316",
    "ligra": RESULTS / "ligra_thd_rebaseline_20260605_2316",
    "ml":    RESULTS / "ml_thd_rebaseline_20260605_2316",
    "qmm":   RESULTS / "qmm_thd_rebaseline_20260604_2307",
}
# Google has no rebaseline dir; use separate dirs with google_repl_pol LRU baseline
GOOGLE_LRU_DIR  = RESULTS / "google_repl_pol_20260522_0722" / "lru_baseline"
GOOGLE_SRRIP_DIR = RESULTS / "google_srrip_live_thd_pc_20260513_0056"
GOOGLE_IPV_DIR   = CLUSTER / "google_ipv_live_thd_pc_20260514_1432"

SUITES = ["dpc3", "qmm", "google", "gap", "gms", "ligra", "ml"]
SUITE_LABELS = {
    "dpc3":   "DPC3",
    "qmm":    "QMM",
    "google": "Google",
    "gap":    "GAP",
    "gms":    "GMS",
    "ligra":  "Ligra",
    "ml":     "ML",
}

THRESHOLDS = [1, 2, 4, 8, 16]
COLOR_SRRIP = "#2ca02c"
COLOR_IPV   = "#9467bd"


def extract_ipc(path):
    try:
        in_roi = False
        for line in open(path, errors="replace"):
            if "Region of Interest Statistics" in line:
                in_roi = True
            if in_roi and "cumulative IPC:" in line:
                import re as _re
                m = _re.search(r"cumulative IPC:\s+([0-9.]+)", line)
                if m:
                    return float(m.group(1))
    except Exception:
        return None


def load_ipcs(d):
    d = Path(d)
    if not d.exists():
        return {}
    out = {}
    for td in sorted(d.iterdir()):
        if not td.is_dir():
            continue
        ipc = extract_ipc(td / "champsim.out")
        if ipc:
            out[td.name] = ipc
    return out


def best_speedup(policy_dirs, prefix, baseline_ipcs):
    """Return (best_thd, best_speedup_pct) over THRESHOLDS."""
    best_thd, best_vs = None, None
    for thd in THRESHOLDS:
        d = policy_dirs / f"{prefix}{thd}"
        live = load_ipcs(d)
        common = set(live) & set(baseline_ipcs)
        if not common:
            continue
        vs = (geometric_mean([live[k] / baseline_ipcs[k] for k in common]) - 1) * 100
        if best_vs is None or vs > best_vs:
            best_vs, best_thd = vs, thd
    return best_thd, best_vs


def main():
    PLOTS.mkdir(exist_ok=True)

    srrip_vals = []
    ipv_vals   = []
    labels     = []

    for suite in SUITES:
        if suite == "google":
            baseline = load_ipcs(GOOGLE_LRU_DIR)
            _, srrip_vs = best_speedup(GOOGLE_SRRIP_DIR, "srrip_live_thd", baseline)
            _, ipv_vs   = best_speedup(GOOGLE_IPV_DIR,   "ipv_live_thd",   baseline)
        else:
            rbase    = REBASE_DIRS[suite]
            baseline = load_ipcs(rbase / "lru")
            _, srrip_vs = best_speedup(rbase / "srrip_live_llc", "thd", baseline)
            _, ipv_vs   = best_speedup(rbase / "ipv_live_llc",   "thd", baseline)

        if not baseline:
            continue

        srrip_vals.append(srrip_vs if srrip_vs is not None else 0.0)
        ipv_vals.append(ipv_vs     if ipv_vs   is not None else 0.0)
        labels.append(SUITE_LABELS[suite])

    x = np.arange(len(labels))
    w = 0.35

    fig, ax = plt.subplots(figsize=(10, 5))

    bars_s = ax.bar(x - w / 2, srrip_vals, w, label="SRRIP-Live", color=COLOR_SRRIP,
                    zorder=3, edgecolor="white", linewidth=0.5)
    bars_i = ax.bar(x + w / 2, ipv_vals,   w, label="IPV-Live",   color=COLOR_IPV,
                    zorder=3, edgecolor="white", linewidth=0.5)

    ax.axhline(0, color="black", linewidth=0.8, zorder=2)

    # Annotate bars with value
    for bar in list(bars_s) + list(bars_i):
        h = bar.get_height()
        ypos = h + 0.15 if h >= 0 else h - 0.55
        ax.text(bar.get_x() + bar.get_width() / 2, ypos,
                f"{h:+.1f}%", ha="center", va="bottom" if h >= 0 else "top",
                fontsize=7, color="black")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("Geomean speedup vs. LRU (%)", fontsize=10)
    ax.yaxis.grid(True, linestyle="--", linewidth=0.5, alpha=0.7, zorder=0)
    ax.set_axisbelow(True)

    ax.legend(fontsize=9, loc="upper right")
    fig.subplots_adjust(bottom=0.12, top=0.96, left=0.09, right=0.98)

    out = PLOTS / "policy_comparison_optimal.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
