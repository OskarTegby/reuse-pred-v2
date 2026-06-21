#!/usr/bin/env python3
"""DoA threshold sensitivity plot (per suite).

Geomean IPC speedup vs pure SRRIP as a function of THD_DOA, one curve per suite.
DPC3 uses SimPoint-weighted geomean; all others use flat geomean.

Data source (downloaded from cluster, ChampSim-dev):
  numerator: allsuites_thd_phase{2,3}/llc/srrip_live/doa{N}/{suite}/{trace}
  baseline:  allsuites_thd_phase1/srrip/{suite}/{trace}   (binary champsim_srrip)
cached as results/thd_phase_ipc.tsv (path<TAB>final_ipc).

doa20 is omitted: it finished 233/251 runs, so including it would compute some
suites over a truncated trace set. The remaining thresholds are all complete, so
every suite's curve is over its full trace set.
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

TSV = ROOT / "results" / "thd_phase_ipc.tsv"
P1 = "allsuites_thd_phase1_20260617_0020"
P2 = "allsuites_thd_phase2_20260617_1651"
P3 = "allsuites_thd_phase3_20260618_1245"

# threshold -> srrip_live path prefix (doa20 dropped: incomplete)
THD = {2: f"{P2}/llc/srrip_live/doa2", 4: f"{P2}/llc/srrip_live/doa4",
       6: f"{P2}/llc/srrip_live/doa6", 8: f"{P2}/llc/srrip_live/doa8",
       16: f"{P2}/llc/srrip_live/doa16",
       25: f"{P3}/llc/srrip_live/doa25", 30: f"{P3}/llc/srrip_live/doa30"}
THRESHOLDS = sorted(THD)

SUITES = {"dpc3": "DPC3 (SPEC)", "gap": "GAP", "gms": "GMS", "google": "Google",
          "ligra": "Ligra", "ml": "ML", "qmm": "QMM"}
WEIGHTED = {"dpc3"}
COLORS = {"dpc3": "#8c564b", "gap": "#1f77b4", "gms": "#ff7f0e", "google": "#17becf",
          "ligra": "#2ca02c", "ml": "#d62728", "qmm": "#9467bd"}
MARKERS = {"dpc3": "v", "gap": "o", "gms": "s", "google": "X",
           "ligra": "^", "ml": "D", "qmm": "P"}
CALIBRATED_THD = 6


def load():
    d = {}
    for line in TSV.read_text().splitlines():
        path, ipc = line.split("\t")
        d[path] = float(ipc)
    return d


def by_trace(data, prefix):
    pre = prefix + "/"
    out = {}
    for p, ipc in data.items():
        if p.startswith(pre):
            out[p[len(pre):].split("/")[0]] = ipc
    return out


def main():
    data = load()
    fig, ax = plt.subplots(figsize=(7, 4.2))

    for suite, label in SUITES.items():
        base = by_trace(data, f"{P1}/srrip/{suite}")
        runs = {thd: by_trace(data, f"{THD[thd]}/{suite}") for thd in THRESHOLDS}
        # common intersection across baseline + all plotted thresholds
        common = set(base)
        for thd in THRESHOLDS:
            common &= set(runs[thd])
        common = sorted(common)
        if len(common) < 3:
            continue
        xs, ys = [], []
        for thd in THRESHOLDS:
            ratios = {t: runs[thd][t] / base[t] for t in common if base[t] > 0}
            if suite in WEIGHTED:
                spd = benchmark_weighted_geomean_pct(ratios)
            else:
                g = math.exp(sum(math.log(r) for r in ratios.values()) / len(ratios))
                spd = (g - 1.0) * 100.0
            xs.append(thd)
            ys.append(spd)
        ax.plot(xs, ys, color=COLORS[suite], marker=MARKERS[suite],
                markersize=5, linewidth=1.6, label=f"{label} (n={len(common)})")

    ax.axvline(x=CALIBRATED_THD, color="black", linestyle="--", linewidth=1.0,
               alpha=0.6, label=f"Calibrated $\\theta_{{\\mathrm{{doa}}}}={CALIBRATED_THD}$")
    ax.axhline(0, color="black", linewidth=0.6, alpha=0.3)

    ax.set_xlabel(r"DoA threshold $\theta_{\mathrm{doa}}$", fontsize=10)
    ax.set_ylabel("Geomean speedup vs SRRIP (\\%)", fontsize=10)
    ax.set_xticks(THRESHOLDS)
    ax.tick_params(labelsize=9)
    ax.legend(frameon=False, fontsize=8, ncol=2, loc="lower right")
    ax.grid(axis="y", linestyle=":", alpha=0.4)

    fig.tight_layout()
    out = ROOT / "results" / "plots" / "doa_threshold.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print("wrote", out)


if __name__ == "__main__":
    main()
