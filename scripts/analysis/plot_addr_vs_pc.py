#!/usr/bin/env python3
"""plot_addr_vs_pc.py — per-workload bar chart: addr vs PC mid-insertion IPC speedup.

Three panels (one per suite). Each workload gets two bars: addr key at its
optimal mid_thd, and PC key at its optimal mid_thd. A geomean bar is appended
after a small gap.
"""

import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

COLOR_ADDR = "#5B7FA6"   # steel blue
COLOR_PC   = "#E07B4A"   # warm orange

# (suite_label, addr_mid_dir, addr_lru_dir, addr_n, pc_mid_dir, pc_lru_dir, pc_n)
BASE = Path("results")
SUITES = [
    # (suite, addr_mid, addr_lru, addr_n, addr_promo, pc_mid, pc_lru, pc_n, pc_promo)
    (
        "SPEC (DPC3)",
        BASE / "mid_lru_study/dpc3_mid_addr_20260401_2359/mid_thd4",
        BASE / "mid_lru_study/dpc3_mid_addr_20260401_2359/lru",
        4, True,
        BASE / "lru_mid_new/dpc3_mid_pc_20260406_1251/mid_thd4",
        BASE / "lru_mid_new/dpc3_mid_pc_20260406_1251/lru",
        4, False,
    ),
    (
        "Google",
        BASE / "lru_mid_new/google_mid_addr_20260406_1251/mid_thd5",
        BASE / "lru_mid_new/google_mid_addr_20260406_1251/lru",
        5, False,
        BASE / "lru_mid_new/google_mid_pc_20260406_1251/mid_thd4",
        BASE / "lru_mid_new/google_mid_pc_20260406_1251/lru",
        4, False,
    ),
    (
        "Qualcomm",
        BASE / "mid_lru_study/qmm_mid_addr_20260401_1625/mid_thd3",
        BASE / "mid_lru_study/qmm_mid_addr_20260401_1625/lru",
        3, True,
        BASE / "mid_lru_study/qmm_mid_pc_20260401_1625/mid_thd5",
        BASE / "mid_lru_study/qmm_mid_pc_20260401_1625/lru",
        5, True,
    ),
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


def load_speedups(mid_dir: Path, lru_dir: Path):
    """Return {workload: speedup_pct} for workloads with valid data in both dirs."""
    out = {}
    for f in sorted(mid_dir.glob("*/champsim.out")):
        wl = f.parent.name
        v = parse_ipc(f)
        b = parse_ipc(lru_dir / wl / "champsim.out")
        if v is not None and b is not None and b > 0:
            out[wl] = (v / b - 1.0) * 100.0
    return out


def geomean_pct(pcts):
    vals = [v for v in pcts if v is not None]
    if not vals:
        return None
    return (np.exp(np.mean(np.log([v / 100 + 1 for v in vals]))) - 1) * 100


def draw_panel(ax, suite_label, addr_sp, pc_sp, addr_n, addr_promo, pc_n, pc_promo):
    workloads = sorted(set(addr_sp) & set(pc_sp))
    if not workloads:
        ax.set_visible(False)
        return

    n_wl = len(workloads)
    gap  = 1.5
    bar_w = 0.38
    x = np.arange(n_wl)
    x_gm = n_wl + gap

    addr_vals = [addr_sp.get(w) for w in workloads]
    pc_vals   = [pc_sp.get(w)   for w in workloads]
    gm_addr   = geomean_pct([v for v in addr_vals if v is not None])
    gm_pc     = geomean_pct([v for v in pc_vals   if v is not None])

    kw = dict(edgecolor="black", linewidth=0.4)
    addr_tag = f"promote" if addr_promo else "no-promote"
    pc_tag   = f"promote" if pc_promo   else "no-promote"
    ax.bar(x - bar_w / 2, addr_vals, bar_w, color=COLOR_ADDR,
           label=f"addr  N={addr_n}, {addr_tag}", **kw)
    ax.bar(x + bar_w / 2, pc_vals,   bar_w, color=COLOR_PC,
           label=f"PC    N={pc_n}, {pc_tag}",     **kw)
    if gm_addr is not None:
        ax.bar(x_gm - bar_w / 2, gm_addr, bar_w, color=COLOR_ADDR, **kw)
    if gm_pc is not None:
        ax.bar(x_gm + bar_w / 2, gm_pc,   bar_w, color=COLOR_PC,   **kw)

    ax.axhline(0, color="black", linewidth=0.8, linestyle="--", zorder=1)
    ax.axvline(n_wl + gap / 2, color="gray", linewidth=0.8, linestyle=":", zorder=1)

    all_ticks  = list(x) + [x_gm]
    all_labels = workloads + ["Geomean"]
    ax.set_xticks(all_ticks)
    ax.set_xticklabels(all_labels, rotation=40, ha="right", fontsize=6)
    for tick, lbl in zip(ax.get_xticklabels(), all_labels):
        if lbl == "Geomean":
            tick.set_fontweight("bold")
            tick.set_fontsize(8)

    all_vals = [v for v in addr_vals + pc_vals if v is not None]
    if gm_addr is not None: all_vals.append(gm_addr)
    if gm_pc   is not None: all_vals.append(gm_pc)
    if all_vals:
        lo, hi = min(all_vals), max(all_vals)
        span = max(hi - lo, 0.5)
        ax.set_ylim(lo - 0.25 * span, hi + 0.25 * span)

    ax.set_xlim(-0.7, x_gm + 0.7)
    ax.set_ylabel("IPC speedup vs LRU (%)", fontsize=9)
    ax.set_title(f"{suite_label}", fontsize=10)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
    ax.legend(fontsize=8, framealpha=0.85, loc="upper right")
    ax.grid(axis="y", alpha=0.25, linewidth=0.5)


def main():
    fig, axes = plt.subplots(3, 1,
                             figsize=(max(14, 95 * 0.12 + 4), 16),
                             constrained_layout=True)

    for ax, (suite_label, addr_mid, addr_lru, addr_n, addr_promo,
             pc_mid, pc_lru, pc_n, pc_promo) in zip(axes, SUITES):
        addr_sp = load_speedups(addr_mid, addr_lru)
        pc_sp   = load_speedups(pc_mid,   pc_lru)
        if not addr_sp or not pc_sp:
            print(f"  WARNING: no data for {suite_label}", file=sys.stderr)
        draw_panel(ax, suite_label, addr_sp, pc_sp,
                   addr_n, addr_promo, pc_n, pc_promo)

    fig.suptitle(
        "Mid-insertion IPC speedup: per-address vs per-PC key\n"
        "(each bar = one workload at optimal mid_thd · rightmost = geomean)",
        fontsize=12, fontweight="bold",
    )

    out = Path("results/plots/addr_vs_pc_bars.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
