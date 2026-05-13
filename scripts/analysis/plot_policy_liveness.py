#!/usr/bin/env python3
"""plot_policy_liveness.py — LLC liveness comparison: LRU vs srrip_live.

For each benchmark two stacked bars are drawn side by side:
  left  — LRU baseline   (grayed palette)
  right — srrip_live at the supplied threshold directory

Each bar is split into DoA / Mostly-dead / Mostly-alive fractions.
Benchmarks are sorted by the LRU DoA fraction (descending).
SPEC (DPC3) traces are aggregated to the 20 benchmark level via SimPoint weights.

Usage
-----
    python3 scripts/analysis/plot_policy_liveness.py      \\
        --lru-dirs  dpc3_pol/lru  google_pol/lru  qmm_pol/lru  \\
        --sl-dirs   dpc3_thd/srrip_live_thd16      \\
                    google_thd/srrip_live_thd16     \\
                    qmm_thd/srrip_live_thd16        \\
        --labels    "SPEC (DPC3)"  Google  Qualcomm  \\
        --sl-label  "srrip_live (thd=16)"            \\
        [--out results/plots/policy_liveness.png]
"""

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from liveness_utils import load_suite, parse_liveness_file
from spec_weights import (SPEC_WEIGHTS, aggregate_spec_liveness,
                          benchmark_name, benchmark_weighted_geomean_frac)

CACHE = "LLC"

# Palette: (DoA, mostly-dead, mostly-alive) — LRU in muted grays, srrip_live in colour
LRU_PALETTE = ("#9EB3CC", "#D4B896", "#A8CCBE")   # desaturated blue/peach/teal
SL_PALETTE  = ("#2C5F8A", "#C46A30", "#2E8B6A")   # vivid  blue/orange/teal


def _contrast(hex_color: str) -> str:
    r, g, b = (int(hex_color[i:i+2], 16) / 255 for i in (1, 3, 5))
    return "white" if (0.299 * r + 0.587 * g + 0.114 * b) < 0.55 else "black"


# ── Data loading ───────────────────────────────────────────────────────────────

def _load_rows(directory: Path):
    """Load all champsim.out files in directory → list[(wl, {cache: data})]."""
    files = sorted(directory.glob("*/champsim.out"))
    rows = []
    for f in files:
        data = parse_liveness_file(f)
        if data:
            rows.append((f.parent.name, data))
    return rows


def _aggregate_spec(rows):
    """Collapse SPEC simpoints to benchmark level via SimPoint weights."""
    return aggregate_spec_liveness(rows)


def _bench_liveness(rows, cache):
    """Return list of (label, doa_pct, md_pct, ma_pct) over all rows for a cache."""
    result = []
    for wl, data in rows:
        d = data.get(cache, {})
        tot = d.get("total", 0)
        if tot == 0:
            continue
        result.append((wl,
                        d["doa"]         / tot * 100,
                        d["mostly_dead"] / tot * 100,
                        d["mostly_alive"]/ tot * 100))
    return result


def _suite_geomean(rows, cache):
    """Benchmark-weighted geomean liveness fractions, normalised to 100%."""
    wl_names, doa_r, md_r, ma_r = [], [], [], []
    for wl, data in rows:
        d = data.get(cache, {})
        tot = d.get("total", 0)
        if tot == 0:
            continue
        wl_names.append(wl)
        doa_r.append(d["doa"]         / tot * 100)
        md_r .append(d["mostly_dead"] / tot * 100)
        ma_r .append(d["mostly_alive"]/ tot * 100)
    if not wl_names:
        return None
    gm_doa = benchmark_weighted_geomean_frac(wl_names, doa_r)
    gm_md  = benchmark_weighted_geomean_frac(wl_names, md_r)
    gm_ma  = benchmark_weighted_geomean_frac(wl_names, ma_r)
    s = gm_doa + gm_md + gm_ma
    if s <= 0:
        return None
    return gm_doa / s * 100, gm_md / s * 100, gm_ma / s * 100


# ── Drawing ────────────────────────────────────────────────────────────────────

def _draw_stacked(ax, x, doa, md, ma, width, palette, label_prefix="",
                  annotate=True, ann_fs=8):
    c_doa, c_md, c_ma = palette
    kw = dict(edgecolor="black", linewidth=0.4)
    ax.bar(x, doa,        width, color=c_doa, **kw, label=f"{label_prefix}DoA")
    ax.bar(x, md,  width, bottom=doa,        color=c_md,  **kw, label=f"{label_prefix}Mostly-dead")
    ax.bar(x, ma,  width, bottom=doa + md,   color=c_ma,  **kw, label=f"{label_prefix}Mostly-alive")
    if annotate:
        for val, base, col in [(doa, 0, c_doa), (md, doa, c_md), (ma, doa+md, c_ma)]:
            if val > 6:
                ax.text(x, base + val / 2, f"{val:.0f}%",
                        ha="center", va="center", fontsize=ann_fs,
                        color=_contrast(col), fontweight="bold")


def draw_panel(ax, lru_rows, sl_rows, suite_label, sl_label):
    # Merge by workload name — keep only workloads present in both
    lru_map = {wl: data for wl, data in lru_rows}
    sl_map  = {wl: data for wl, data in sl_rows}
    common  = sorted(set(lru_map) & set(sl_map))

    lru_live = {wl: lru_map[wl] for wl in common}
    sl_live  = {wl: sl_map[wl]  for wl in common}

    # Aggregate SPEC traces → 20 benchmarks
    lru_rows_f = list(lru_live.items())
    sl_rows_f  = list(sl_live.items())
    if SPEC_WEIGHTS and any(re.search(r'-\d+[A-Z]+$', wl) for wl in common):
        lru_rows_f = _aggregate_spec(lru_rows_f)
        sl_rows_f  = _aggregate_spec(sl_rows_f)

    # Extract per-benchmark liveness fractions
    lru_data = _bench_liveness(lru_rows_f, CACHE)
    sl_data  = _bench_liveness(sl_rows_f,  CACHE)

    # Align by benchmark name
    lru_dict = {wl: (d, md, ma) for wl, d, md, ma in lru_data}
    sl_dict  = {wl: (d, md, ma) for wl, d, md, ma in sl_data}
    bm_names = sorted(set(lru_dict) & set(sl_dict),
                      key=lambda b: lru_dict[b][0], reverse=True)

    if not bm_names:
        ax.set_visible(False)
        return

    n       = len(bm_names)
    bar_w   = 0.38
    gap_in  = 0.05   # gap between the two bars of a group
    group_w = 2 * bar_w + gap_in
    gm_gap  = 1.2

    x_centers = np.arange(n) * (group_w + 0.12)
    x_gm      = x_centers[-1] + group_w + gm_gap

    lru_offset = -(bar_w + gap_in) / 2
    sl_offset  =  (bar_w + gap_in) / 2

    ann_fs = max(5.0, 8.0 - n * 0.08)

    for i, bm in enumerate(bm_names):
        x = x_centers[i]
        ld, lmd, lma = lru_dict[bm]
        sd, smd, sma = sl_dict[bm]
        # LRU bar — only draw labels on first iteration to avoid duplicate legend entries
        kw = dict(annotate=(n <= 30), ann_fs=ann_fs)
        _draw_stacked(ax, x + lru_offset, ld, lmd, lma, bar_w, LRU_PALETTE,
                      label_prefix="_" if i > 0 else "LRU — ", **kw)
        _draw_stacked(ax, x + sl_offset,  sd, smd, sma, bar_w, SL_PALETTE,
                      label_prefix="_" if i > 0 else f"{sl_label} — ", **kw)

    # Geomean column
    lru_gm = _suite_geomean(lru_rows_f, CACHE)
    sl_gm  = _suite_geomean(sl_rows_f,  CACHE)
    if lru_gm:
        _draw_stacked(ax, x_gm + lru_offset, *lru_gm, bar_w * 1.1, LRU_PALETTE,
                      label_prefix="_", annotate=True, ann_fs=ann_fs + 1)
    if sl_gm:
        _draw_stacked(ax, x_gm + sl_offset, *sl_gm, bar_w * 1.1, SL_PALETTE,
                      label_prefix="_", annotate=True, ann_fs=ann_fs + 1)

    # Axis decoration
    ax.axvline(x_centers[-1] + group_w + gm_gap / 2,
               color="gray", linewidth=0.8, linestyle=":", zorder=1)

    all_x   = list(x_centers) + [x_gm]
    xlabels = bm_names + ["Geomean"]
    ax.xaxis.set_major_locator(mticker.FixedLocator(all_x))
    ax.xaxis.set_major_formatter(mticker.FixedFormatter(xlabels))
    ax.tick_params(axis="x", which="major", length=3, width=0.6, pad=2)
    ax.tick_params(axis="x", which="minor", length=0)
    ax.minorticks_off()
    for tick, lbl in zip(ax.get_xticklabels(), xlabels):
        tick.set_rotation(40)
        tick.set_ha("right")
        tick.set_fontsize(7.5)
        if lbl == "Geomean":
            tick.set_fontweight("bold")

    ax.set_ylim(0, 108)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.yaxis.set_major_locator(mticker.MultipleLocator(20))
    ax.set_ylabel("LLC evictions (%)", fontsize=9)
    ax.set_title(suite_label, fontsize=12, fontweight="bold")
    ax.set_xlim(-0.7, x_gm + 0.7)
    ax.yaxis.grid(True, linestyle="--", color="gray", alpha=0.4, linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(loc="lower right", fontsize=8, framealpha=0.9, ncol=2)


# ── Main ───────────────────────────────────────────────────────────────────────

import re   # needed for SPEC trace detection above


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lru-dirs", nargs="+", required=True,
                    help="LRU result directories, one per suite")
    ap.add_argument("--sl-dirs",  nargs="+", required=True,
                    help="srrip_live result directories, one per suite")
    ap.add_argument("--labels",   nargs="+", default=None)
    ap.add_argument("--sl-label", default="srrip_live",
                    help="Label for the srrip_live policy in the legend")
    ap.add_argument("--out", default="results/plots/policy_liveness.png")
    args = ap.parse_args()

    if len(args.lru_dirs) != len(args.sl_dirs):
        sys.exit("ERROR: --lru-dirs and --sl-dirs must have the same length")

    n_suites = len(args.lru_dirs)
    labels   = args.labels or [Path(d).parent.name.split("_")[0].upper()
                                for d in args.lru_dirs]

    suites = []
    for lru_d, sl_d, label in zip(args.lru_dirs, args.sl_dirs, labels):
        print(f"Loading '{label}' …")
        lru_rows = _load_rows(Path(lru_d))
        sl_rows  = _load_rows(Path(sl_d))
        print(f"  LRU: {len(lru_rows)} traces   srrip_live: {len(sl_rows)} traces")
        suites.append({"label": label, "lru": lru_rows, "sl": sl_rows})

    # Figure width scales with the largest suite
    max_n = max(len(s["lru"]) for s in suites)
    fig_w = max(14, min(24, max_n * 0.55 + 3))
    fig, axes = plt.subplots(n_suites, 1,
                             figsize=(fig_w, 5.0 * n_suites),
                             sharey=False)
    if n_suites == 1:
        axes = [axes]

    for ax, suite in zip(axes, suites):
        draw_panel(ax, suite["lru"], suite["sl"], suite["label"], args.sl_label)

    # Shared legend patches
    patches = []
    for lbl, pal in [("LRU", LRU_PALETTE), (args.sl_label, SL_PALETTE)]:
        for cat, col in zip(["DoA", "Mostly-dead", "Mostly-alive"], pal):
            patches.append(mpatches.Patch(facecolor=col, edgecolor="black",
                                          linewidth=0.4, label=f"{lbl} — {cat}"))
    fig.legend(handles=patches, loc="lower center",
               ncol=3, fontsize=9, framealpha=0.9,
               bbox_to_anchor=(0.5, 0.0))

    fig.suptitle(
        f"LLC eviction liveness breakdown: LRU vs {args.sl_label}",
        fontsize=11, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0.06, 1, 1])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
