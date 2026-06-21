#!/usr/bin/env python3
"""LLC history table size sensitivity plot.

Per-suite geomean speedup vs SRRIP (%) as a function of bounded history table
capacity.  The unbounded result is plotted as an extra point at the right edge
where data is available.

Sources:
  bounded  : results/size_srrip_live_small_20260619_1402/{suite}/tier_c{cap}/  (cap 256-4096)
             results/size_srrip_live_ext_20260619_1534/{suite}/tier_c{cap}/    (cap 8-128; all QMM)
             results/size_srrip_live_large_20260619_2322/{suite}/tier_c{cap}/  (cap 8K/16K + DPC3 all)
  unbounded: results/size_srrip_live_unbound_20260619_2009/{suite}/unbound/    (gap/gms/ligra/ml/qmm)
             results/size_srrip_live_large_20260619_2322/dpc3/unbound/         (DPC3; 6/95 complete)
  srrip    : results/baselines/srrip/{suite}/                                  (canonical baseline)
"""

import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"

BYPASS_LABEL  = "bypass_allsuites_20260610_2312"
UNBOUND_LABEL = "size_srrip_live_unbound_20260619_2009"   # gap/gms/ligra/ml/qmm

# cap -> which result label holds it
LABEL_SMALL = "size_srrip_live_small_20260619_1402"   # 256-4096 for small suites
LABEL_EXT   = "size_srrip_live_ext_20260619_1534"     # 8-128 for small suites; all caps for QMM
LABEL_LARGE = "size_srrip_live_large_20260619_2322"   # 8K/16K all suites; all caps + unbound DPC3

CAPS = [8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384]

SUITES = {
    "dpc3":  "DPC3 (SPEC)",
    "gap":   "GAP",
    "gms":   "GMS",
    "ligra": "Ligra",
    "ml":    "ML",
    "qmm":   "QMM",
}

# Which label to use per (suite, cap)
def cap_label(suite, cap):
    if suite == "dpc3":
        return LABEL_LARGE
    if cap >= 8192:
        return LABEL_LARGE
    if suite == "qmm":
        return LABEL_EXT
    return LABEL_SMALL if cap >= 256 else LABEL_EXT

def unbound_dir(suite):
    if suite == "dpc3":
        return RESULTS / LABEL_LARGE / suite / "unbound"
    return RESULTS / UNBOUND_LABEL / suite / "unbound"

COLORS = {
    "dpc3":  "#8c564b",
    "gap":   "#1f77b4",
    "gms":   "#ff7f0e",
    "ligra": "#2ca02c",
    "ml":    "#d62728",
    "qmm":   "#9467bd",
}

MARKERS = {
    "dpc3":  "v",
    "gap":   "o",
    "gms":   "s",
    "ligra": "^",
    "ml":    "D",
    "qmm":   "P",
}


def get_ipc(path: Path):
    try:
        with open(path) as f:
            for line in f:
                if "CPU 0 cumulative IPC:" in line:
                    return float(line.split()[4])
    except Exception:
        pass
    return None


def geomean_ratio(pairs):
    if not pairs:
        return None
    return math.exp(sum(math.log(m / b) for m, b in pairs) / len(pairs))


def main():
    x_bounded = list(range(len(CAPS)))   # 0..11
    x_unbound = len(CAPS)                # one step past last bounded cap

    fig, ax = plt.subplots(figsize=(7, 4))

    for suite, label in SUITES.items():
        srrip_dir    = RESULTS / "baselines" / "srrip" / suite
        unbound_dir_ = unbound_dir(suite)
        cap_dirs     = [RESULTS / cap_label(suite, cap) / suite / f"tier_c{cap}" for cap in CAPS]

        if not srrip_dir.is_dir() or not unbound_dir_.is_dir():
            continue

        # Collect per-trace SRRIP baseline and unbounded reference (common traces only)
        base_traces = {}
        for td in srrip_dir.iterdir():
            b = get_ipc(td / "champsim.out")
            u = get_ipc(unbound_dir_ / td.name / "champsim.out")
            if b is not None and u is not None and b > 0:
                base_traces[td.name] = (b, u)

        if not base_traces:
            continue

        # Unbounded geomean (over common traces)
        gm_unb = geomean_ratio([(u, b) for b, u in base_traces.values()])
        unb_pct = (gm_unb - 1.0) * 100 if gm_unb is not None else None

        color  = COLORS[suite]
        marker = MARKERS[suite]
        n      = len(base_traces)

        # Per-cap: absolute speedup vs SRRIP (%)
        xs, ys = [], []
        for xi, (cap, cd) in enumerate(zip(CAPS, cap_dirs)):
            pairs = []
            for name, (b, _) in base_traces.items():
                m = get_ipc(cd / name / "champsim.out")
                if m is not None:
                    pairs.append((m, b))
            if len(pairs) >= 3:
                gm = geomean_ratio(pairs)
                if gm is not None:
                    xs.append(xi)
                    ys.append((gm - 1.0) * 100)

        if not xs:
            continue

        ax.plot(xs, ys, color=color, marker=marker, markersize=5,
                linewidth=1.5, label=f"{label} (n={n})")

        # Unbounded point at x_unbound (hollow marker), if available
        if unb_pct is not None:
            ax.plot(x_unbound, unb_pct,
                    color=color, marker=marker, markersize=6,
                    markerfacecolor="white", markeredgewidth=1.5,
                    linestyle="none", zorder=5)
            ax.plot([xs[-1], x_unbound], [ys[-1], unb_pct],
                    color=color, linestyle=":", linewidth=0.8)

    ax.axhline(y=0, color="black", linewidth=0.8)
    tick_labels = ["8", "16", "32", "64", "128", "256", "512", "1K", "2K", "4K", "8K", "16K", "∞"]
    ax.set_xticks(x_bounded + [x_unbound])
    ax.set_xticklabels(tick_labels, fontsize=7)
    ax.set_xlabel("LLC history table capacity (entries)", fontsize=10)
    ax.set_ylabel("Geomean speedup vs SRRIP (%)", fontsize=10)
    ax.tick_params(axis="y", labelsize=9)
    ax.legend(frameon=False, fontsize=9, loc="upper right",
              bbox_to_anchor=(1.0, 0.92))
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    ax.set_xlim(-0.4, x_unbound + 0.4)

    fig.tight_layout()
    out = ROOT / "results" / "plots" / "size_sensitivity.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print("wrote", out)


if __name__ == "__main__":
    main()
