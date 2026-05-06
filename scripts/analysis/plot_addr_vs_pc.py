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

from spec_weights import benchmark_weighted_geomean_pct, SPEC_WEIGHTS, benchmark_name
from champsim_utils import parse_ipc

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


MAX_WORKLOADS = 25   # maximum per-workload bars shown


def _iqr_ylim(vals, ref=None, pad=0.08):
    """Tight y-limits via IQR outlier clipping.  ref value is always included."""
    clean = sorted(v for v in vals if v is not None and np.isfinite(v))
    if not clean:
        return None, None
    q1, q3 = np.percentile(clean, 25), np.percentile(clean, 75)
    iqr = q3 - q1
    if iqr > 1e-8:
        inner = [v for v in clean if q1 - 1.5 * iqr <= v <= q3 + 1.5 * iqr]
    else:
        inner = clean
    if ref is not None:
        inner = inner + [ref]
    if not inner:
        inner = clean
    lo, hi = min(inner), max(inner)
    span = max(hi - lo, 1e-8)
    return lo - pad * span, hi + pad * span


def _annotate_clipped(ax, y_lo, y_hi, fmt="%.1f%%"):
    """Write the actual value above/below bars clipped at [y_lo, y_hi] — plain
    horizontal text, no slashes, matching the clean style of Mazumdar Fig 9."""
    span = y_hi - y_lo
    for patch in ax.patches:
        h = patch.get_height()
        if h <= 0:
            continue
        b   = patch.get_y()
        top = b + h
        x   = patch.get_x() + patch.get_width() / 2
        if top > y_hi:
            ax.text(x, y_hi + 0.02 * span, fmt % top,
                    ha="center", va="bottom", fontsize=8,
                    fontweight="bold", color="black", clip_on=False)
        elif b < y_lo:
            ax.text(x, y_lo - 0.02 * span, fmt % b,
                    ha="center", va="top", fontsize=8,
                    fontweight="bold", color="black", clip_on=False)


def _diverse_select(items, feature_fn, k):
    """Greedy farthest-point sampling in normalised feature space.  Returns indices."""
    n = len(items)
    if n <= k:
        return list(range(n))
    vecs = np.array([feature_fn(item) for item in items], dtype=float)
    lo, hi = vecs.min(axis=0), vecs.max(axis=0)
    span = np.where(hi > lo, hi - lo, 1.0)
    v = (vecs - lo) / span
    centroid = v.mean(axis=0)
    selected = [int(np.argmin(np.linalg.norm(v - centroid, axis=1)))]
    min_d = np.full(n, np.inf)
    while len(selected) < k:
        d = np.linalg.norm(v - v[selected[-1]], axis=1)
        min_d = np.minimum(min_d, d)
        min_d[selected] = -1.0
        selected.append(int(np.argmax(min_d)))
    return selected


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


def _aggregate_spec(speedup_by_wl: "dict[str, float]") -> "dict[str, float]":
    """Aggregate SPEC simpoints into parent benchmark speedups (weighted geomean)."""
    groups: dict = {}
    for wl, v in speedup_by_wl.items():
        groups.setdefault(benchmark_name(wl), []).append((wl, v))
    result: dict = {}
    for bm_name, items in groups.items():
        if len(items) == 1 and items[0][0] == bm_name:
            result[bm_name] = items[0][1]
            continue
        # Weighted geomean of (speedup% → ratio → geomean → back to %)
        ratios = [(v / 100.0 + 1.0, SPEC_WEIGHTS.get(wl)) for wl, v in items]
        w_pairs = [(r, w) for r, w in ratios if r > 0 and w is not None]
        if w_pairs and SPEC_WEIGHTS:
            total_w = sum(w for _, w in w_pairs)
            if total_w > 0:
                result[bm_name] = (float(np.exp(
                    sum(w / total_w * np.log(r) for r, w in w_pairs))) - 1) * 100
                continue
        valid = [r for r, _ in ratios if r > 0]
        if valid:
            result[bm_name] = (float(np.exp(np.mean(np.log(valid)))) - 1) * 100
    return result


def geomean_pct(pcts):
    vals = [v for v in pcts if v is not None]
    if not vals:
        return None
    return (np.exp(np.mean(np.log([v / 100 + 1 for v in vals]))) - 1) * 100


def draw_panel(ax, suite_label, addr_sp, pc_sp, addr_n, addr_promo, pc_n, pc_promo):
    # Aggregate SPEC simpoints into parent benchmarks
    addr_sp = _aggregate_spec(addr_sp)
    pc_sp   = _aggregate_spec(pc_sp)

    workloads_all = sorted(set(addr_sp) & set(pc_sp))
    if not workloads_all:
        ax.set_visible(False)
        return

    # Geomean over ALL benchmarks/workloads (before capping)
    gm_addr = benchmark_weighted_geomean_pct(
        {w: addr_sp[w] for w in workloads_all if addr_sp.get(w) is not None})
    gm_pc   = benchmark_weighted_geomean_pct(
        {w: pc_sp[w]   for w in workloads_all if pc_sp.get(w) is not None})

    n_total = len(workloads_all)

    # Select diverse subset: feature = (addr_speedup, pc_speedup)
    if n_total > MAX_WORKLOADS:
        def _fvec(w):
            return [addr_sp.get(w, 0) or 0, pc_sp.get(w, 0) or 0]
        sel = _diverse_select(workloads_all, _fvec, MAX_WORKLOADS)
        workloads = [workloads_all[i] for i in sel]
    else:
        workloads = list(workloads_all)

    # Sort selected by |addr + pc| descending for left-to-right readability
    workloads.sort(key=lambda w: abs((addr_sp.get(w, 0) or 0) +
                                     (pc_sp.get(w, 0)   or 0)), reverse=True)

    n_wl = len(workloads)
    gap  = 1.5
    bar_w = 0.38
    x = np.arange(n_wl)
    x_gm = n_wl + gap

    addr_vals = [addr_sp.get(w) for w in workloads]
    pc_vals   = [pc_sp.get(w)   for w in workloads]

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

    # Annotate every bar with its % value (rotated, above positive / below negative)
    def _label_bar(xi, val, color):
        if val is None or not np.isfinite(val):
            return
        s = f"{val:+.1f}%"
        if val >= 0:
            ax.text(xi, val + 0.04, s, ha="center", va="bottom",
                    fontsize=8, color=color, rotation=90, clip_on=True)
        else:
            ax.text(xi, val - 0.04, s, ha="center", va="top",
                    fontsize=8, color=color, rotation=90, clip_on=True)

    for xi, (av, pv) in enumerate(zip(addr_vals, pc_vals)):
        _label_bar(x[xi] - bar_w / 2, av, COLOR_ADDR)
        _label_bar(x[xi] + bar_w / 2, pv, COLOR_PC)
    _label_bar(x_gm - bar_w / 2, gm_addr, COLOR_ADDR)
    _label_bar(x_gm + bar_w / 2, gm_pc,   COLOR_PC)

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
        span = max(hi - lo, 0.3)
        ax.set_ylim(lo - 0.30 * span, hi + 0.30 * span)

    ax.set_xlim(-0.7, x_gm + 0.7)
    ax.set_ylabel("IPC speedup vs LRU (%)", fontsize=9)
    ax.set_title(
        f"{suite_label}  ({n_wl} most diverse of {n_total}; geomean over all)",
        fontsize=13)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
    ax.legend(fontsize=9, framealpha=0.85, loc="upper left")
    ax.grid(axis="y", alpha=0.25, linewidth=0.5)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/plots/mid_lru/addr_vs_pc_all.png")
    args = ap.parse_args()

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

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
