#!/usr/bin/env python3
"""Liveness contribution: each guided policy vs its OWN non-guided base
(LRU-Live/LRU, SRRIP-Live/SRRIP), no bypass. Both policies at the common
THD_DOA=6 anchor with set dueling -- the current, consistent methodology
(matches the arch-rerun scripts and Figure 2), not the old mixed one
(SRRIP-Live at a per-suite-optimal non-dueling threshold, LRU-Live at a
fixed single arm) this plot used previously.

Sources:
  LRU-Live:   results/lru_live_theta6_20260624_0126/.../duel vs baselines/lru
  SRRIP-Live: results/srrip_live_theta6_20260623_1834/duel  vs baselines/srrip
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

LRU_LIVE_DIR = ROOT / "results" / "lru_live_theta6_20260624_0126" / "lru_live_theta6_20260624_0126" / "duel"
SRRIP_LIVE_DIR = ROOT / "results" / "srrip_live_theta6_20260623_1834" / "duel"

SUITES = {"dpc3": "SPEC", "gap": "GAP", "gms": "GMS", "ligra": "Ligra",
          "ml": "ML", "qmm": "QMM", "google": "Google"}
WEIGHTED = {"dpc3"}


def get_ipc(path):
    try:
        for line in reversed(Path(path).read_text().splitlines()):
            if "CPU 0 cumulative IPC:" in line:
                return float(line.split()[4])
    except Exception:
        pass
    return None


def suite_pct(base_dir, live_dir, suite):
    bdir, ldir = base_dir / suite, live_dir / suite
    if not bdir.is_dir() or not ldir.is_dir():
        return None
    base = {td.name: get_ipc(td / "champsim.out") for td in bdir.iterdir() if td.is_dir()}
    base = {k: v for k, v in base.items() if v}
    ratios = {}
    for tr, b in base.items():
        live = get_ipc(ldir / tr / "champsim.out")
        if live and b > 0:
            ratios[tr] = live / b
    if len(ratios) < 3:
        return None
    if suite in WEIGHTED:
        return benchmark_weighted_geomean_pct(ratios)
    g = math.exp(sum(math.log(r) for r in ratios.values()) / len(ratios))
    return (g - 1.0) * 100.0


def main():
    configs = {
        "LRU-Live / LRU": (ROOT / "results" / "baselines" / "lru", LRU_LIVE_DIR, "#1f77b4"),
        "SRRIP-Live / SRRIP": (ROOT / "results" / "baselines" / "srrip", SRRIP_LIVE_DIR, "#2a7f3f"),
    }

    order = ["dpc3", "gap", "gms", "ligra", "ml", "qmm", "google"]
    results = {}
    for label, (base_dir, live_dir, _color) in configs.items():
        results[label] = {}
        for suite in order:
            pct = suite_pct(base_dir, live_dir, suite)
            if pct is not None:
                results[label][suite] = pct

    suites = [s for s in order if all(s in results[label] for label in configs)]
    labels = [SUITES[s] for s in suites]

    x = list(range(len(suites)))
    w = 0.32
    fig, ax = plt.subplots(figsize=(9, 4.4))
    for i, (label, (_bd, _ld, color)) in enumerate(configs.items()):
        vals = [results[label][s] for s in suites]
        off = (i - 0.5) * w
        ax.bar([xi + off for xi in x], vals, w,
               label=label, color=color, edgecolor="black", linewidth=0.4)

    ax.axhline(0, color="black", linewidth=0.6)
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.set_ylabel("Geomean IPC speedup over non-guided base (%)")
    ax.set_title("Replacement guidance only: each guided policy vs. its own non-guided base\n"
                 r"(both at $\theta_{\mathrm{doa}}=6$ with set dueling; no bypass)")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()
    out = ROOT / "results" / "plots" / "live_vs_base.png"
    fig.savefig(out, dpi=150)
    print("wrote", out)

    print("\nGeomean speedup over own non-guided base (%):")
    for label in configs:
        row = "  ".join("%s=%+.2f%%" % (SUITES[s], results[label][s]) for s in suites)
        print("  %-20s %s" % (label, row))


if __name__ == "__main__":
    main()
