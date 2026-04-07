#!/usr/bin/env python3
"""plot_addr_vs_pc_summary.py — geomean IPC speedup summary: addr vs PC, promote vs no-promote.

Four bars per suite (each at its own optimal mid_thd):
  addr, no-promote  — lru_mid_new runs (post-fix: no promotion on hit)
  addr, promote     — mid_lru_study runs (pre-fix: implicit promotion on hit)
  PC,   no-promote  — lru_mid_new runs
  PC,   promote     — mid_lru_study runs (or newer explicit --mid-promote run)

Output: results/plots/mid_lru/addr_vs_pc_summary.png
"""

import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

BASE = Path("results")

# (label, color, sweep_dir)
CONFIGS = [
    ("addr, no-promote", "#5B7FA6"),   # steel blue
    ("addr, promote",    "#1A4A7A"),   # dark navy blue
    ("PC, no-promote",   "#E09B6A"),   # light orange
    ("PC, promote",      "#B03000"),   # dark red-orange
]

SUITES = [
    {
        "label": "SPEC (DPC3)",
        "dirs": [
            BASE / "lru_mid_new/dpc3_mid_addr_20260406_1251",       # addr no-promo
            BASE / "mid_lru_study/dpc3_mid_addr_20260401_2359",     # addr promote (pre-fix implicit)
            BASE / "lru_mid_new/dpc3_mid_pc_20260406_1251",         # PC no-promo
            BASE / "mid_lru_study/dpc3_mid_pc_20260401_2359",       # PC promote (pre-fix implicit)
        ],
    },
    {
        "label": "Google",
        "dirs": [
            BASE / "lru_mid_new/google_mid_addr_20260406_1251",     # addr no-promo
            BASE / "mid_lru_study/google_mid_addr_20260402_0000",   # addr promote (pre-fix implicit)
            BASE / "lru_mid_new/google_mid_pc_20260406_1251",       # PC no-promo
            BASE / "mid_lru_study/google_mid_pc_promote_20260407_1031",  # PC promote (explicit)
        ],
    },
    {
        "label": "Qualcomm",
        "dirs": [
            BASE / "lru_mid_new/qmm_mid_addr_20260406_1251",        # addr no-promo
            BASE / "mid_lru_study/qmm_mid_addr_20260401_1625",      # addr promote (pre-fix implicit)
            BASE / "lru_mid_new/qmm_mid_pc_20260406_1251",          # PC no-promo
            BASE / "mid_lru_study/qmm_mid_pc_20260401_1625",        # PC promote (pre-fix implicit)
        ],
    },
]


def parse_ipc(path: Path):
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


def best_geomean(sweep_dir: Path):
    """Return (best_thd, best_geomean_pct) over mid_thd1..5."""
    lru_dir = sweep_dir / "lru"
    baselines = {}
    for f in sorted(lru_dir.glob("*/champsim.out")):
        v = parse_ipc(f)
        if v is not None:
            baselines[f.parent.name] = v
    if not baselines:
        return None, None

    best_gm, best_n = -999.0, None
    for n in range(1, 6):
        thd_dir = sweep_dir / f"mid_thd{n}"
        if not thd_dir.is_dir():
            continue
        pcts = []
        for wl, b in baselines.items():
            v = parse_ipc(thd_dir / wl / "champsim.out")
            if v is not None and b > 0:
                pcts.append((v / b - 1.0) * 100.0)
        if not pcts:
            continue
        gm = (np.exp(np.mean(np.log([p / 100 + 1 for p in pcts]))) - 1) * 100
        if gm > best_gm:
            best_gm, best_n = gm, n
    return best_n, best_gm if best_n is not None else None


def main():
    n_suites = len(SUITES)
    n_cfgs   = len(CONFIGS)
    bar_w    = 0.18
    gap      = 0.12          # extra gap between suite groups
    group_w  = n_cfgs * bar_w + gap

    fig, ax = plt.subplots(figsize=(10, 5))

    all_vals = []
    xtick_pos, xtick_lbl = [], []

    for si, suite in enumerate(SUITES):
        x0 = si * group_w
        for ci, ((lbl, color), sweep_dir) in enumerate(zip(CONFIGS, suite["dirs"])):
            n, gm = best_geomean(sweep_dir)
            if gm is None:
                print(f"  WARNING: no data for {suite['label']} / {lbl}", file=sys.stderr)
                gm = 0.0
            else:
                all_vals.append(gm)
                print(f"  {suite['label']:12s}  {lbl:<20s}: best_thd={n}  gm={gm:+.3f}%")

            x = x0 + ci * bar_w
            bar = ax.bar(x, gm, bar_w * 0.88, color=color,
                         edgecolor="black", linewidth=0.5,
                         label=lbl if si == 0 else "_nolegend_")
            if gm != 0.0:
                ax.text(x, gm + 0.03, f"{gm:+.2f}%",
                        ha="center", va="bottom", fontsize=7, rotation=90)

        # Suite label centred under the group
        cx = x0 + (n_cfgs - 1) * bar_w / 2
        xtick_pos.append(cx)
        xtick_lbl.append(suite["label"])

    ax.set_xticks(xtick_pos)
    ax.set_xticklabels(xtick_lbl, fontsize=11)
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--", zorder=1)

    if all_vals:
        lo, hi = min(all_vals), max(all_vals)
        span   = max(hi - lo, 0.5)
        ax.set_ylim(lo - 0.20 * span, hi + 0.30 * span)

    ax.set_ylabel("IPC speedup vs LRU baseline (geomean, %)", fontsize=10)
    ax.set_title(
        "Mid-insertion: addr vs PC key, promote vs no-promote\n"
        "(each bar = geomean at optimal mid_thd for that scenario)",
        fontsize=11,
    )
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f%%"))
    ax.legend(fontsize=9, framealpha=0.85, loc="upper left")
    ax.grid(axis="y", alpha=0.25, linewidth=0.5)

    # Vertical separators between suite groups
    for si in range(1, n_suites):
        ax.axvline(si * group_w - gap / 2, color="gray", linewidth=0.7,
                   linestyle=":", zorder=0)

    fig.tight_layout()

    out = Path("results/plots/mid_lru/addr_vs_pc_summary.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
