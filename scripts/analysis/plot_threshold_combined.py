#!/usr/bin/env python3
"""
plot_threshold_combined.py — combined 1×3 IPC speedup heatmap for QMM, SPEC, Google.

Each panel shows the geomean IPC speedup (%) vs baseline across the full 7×7
dpPred×cbPred threshold grid (pthd rows, bthd columns).  All three panels share
a single colorbar scale (driven by Qualcomm's larger range) so that the near-flat
SPEC and Google surfaces are visually distinguishable from Qualcomm's large gradient.

Usage
-----
  python3 scripts/analysis/plot_threshold_combined.py \
      --qmm   results/qmm_20260322 \
      --dpc3  results/dpc3_oldcfg_thd_20260428_2229 \
      --google results/google_oldcfg_thd_20260428_2229 \
      --out   results/plots/dp_cbpred_study/threshold_heatmaps_combined.png
"""

import argparse
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np


# ── IPC parsing ───────────────────────────────────────────────────────────────

def _parse_ipc(path: Path):
    in_roi = False
    try:
        for line in path.read_text(errors="replace").splitlines():
            if "Region of Interest Statistics" in line:
                in_roi = True
            if in_roi and "cumulative IPC:" in line:
                m = re.search(r"cumulative IPC:\s+([0-9.]+)", line)
                if m:
                    return float(m.group(1))
    except OSError:
        pass
    return None


def _benchmark_name(wl: str) -> str:
    """Strip simpoint suffix so all simpoints of one benchmark share a key.
    SPEC: 600.perlbench_s-1273B → 600.perlbench_s
    Google: arizona_0000 → arizona
    Other (QMM, etc.): returned unchanged.
    """
    m = re.match(r'^(.+)-\d+[A-Z]+$', wl)
    if m:
        return m.group(1)
    m = re.match(r'^(.+)_\d{4}$', wl)
    if m:
        return m.group(1)
    return wl


def _benchmark_geomean_speedup(ratios_by_trace: dict) -> float:
    """Benchmark-weighted geomean IPC speedup (%).

    Groups simpoints by benchmark, takes geomean within each group, then
    geomean across groups so SPEC simpoint count doesn't skew the result.
    """
    from collections import defaultdict
    groups: dict = defaultdict(list)
    for t, r in ratios_by_trace.items():
        if r > 0:
            groups[_benchmark_name(t)].append(r)
    if not groups:
        return float("nan")
    bench_means = [float(np.exp(np.mean(np.log(rs)))) for rs in groups.values()]
    return (float(np.exp(np.mean(np.log(bench_means)))) - 1.0) * 100.0


# ── Heatmap data ──────────────────────────────────────────────────────────────

def _heatmap_data(base: Path) -> np.ndarray:
    """Return 7×7 benchmark-weighted geomean IPC speedup (%) grid."""
    bl_dir = base / "baseline"
    traces = sorted(d.name for d in bl_dir.iterdir() if d.is_dir())
    baselines = {t: _parse_ipc(bl_dir / t / "champsim.out") for t in traces}
    baselines = {t: v for t, v in baselines.items() if v is not None}

    data = np.full((7, 7), np.nan)
    for pthd in range(7):
        for bthd in range(7):
            cfg = f"pthd{pthd}_bthd{bthd}"
            ratios: dict = {}
            for t, bi in baselines.items():
                v = _parse_ipc(base / cfg / t / "champsim.out")
                if v is not None and bi > 0:
                    ratios[t] = v / bi
            if ratios:
                data[pthd, bthd] = _benchmark_geomean_speedup(ratios)
    return data


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--qmm",    required=True)
    ap.add_argument("--dpc3",   required=True)
    ap.add_argument("--google", required=True)
    ap.add_argument("--out",    required=True)
    args = ap.parse_args()

    panels = [
        (Path(args.qmm),    "(a) Qualcomm"),
        (Path(args.dpc3),   "(b) SPEC CPU2006"),
        (Path(args.google), "(c) Google"),
    ]

    nr = list(range(7))

    # Pre-compute all data so we can build a shared scale.
    print("Loading data …")
    all_data = []
    for base, label in panels:
        print(f"  {label} …")
        all_data.append(_heatmap_data(base))

    global_vmax = max(
        float(np.nanmax(np.abs(d))) for d in all_data if np.any(~np.isnan(d))
    )
    global_vmax = max(global_vmax, 0.1)
    norm = mcolors.TwoSlopeNorm(vmin=-global_vmax, vcenter=0.0, vmax=global_vmax)

    fig, axes = plt.subplots(1, 3, figsize=(14, 5), constrained_layout=True)

    im = None
    for ax, (base, panel_label), data in zip(axes, panels, all_data):
        im = ax.imshow(data, cmap="RdYlGn", norm=norm,
                       origin="lower", aspect="equal")

        for pthd in nr:
            for bthd in nr:
                v = data[pthd, bthd]
                if not np.isnan(v):
                    txt = f"+{v:.2f}" if v >= 0 else f"{v:.2f}"
                    tc = "white" if abs(v) > global_vmax * 0.55 else "black"
                    ax.text(bthd, pthd, txt, ha="center", va="center",
                            fontsize=6.5, color=tc)

        ax.set_xticks(nr)
        ax.set_xticklabels([str(i) for i in nr], fontsize=8)
        ax.set_yticks(nr)
        ax.set_yticklabels([str(i) for i in nr], fontsize=8)
        ax.set_xlabel("bthd", fontsize=9)
        if ax is axes[0]:
            ax.set_ylabel("pthd", fontsize=9)

        ax.set_title(panel_label, fontsize=10, fontweight="bold", pad=5)

    # Single shared colorbar to the right of all panels.
    cb = fig.colorbar(im, ax=axes, fraction=0.02, pad=0.02, shrink=0.8)
    cb.set_label("IPC speedup (%)", fontsize=9)
    cb.ax.tick_params(labelsize=8)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
