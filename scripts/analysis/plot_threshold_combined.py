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


# ── SimPoint weights ──────────────────────────────────────────────────────────

_DEFAULT_WEIGHTS_DIR = (
    Path(__file__).parents[2] / ".." / "ChampSim-dev" / "trace-files" / "SPEC2006_weights"
).resolve()


def _load_spec_weights(weights_dir: Path) -> "dict[str, float]":
    result: dict = {}
    if not weights_dir.is_dir():
        return result
    for bm_dir in sorted(weights_dir.iterdir()):
        if not bm_dir.is_dir():
            continue
        w_file = bm_dir / "weights.out"
        s_file = bm_dir / "simpoints.out"
        if not (w_file.exists() and s_file.exists()):
            continue
        w_vals = [float(x) for x in w_file.read_text().split()]
        s_ids  = [int(x)   for x in s_file.read_text().split()]
        for sp_id, w in zip(s_ids, w_vals):
            result[f"{bm_dir.name}-{sp_id}B"] = w
    return result


def _benchmark_name(wl: str) -> str:
    """Strip SPEC simpoint suffix: 602.gcc_s-734B -> 602.gcc_s."""
    m = re.match(r'^(.+)-\d+[A-Z]+$', wl)
    return m.group(1) if m else wl


_SPEC_WEIGHTS: "dict[str, float]" = _load_spec_weights(_DEFAULT_WEIGHTS_DIR)


def _benchmark_weighted_geomean_pct(ratios_by_wl: "dict[str, float]") -> float:
    """Simpoint-weighted geomean speedup (%).

    For SPEC traces with weights: weighted geomean within each benchmark
    (re-normalised for missing simpoints), then equal-weight geomean across
    benchmarks.  For other traces: flat equal-weight geomean.
    ratios_by_wl values are raw ratios (ipc_new/ipc_base), not percentages.
    """
    groups: dict = {}
    for wl, r in ratios_by_wl.items():
        groups.setdefault(_benchmark_name(wl), []).append(wl)
    per_bench = []
    for wl_list in groups.values():
        if _SPEC_WEIGHTS:
            pairs = [(ratios_by_wl[wl], _SPEC_WEIGHTS.get(wl)) for wl in wl_list]
            if any(w is not None for _, w in pairs):
                pairs = [(r, w) for r, w in pairs if w is not None and r > 0]
                total_w = sum(w for _, w in pairs)
                if total_w > 0:
                    per_bench.append(
                        float(np.exp(sum((w / total_w) * np.log(r) for r, w in pairs))))
                    continue
        vals = [ratios_by_wl[wl] for wl in wl_list if ratios_by_wl[wl] > 0]
        if vals:
            per_bench.append(float(np.exp(np.mean(np.log(vals)))))
    if not per_bench:
        return float("nan")
    return (float(np.exp(np.mean(np.log([r for r in per_bench if r > 0])))) - 1) * 100


# ── Heatmap data ──────────────────────────────────────────────────────────────

def _heatmap_data(base: Path) -> np.ndarray:
    """Return 7×7 simpoint-weighted geomean IPC speedup (%) grid."""
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
                data[pthd, bthd] = _benchmark_weighted_geomean_pct(ratios)
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
