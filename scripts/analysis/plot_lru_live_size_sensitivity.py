#!/usr/bin/env python3
"""LLC history-table size sensitivity for LRU-Live (vs LRU baseline), at each
suite's own optimal DoA threshold.

Per-suite geomean IPC speedup over plain LRU as a function of REPL_HIST_LLC_CAP,
normalised to each suite's own speedup at the largest capacity tested (16,384
entries, treated as the unbounded ceiling = 100%). SPEC uses SimPoint-weighted
geomean; all others use flat geomean. GMS is excluded: its guidance results
are negative at every capacity, so there is nothing to show on this axis.

Data sources:
  numerator : results/lru_live_size_peakthd_20260630_2127/cap{N}/{suite}/{trace}
              (thd_doa per suite: gap=2, ligra=4, ml=30, qmm=8, google=30, dpc3=30)
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

DATA_DIR = ROOT / "results" / "lru_live_size_peakthd_20260630_2127"
CAPS = [8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384]

SUITES = {"dpc3": "SPEC", "gap": "GAP", "google": "Google",
          "ligra": "Ligra", "ml": "ML", "qmm": "QMM"}
WEIGHTED = {"dpc3"}
COLORS  = {"dpc3": "#8c564b", "gap": "#1f77b4", "google": "#17becf",
           "ligra": "#2ca02c", "ml": "#d62728", "qmm": "#9467bd"}
MARKERS = {"dpc3": "v", "gap": "o", "google": "X",
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

        cap_pct = {}
        for cap in CAPS:
            suite_dir = DATA_DIR / f"cap{cap}" / suite
            if not suite_dir.is_dir():
                continue
            ratios = {}
            for tr in base:
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
            cap_pct[cap] = pct

        if 16384 not in cap_pct or cap_pct[16384] == 0:
            continue
        ceiling = cap_pct[16384]

        xs = [CAPS.index(cap) for cap in CAPS if cap in cap_pct]
        ys = [cap_pct[cap] / ceiling * 100.0 for cap in CAPS if cap in cap_pct]
        ax.plot(xs, ys, color=COLORS[suite], marker=MARKERS[suite],
                markersize=5, linewidth=1.6, label=label)

    ax.axhline(100, color="black", linestyle="--", linewidth=0.8, alpha=0.5)
    ax.set_xlabel("LLC history table capacity (entries)", fontsize=10)
    ax.set_ylabel("% of unbounded-table speedup", fontsize=10)
    ax.set_xticks(range(len(CAPS)))
    ax.set_xticklabels(["8", "16", "32", "64", "128", "256", "512", "1K", "2K", "4K", "8K", "16K"], fontsize=8)
    ax.tick_params(axis="y", labelsize=9)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    ax.grid(axis="y", linestyle=":", alpha=0.4)

    fig.tight_layout()
    out = ROOT / "results" / "plots" / "lru_live_size_sensitivity.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print("wrote", out)


if __name__ == "__main__":
    main()
