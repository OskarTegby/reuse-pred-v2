#!/usr/bin/env python3
"""Compare scoring weight schemes (modes 3/4/5/7/8) at cap=256.

Shows per-suite geomean speedup vs SRRIP for each scoring mode.
DPC3 uses SimPoint-weighted geomean; other suites use flat geomean.

Data sources:
  SRRIP baseline : results/bypass_allsuites_20260610_2312/{suite}/srrip/
  Modes 4/5/7/8  : results/{suite}_scoring_weights_20260619_2024/{mode}/
  Mode 3          : results/{suite}_scoring_weights_20260619_2026/mode3_123/
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

sys.path.insert(0, str(Path(__file__).parent))
from spec_weights import benchmark_weighted_geomean_pct

BYPASS_LABEL = "bypass_allsuites_20260610_2312"

MODES = [
    ("mode3_123", "mode 3\n(1/2/3)", "20260619_2026"),
    ("mode4_321", "mode 4\n(3/2/1)", "20260619_2024"),
    ("mode5_531", "mode 5\n(5/3/1)", "20260619_2024"),
    ("mode7_111", "mode 7\n(1/1/1)", "20260619_2024"),
    ("mode8_135", "mode 8\n(1/3/5)", "20260619_2024"),
]

SUITES = {
    "dpc3":  "DPC3",
    "gap":   "GAP",
    "gms":   "GMS",
    "ligra": "Ligra",
    "ml":    "ML",
    "qmm":   "QMM",
}

COLORS = {
    "dpc3":  "#8c564b",
    "gap":   "#1f77b4",
    "gms":   "#ff7f0e",
    "ligra": "#2ca02c",
    "ml":    "#d62728",
    "qmm":   "#9467bd",
}

HATCHES = {
    "mode3_123": "",
    "mode4_321": "//",
    "mode5_531": "xx",
    "mode7_111": "..",
    "mode8_135": "\\\\",
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


def suite_speedup(suite: str, mode_key: str, date_label: str) -> tuple:
    """Returns (speedup_pct, n_traces) or (None, 0) if insufficient data."""
    srrip_dir = RESULTS / "baselines" / "srrip" / suite   # canonical pure-SRRIP baseline
    mode_dir = RESULTS / f"{suite}_scoring_weights_{date_label}" / mode_key

    if not srrip_dir.is_dir() or not mode_dir.is_dir():
        return None, 0

    ratios = {}
    for trace_d in srrip_dir.iterdir():
        trace = trace_d.name
        b = get_ipc(srrip_dir / trace / "champsim.out")
        m = get_ipc(mode_dir / trace / "champsim.out")
        if b is not None and m is not None and b > 0:
            ratios[trace] = m / b

    if len(ratios) < 3:
        return None, len(ratios)

    if suite == "dpc3":
        spdup = benchmark_weighted_geomean_pct(ratios)
    else:
        gm = math.exp(sum(math.log(r) for r in ratios.values()) / len(ratios))
        spdup = (gm - 1.0) * 100.0

    return spdup, len(ratios)


def main():
    n_modes = len(MODES)
    n_suites = len(SUITES)
    width = 0.13
    group_gap = 0.9

    fig, ax = plt.subplots(figsize=(10, 4.5))

    x_positions = np.arange(n_suites) * group_gap
    offsets = np.linspace(-(n_modes - 1) / 2, (n_modes - 1) / 2, n_modes) * width

    any_data = False
    for mi, (mode_key, mode_label, date_label) in enumerate(MODES):
        bar_heights = []
        bar_colors = []
        bar_xs = []
        bar_labels = []

        for si, (suite, suite_label) in enumerate(SUITES.items()):
            spdup, n = suite_speedup(suite, mode_key, date_label)
            x = x_positions[si] + offsets[mi]
            if spdup is not None:
                bar_heights.append(spdup)
                bar_colors.append(COLORS[suite])
                bar_xs.append(x)
                bar_labels.append(f"{n}")
                any_data = True
            else:
                bar_heights.append(0)
                bar_colors.append("#cccccc")
                bar_xs.append(x)
                bar_labels.append("–")

        bars = ax.bar(bar_xs, bar_heights, width=width * 0.85,
                      color=bar_colors, hatch=HATCHES[mode_key],
                      edgecolor="white", linewidth=0.5,
                      label=mode_label.replace("\n", " "))

        # Annotate n above each bar (only if data present)
        for bar, h, lbl in zip(bars, bar_heights, bar_labels):
            if lbl != "–" and abs(h) > 0.1:
                ax.text(bar.get_x() + bar.get_width() / 2,
                        h + (0.05 if h >= 0 else -0.25),
                        lbl, ha="center", va="bottom" if h >= 0 else "top",
                        fontsize=5, color="gray")

    if not any_data:
        print("No data found — check result paths")
        sys.exit(1)

    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x_positions)
    ax.set_xticklabels(list(SUITES.values()), fontsize=10)
    ax.set_ylabel("Geomean speedup vs SRRIP (%)", fontsize=10)
    ax.tick_params(axis="y", labelsize=9)
    ax.grid(axis="y", linestyle=":", alpha=0.4)

    # Mode legend (hatch patterns, gray fill)
    from matplotlib.patches import Patch
    legend_handles = [
        Patch(facecolor="gray", hatch=HATCHES[mk], edgecolor="white",
              label=ml.replace("\n", " "))
        for mk, ml, _ in MODES
    ]
    ax.legend(handles=legend_handles, frameon=False, fontsize=8,
              loc="upper right", ncol=len(MODES))

    fig.tight_layout()
    out = ROOT / "results" / "plots" / "scoring_weights.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print("wrote", out)


if __name__ == "__main__":
    main()
