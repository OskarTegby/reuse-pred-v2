#!/usr/bin/env python3
"""
plot_cbpred_dist_combined.py — combined 1×3 figure of dpPred+cbPred optimal
threshold distribution heatmaps for SPEC, Google, and Qualcomm.

For each suite the script finds the per-group optimal (pthd, bthd) pair and
counts how many groups chose each cell in a 7×7 grid.

Usage
-----
  python3 scripts/analysis/plot_cbpred_dist_combined.py \
      --dpc3   results/dpc3_oldcfg_thd_20260428_2229 \
      --google results/google_oldcfg_thd_20260428_2229 \
      --qmm    results/qmm_20260322 \
      --out    results/plots/dp_cbpred_study/cbpred_dist_combined.png
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from spec_weights import benchmark_weighted_geomean_pct, SPEC_WEIGHTS, benchmark_name
from champsim_utils import parse_ipc

# ── Parsing ───────────────────────────────────────────────────────────────────


def _wgeomean(speedups, weights):
    pairs = [(s / 100.0 + 1.0, w) for s, w in zip(speedups, weights)]
    valid = [(r, w) for r, w in pairs if r > 0 and w is not None]
    if valid:
        total = sum(w for _, w in valid)
        if total > 0:
            return (np.exp(sum((w / total) * np.log(r) for r, w in valid)) - 1.0) * 100.0
    pos = [r for r, _ in pairs if r > 0]
    return (np.exp(np.mean(np.log(pos))) - 1.0) * 100.0 if pos else float("nan")


def _group_name(trace: str, suite: str) -> str:
    if suite == "dpc3":
        m = re.match(r"^(.+)-\d+[A-Z]+$", trace)
        return m.group(1) if m else trace
    if suite == "google":
        return re.sub(r"_\d+$", "", trace)
    return trace


# ── Distribution for one suite ────────────────────────────────────────────────

def _opt_keys(base: Path, suite: str):
    """Return list of optimal (pthd, bthd) keys — one per trace (Google) or group."""
    nr      = list(range(7))
    use_wts = (suite == "dpc3")
    bl_dir  = base / "baseline"
    traces  = sorted(d.name for d in bl_dir.iterdir() if d.is_dir())
    baselines = {t: parse_ipc(bl_dir / t / "champsim.out") for t in traces}
    baselines = {t: v for t, v in baselines.items() if v is not None}

    all_keys = [(n, m) for n in nr for m in nr]

    grid = {}
    for t, bi in baselines.items():
        grid[t] = {}
        for key in all_keys:
            v = parse_ipc(base / f"pthd{key[0]}_bthd{key[1]}" / t / "champsim.out")
            if v is not None and bi > 0:
                grid[t][key] = (v / bi - 1.0) * 100.0

    if suite == "google":
        # one key per individual trace
        keys = []
        for t in sorted(baselines):
            best_k, best_v = None, float("-inf")
            for key in all_keys:
                v = grid[t].get(key)
                if v is not None and v > best_v:
                    best_v, best_k = v, key
            if best_k is not None:
                keys.append(best_k)
        return keys, len(keys)

    groups = defaultdict(list)
    for t in grid:
        groups[_group_name(t, suite)].append(t)

    keys = []
    for grp, tlist in sorted(groups.items()):
        best_k, best_v = None, float("-inf")
        for key in all_keys:
            sps, wts = [], []
            for t in tlist:
                if key in grid.get(t, {}):
                    sps.append(grid[t][key])
                    wts.append(SPEC_WEIGHTS.get(t) if use_wts else None)
            if sps:
                v = _wgeomean(sps, wts)
                if not np.isnan(v) and v > best_v:
                    best_v, best_k = v, key
        if best_k is not None:
            keys.append(best_k)

    return keys, len(keys)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dpc3",   required=True)
    ap.add_argument("--google", required=True)
    ap.add_argument("--qmm",    required=True)
    ap.add_argument("--out",    required=True)
    args = ap.parse_args()

    # unit label per suite (shown in panel title)
    _units = {"dpc3": "benchmarks", "google": "traces", "qmm": "traces"}

    panels = [
        (Path(args.dpc3),   "dpc3",   "(a) SPEC CPU2006"),
        (Path(args.google), "google", "(b) Google"),
        (Path(args.qmm),    "qmm",    "(c) Qualcomm"),
    ]

    nr = list(range(7))
    def_n, def_b = 6, 6

    fig, axes = plt.subplots(1, 3, figsize=(13, 4.5), constrained_layout=True)

    for ax, (base, suite, panel_label) in zip(axes, panels):
        print(f"Computing {panel_label} …")
        opt_keys, n_total = _opt_keys(base, suite)

        counts = np.zeros((7, 7), dtype=int)
        for key in opt_keys:
            counts[key[0], key[1]] += 1

        assert int(counts.sum()) == n_total, \
            f"{panel_label}: cell sum {counts.sum()} ≠ expected {n_total}"

        vmax = max(counts.max(), 1)
        im   = ax.imshow(counts, cmap="Blues", vmin=0, vmax=vmax,
                         origin="lower", aspect="equal")

        for n in nr:
            for m in nr:
                c  = counts[n, m]
                tc = "white" if c > vmax * 0.55 else "black"
                ax.text(m, n, str(c), ha="center", va="center",
                        fontsize=8, color=tc,
                        fontweight="bold" if c > 0 else "normal")

        # Red border around default cell
        ax.add_patch(plt.Rectangle(
            (def_b - 0.5, def_n - 0.5), 1, 1,
            fill=False, edgecolor="#d62728", lw=2.5, zorder=3,
        ))

        ax.set_xticks(nr)
        ax.set_xticklabels([str(m) for m in nr], fontsize=8)
        ax.set_yticks(nr)
        ax.set_yticklabels([str(n) for n in nr], fontsize=8)
        ax.set_xlabel("bthd", fontsize=9)
        if ax is axes[0]:
            ax.set_ylabel("pthd", fontsize=9)

        unit = _units[suite]
        ax.set_title(f"{panel_label}\n($n = {n_total}$ {unit})",
                     fontsize=10, fontweight="bold", pad=4)

        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, shrink=0.85)
        cb.set_label("Count", fontsize=8)
        cb.ax.tick_params(labelsize=7)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
