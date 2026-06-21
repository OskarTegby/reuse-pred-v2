#!/usr/bin/env python3
"""DoA threshold sensitivity for LRU-Live (vs LRU baseline).

Per-suite geomean IPC speedup over plain LRU as a function of THD_DOA.
DPC3 uses SimPoint-weighted geomean; all others use flat geomean.

Data sources:
  numerator : allsuites_thd_phase{2,3}/llc/lru_live/doa{N}/{suite}/{trace}
  baseline  : results/baselines/lru/{suite}/{trace}
"""

import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
from spec_weights import benchmark_weighted_geomean_pct  # noqa: E402

P2 = "allsuites_thd_phase2_20260617_1651"
P3 = "allsuites_thd_phase3_20260618_1245"

THD = {
    2:  (ROOT / "results" / P2 / "llc" / "lru_live" / "doa2"),
    4:  (ROOT / "results" / P2 / "llc" / "lru_live" / "doa4"),
    6:  (ROOT / "results" / P2 / "llc" / "lru_live" / "doa6"),
    8:  (ROOT / "results" / P2 / "llc" / "lru_live" / "doa8"),
    16: (ROOT / "results" / P2 / "llc" / "lru_live" / "doa16"),
    20: (ROOT / "results" / P3 / "llc" / "lru_live" / "doa20"),
    25: (ROOT / "results" / P3 / "llc" / "lru_live" / "doa25"),
    30: (ROOT / "results" / P3 / "llc" / "lru_live" / "doa30"),
}
THRESHOLDS = sorted(THD)

SUITES = {"dpc3": "DPC3 (SPEC)", "gap": "GAP", "gms": "GMS", "google": "Google",
          "ligra": "Ligra", "ml": "ML", "qmm": "QMM"}
WEIGHTED = {"dpc3"}
COLORS  = {"dpc3": "#8c564b", "gap": "#1f77b4", "gms": "#ff7f0e", "google": "#17becf",
           "ligra": "#2ca02c", "ml": "#d62728", "qmm": "#9467bd"}
MARKERS = {"dpc3": "v", "gap": "o", "gms": "s", "google": "X",
           "ligra": "^", "ml": "D", "qmm": "P"}


def get_ipc(path):
    try:
        for line in reversed(Path(path).read_text().splitlines()):
            if "CPU 0 cumulative IPC:" in line:
                return float(line.split()[4])
    except Exception:
        pass
    return None


def main():
    fig, ax = plt.subplots(figsize=(7, 4.2))

    for suite, label in SUITES.items():
        base_dir = ROOT / "results" / "baselines" / "lru" / suite
        if not base_dir.is_dir():
            continue

        base = {td.name: get_ipc(td / "champsim.out")
                for td in base_dir.iterdir() if td.is_dir()}
        base = {k: v for k, v in base.items() if v}

        # intersection across baseline + all thresholds
        common = set(base)
        for thd, thd_dir in THD.items():
            suite_dir = thd_dir / suite
            if suite_dir.is_dir():
                common &= {td.name for td in suite_dir.iterdir() if td.is_dir()}
        common = sorted(common)
        if len(common) < 3:
            continue

        xs, ys = [], []
        for thd in THRESHOLDS:
            suite_dir = THD[thd] / suite
            if not suite_dir.is_dir():
                continue
            ratios = {}
            for tr in common:
                live = get_ipc(suite_dir / tr / "champsim.out")
                if live and base[tr] > 0:
                    ratios[tr] = live / base[tr]
            if len(ratios) < 3:
                continue
            if suite in WEIGHTED:
                pct = benchmark_weighted_geomean_pct(ratios)
            else:
                g = math.exp(sum(math.log(r) for r in ratios.values()) / len(ratios))
                pct = (g - 1.0) * 100.0
            xs.append(thd)
            ys.append(pct)

        if not xs:
            continue

        ax.plot(xs, ys, color=COLORS[suite], marker=MARKERS[suite],
                markersize=5, linewidth=1.6, label=f"{label} (n={len(common)})")

    ax.axhline(0, color="black", linewidth=0.6, alpha=0.3)
    ax.set_xlabel(r"DoA threshold $\theta_{\mathrm{doa}}$", fontsize=10)
    ax.set_ylabel("Geomean speedup vs LRU (%)", fontsize=10)
    ax.set_xticks(THRESHOLDS)
    ax.tick_params(labelsize=9)
    ax.legend(frameon=False, fontsize=8, ncol=2, loc="lower left")
    ax.grid(axis="y", linestyle=":", alpha=0.4)

    fig.tight_layout()
    out = ROOT / "results" / "plots" / "lru_live_threshold.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print("wrote", out)


if __name__ == "__main__":
    main()
