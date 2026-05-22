#!/usr/bin/env python3
"""plot_pc_bypass.py — IPC speedup for PC-indexed and merged bypass modes.

Compares CBPRED_IDX configurations vs the addr-indexed paper baseline:
  lru_baseline  — no predictor (IPC floor)
  addr_pred     — paper-style addr-indexed bypass  (reference)
  pc_pred       — PC-indexed bypass
  merged_pred   — merged STLB+LLC table bypass

Produces a grouped bar chart: one group per suite, three bars per group
(addr_pred, pc_pred, merged_pred), all normalised to lru_baseline.

Usage
-----
    python3 scripts/analysis/plot_pc_bypass.py \\
        --dirs  results/dpc3_pc_bypass_<date>/ \\
                results/gap_pc_bypass_<date>/  ... \\
        --labels "SPEC (DPC3)" GAP GMS Google Ligra MAZ Qualcomm \\
        [--out results/plots/pc_bypass/pc_bypass.png]
"""

import argparse
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from champsim_utils import geomean_speedup

CONFIGS = [
    ("addr_pred",   "addr (paper baseline)", "#4393C3"),
    ("pc_pred",     "PC-indexed",            "#D73027"),
    ("merged_pred", "merged STLB+LLC",       "#1A9641"),
]
BASELINE = "lru_baseline"


def load_suite(suite_dir: Path) -> "dict[str, float | None]":
    base_dir = suite_dir / BASELINE
    if not base_dir.is_dir():
        print(f"WARNING: no {BASELINE}/ in {suite_dir}", file=sys.stderr)
        return {cfg: None for cfg, _, _ in CONFIGS}
    result = {}
    for cfg, _, _ in CONFIGS:
        exp_dir = suite_dir / cfg
        if exp_dir.is_dir():
            v = geomean_speedup(str(exp_dir), str(base_dir))
            result[cfg] = None if math.isnan(v) else v
        else:
            result[cfg] = None
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dirs",   nargs="+", required=True,
                    help="pc_bypass result directories, one per suite")
    ap.add_argument("--labels", nargs="+", default=None,
                    help="Suite labels (default: inferred from dir names)")
    ap.add_argument("--out",    default="results/plots/pc_bypass/pc_bypass.png")
    args = ap.parse_args()

    dirs   = [Path(d) for d in args.dirs]
    labels = args.labels or [d.name.split("_")[0].upper() for d in dirs]
    if len(labels) != len(dirs):
        sys.exit("ERROR: --labels count must match --dirs count")

    suites = []
    for d, label in zip(dirs, labels):
        print(f"Loading '{label}' from {d.name} …")
        data = load_suite(d)
        for cfg, desc, _ in CONFIGS:
            v = data[cfg]
            print(f"  {cfg:<14}: {v:+.3f}%" if v is not None else f"  {cfg}: missing")
        suites.append({"label": label, "data": data})

    n      = len(suites)
    n_cfg  = len(CONFIGS)
    width  = 0.20
    gap    = 0.08
    group  = n_cfg * width + gap

    x = np.arange(n) * group

    fig, ax = plt.subplots(figsize=(max(8, 1.4 * n), 4.2))

    for i, (cfg, desc, color) in enumerate(CONFIGS):
        vals = [s["data"].get(cfg) for s in suites]
        offsets = x + (i - (n_cfg - 1) / 2) * width
        heights = [v if v is not None else 0.0 for v in vals]
        ax.bar(offsets, heights, width * 0.88,
               label=desc, color=color,
               edgecolor="black", linewidth=0.5, zorder=3)

    ax.axhline(0, color="black", linewidth=0.8, linestyle="--", zorder=1)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("IPC speedup vs. no-pred baseline (geomean, %)", fontsize=9)
    ax.set_title("PC-indexed and merged bypass prediction vs. address-indexed baseline",
                 fontsize=10, fontweight="bold")
    ax.yaxis.grid(True, linestyle="--", color="gray", alpha=0.55, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f%%"))

    all_vals = [v for s in suites for _, _, _ in CONFIGS
                for v in [s["data"].get(CONFIGS[0][0])] if v is not None]
    all_vals = [v for s in suites for cfg, _, _ in CONFIGS
                if (v := s["data"].get(cfg)) is not None]
    if all_vals:
        lo, hi = min(all_vals), max(all_vals)
        span   = max(hi - lo, 0.2)
        ax.set_ylim(lo - 0.20 * span, hi + 0.25 * span)

    ax.legend(loc="upper right", fontsize=9, framealpha=0.9)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=180, bbox_inches="tight")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
