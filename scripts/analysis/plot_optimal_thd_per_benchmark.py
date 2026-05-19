#!/usr/bin/env python3
"""plot_optimal_thd_per_benchmark.py — per-benchmark IPC speedup at the best threshold.

For each benchmark (SPEC: SimPoint-aggregated; Google/QMM: per-trace), the
srrip_live bar shows the speedup achieved at whichever threshold (1/2/4/8/16)
maximises that benchmark's IPC speedup over LRU.  A SRRIP bar is placed
immediately next to it for comparison.  Bars are sorted by srrip_live speedup
(descending) and a geomean column is appended.

Usage
-----
    python3 scripts/analysis/plot_optimal_thd_per_benchmark.py   \\
        --thd-dirs  dpc3_srrip_live_thd/  google_...  qmm_...    \\
        --pol-dirs  dpc3_pol/             google_...  qmm_...     \\
        --labels    "SPEC (DPC3)"         Google      Qualcomm    \\
        [--out results/plots/optimal_thd_per_benchmark.png]
"""

import argparse
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.colors as mc
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from matplotlib.ticker import FixedFormatter, FixedLocator

sys.path.insert(0, str(Path(__file__).parent))
from champsim_utils import parse_ipc
from spec_weights import SPEC_WEIGHTS, benchmark_name

SRRIP_LIVE_COLOR = "#2E8B6A"
IPV_LIVE_COLOR   = "#4169B8"
SRRIP_COLOR      = "#E8A87C"
LRU_MID_COLOR    = "#A67CB9"
THD_VALUES       = [1, 2, 4, 8, 16]
STLB_POLICIES    = ["stlb_srrip", "stlb_srrip_live", "stlb_lru_mid"]


def _diverse_select(items, fvec, k):
    """Greedily select k items maximising coverage of feature-vector space."""
    n = len(items)
    if n <= k:
        return items
    vecs = np.array([fvec(i) for i in items], dtype=float)
    chosen = []
    # Seed: item closest to global mean
    mean = vecs.mean(axis=0)
    chosen.append(int(np.argmin(np.linalg.norm(vecs - mean, axis=1))))
    dists = np.linalg.norm(vecs - vecs[chosen[0]], axis=1)
    for _ in range(k - 1):
        nxt = int(np.argmax(dists))
        chosen.append(nxt)
        d = np.linalg.norm(vecs - vecs[nxt], axis=1)
        dists = np.minimum(dists, d)
    return [items[i] for i in chosen]


def shade(hex_color, i, n_total):
    rgb = np.array(mc.to_rgb(hex_color))
    t   = i / max(n_total - 1, 1)
    return tuple(np.ones(3) * (1 - t) * 0.55 + rgb * (1 - (1 - t) * 0.55))


def _load_ipc(directory: Path) -> dict:
    files = sorted(directory.glob("*/champsim.out"))
    return {f.parent.name: parse_ipc(f) for f in files}


def _bench_speedup_pct(wl_list, policy_ipc, lru_ipc):
    """SimPoint-weighted geomean IPC speedup (%) within one benchmark."""
    if SPEC_WEIGHTS:
        pairs = [(policy_ipc[wl] / lru_ipc[wl], SPEC_WEIGHTS.get(wl))
                 for wl in wl_list
                 if wl in policy_ipc and wl in lru_ipc and lru_ipc[wl] > 0]
        weighted = [(r, w) for r, w in pairs if w is not None and r > 0]
        if weighted:
            tot = sum(w for _, w in weighted)
            if tot > 0:
                return (math.exp(sum(w / tot * math.log(r) for r, w in weighted)) - 1) * 100
    ratios = [policy_ipc[wl] / lru_ipc[wl]
              for wl in wl_list
              if wl in policy_ipc and wl in lru_ipc and lru_ipc[wl] > 0]
    if not ratios:
        return None
    return (math.exp(sum(math.log(r) for r in ratios) / len(ratios)) - 1) * 100


def _geomean_of_speedups(speedups):
    """Geomean of per-benchmark %-speedup values."""
    ratios = [v / 100 + 1 for v in speedups if v is not None and not math.isnan(v)]
    if not ratios:
        return None
    gm = math.exp(sum(math.log(r) for r in ratios) / len(ratios))
    return (gm - 1) * 100


def load_suite(thd_dir: Path, pol_dir: Path, ipv_thd_dir: Path = None):
    lru_dir = pol_dir / "lru"
    if not lru_dir.is_dir():
        sys.exit(f"ERROR: no lru/ in {pol_dir}")
    lru_ipc = _load_ipc(lru_dir)

    # All threshold IPC: {thd: {wl: ipc}}
    thd_ipc = {}
    sl1 = pol_dir / "srrip_live"
    if not sl1.is_dir():
        sl1 = thd_dir / "srrip_live_thd1"  # PC-keyed sweeps include thd=1 here
    if sl1.is_dir():
        thd_ipc[1] = _load_ipc(sl1)
    for thd in THD_VALUES[1:]:
        sub = thd_dir / f"srrip_live_thd{thd}"
        if sub.is_dir():
            thd_ipc[thd] = _load_ipc(sub)

    # IPV_live threshold IPC (optional)
    ipv_thd_ipc = {}
    if ipv_thd_dir is not None:
        for thd in THD_VALUES:
            sub = ipv_thd_dir / f"ipv_live_thd{thd}"
            if sub.is_dir():
                ipv_thd_ipc[thd] = _load_ipc(sub)

    srrip_ipc   = _load_ipc(pol_dir / "srrip")   if (pol_dir / "srrip").is_dir()   else {}
    lru_mid_ipc = _load_ipc(pol_dir / "lru_mid") if (pol_dir / "lru_mid").is_dir() else {}

    # Group workloads by benchmark
    groups: dict = {}
    for wl in lru_ipc:
        groups.setdefault(benchmark_name(wl), []).append(wl)

    benchmarks = {}
    for bm, wl_list in sorted(groups.items()):
        # Per-threshold speedup for this benchmark
        thd_speedup = {}
        for thd, ipc_map in thd_ipc.items():
            s = _bench_speedup_pct(wl_list, ipc_map, lru_ipc)
            if s is not None:
                thd_speedup[thd] = s

        if not thd_speedup:
            continue
        best_thd     = max(thd_speedup, key=thd_speedup.get)
        best_speedup = thd_speedup[best_thd]

        ipv_speedup = {}
        for thd, ipc_map in ipv_thd_ipc.items():
            s = _bench_speedup_pct(wl_list, ipc_map, lru_ipc)
            if s is not None:
                ipv_speedup[thd] = s
        ipv_best_thd     = max(ipv_speedup, key=ipv_speedup.get) if ipv_speedup else None
        ipv_best_speedup = ipv_speedup[ipv_best_thd] if ipv_best_thd is not None else None

        srrip_sp    = _bench_speedup_pct(wl_list, srrip_ipc,   lru_ipc)
        lru_mid_sp  = _bench_speedup_pct(wl_list, lru_mid_ipc, lru_ipc)

        benchmarks[bm] = {
            "optimal_speedup":  best_speedup,
            "optimal_thd":      best_thd,
            "ipv_live_speedup": ipv_best_speedup,
            "ipv_live_thd":     ipv_best_thd,
            "srrip_speedup":    srrip_sp,
            "lru_mid_speedup":  lru_mid_sp,
            "thd_speedup":      thd_speedup,
            "ipv_thd_speedup":  ipv_speedup,
        }

    return benchmarks


def load_suite_stlb_thd(thd_dir: Path, pol_dir: Path) -> dict:
    """Load STLB threshold sweep — per-benchmark speedup at optimal threshold."""
    lru_dir = pol_dir / "lru"
    if not lru_dir.is_dir():
        sys.exit(f"ERROR: no lru/ in {pol_dir}")
    lru_ipc = _load_ipc(lru_dir)

    stlb_srrip_ipc   = _load_ipc(pol_dir / "stlb_srrip")   if (pol_dir / "stlb_srrip").is_dir()   else {}
    stlb_lru_mid_ipc = _load_ipc(pol_dir / "stlb_lru_mid") if (pol_dir / "stlb_lru_mid").is_dir() else {}

    thd_ipc = {}
    for thd in THD_VALUES:
        sub = thd_dir / f"stlb_srrip_live_thd{thd}"
        if sub.is_dir():
            thd_ipc[thd] = _load_ipc(sub)

    groups: dict = {}
    for wl in lru_ipc:
        groups.setdefault(benchmark_name(wl), []).append(wl)

    benchmarks = {}
    for bm, wl_list in sorted(groups.items()):
        thd_speedup = {}
        for thd, ipc_map in thd_ipc.items():
            s = _bench_speedup_pct(wl_list, ipc_map, lru_ipc)
            if s is not None:
                thd_speedup[thd] = s
        if not thd_speedup:
            continue
        best_thd     = max(thd_speedup, key=thd_speedup.get)
        best_speedup = thd_speedup[best_thd]
        benchmarks[bm] = {
            "optimal_speedup": best_speedup,
            "optimal_thd":     best_thd,
            "srrip_speedup":   _bench_speedup_pct(wl_list, stlb_srrip_ipc,   lru_ipc),
            "lru_mid_speedup": _bench_speedup_pct(wl_list, stlb_lru_mid_ipc, lru_ipc),
            "thd_speedup":     thd_speedup,
        }
    return benchmarks


def load_suite_stlb(stlb_dir: Path) -> dict:
    lru_dir = stlb_dir / "lru"
    if not lru_dir.is_dir():
        sys.exit(f"ERROR: no lru/ in {stlb_dir}")
    lru_ipc = _load_ipc(lru_dir)

    pol_ipc = {}
    for pol in STLB_POLICIES:
        pol_dir = stlb_dir / pol
        pol_ipc[pol] = _load_ipc(pol_dir) if pol_dir.is_dir() else {}

    groups: dict = {}
    for wl in lru_ipc:
        groups.setdefault(benchmark_name(wl), []).append(wl)

    benchmarks = {}
    for bm, wl_list in sorted(groups.items()):
        live_sp = _bench_speedup_pct(wl_list, pol_ipc.get("stlb_srrip_live", {}), lru_ipc)
        if live_sp is None:
            continue
        benchmarks[bm] = {
            "optimal_speedup": live_sp,
            "optimal_thd":     16,   # maps to darkest shade = full SRRIP_LIVE_COLOR
            "srrip_speedup":   _bench_speedup_pct(wl_list, pol_ipc.get("stlb_srrip", {}), lru_ipc),
            "lru_mid_speedup": _bench_speedup_pct(wl_list, pol_ipc.get("stlb_lru_mid", {}), lru_ipc),
            "thd_speedup":     {},
        }
    return benchmarks


def _annotate_clipped(ax, y_lo, y_hi, fmt="%.2f%%"):
    """Annotate bars that are genuinely clipped: positive bars exceeding y_hi,
    or negative bars (b < 0) going below y_lo.  Positive bars whose bottom
    sits at 0 below a raised y_lo are NOT annotated — they are just zoomed in."""
    span = y_hi - y_lo
    for patch in ax.patches:
        h   = patch.get_height()
        if h <= 0:
            continue
        b   = patch.get_y()
        top = b + h
        x   = patch.get_x() + patch.get_width() / 2
        if top > y_hi:
            ax.text(x, y_hi + 0.02 * span, fmt % top,
                    ha="center", va="bottom", fontsize=7,
                    fontweight="bold", color="black", clip_on=False)
        elif b < y_lo and b < 0:   # only truly negative bars
            ax.text(x, y_lo - 0.02 * span, fmt % b,
                    ha="center", va="top", fontsize=7,
                    fontweight="bold", color="black", clip_on=False)


def _iqr_ylim(vals, pad=0.10):
    arr = np.array([v for v in vals if v is not None and not math.isnan(v)])
    if arr.size == 0:
        return -1, 1
    q1, q3 = np.percentile(arr, 25), np.percentile(arr, 75)
    iqr     = q3 - q1
    fence   = 1.5 * iqr
    lo = max(arr.min(), q1 - fence)
    hi = min(arr.max(), q3 + fence)
    span = max(hi - lo, 0.2)
    return lo - pad * span, hi + pad * span


def draw_panel(ax, benchmarks, suite_label, clip_outliers=True, bm_order=None, max_bm=None,
               annotate_individual=None):
    has_ipv = any(d.get("ipv_live_speedup") is not None for d in benchmarks.values())

    if bm_order is not None:
        # Use the reference order; keep only benchmarks present in this suite
        bm_names_all = [b for b in bm_order if b in benchmarks]
        # Append any benchmarks not in the reference (shouldn't happen, but be safe)
        bm_names_all += [b for b in sorted(benchmarks, key=lambda b: benchmarks[b]["optimal_speedup"], reverse=True)
                         if b not in bm_names_all]
    else:
        # Sort by srrip_live optimal speedup descending
        bm_names_all = sorted(benchmarks, key=lambda b: benchmarks[b]["optimal_speedup"], reverse=True)
    n_total = len(bm_names_all)

    # Diversity selection: keep all in geomean but limit what is drawn
    diversity_active = max_bm is not None and max_bm < n_total
    if diversity_active:
        def _fvec(bm):
            d = benchmarks[bm]
            vec = [
                d["optimal_speedup"],
                d.get("ipv_live_speedup") or 0.0,
                d["srrip_speedup"]   if d["srrip_speedup"]   is not None else 0.0,
                d["lru_mid_speedup"] if d["lru_mid_speedup"] is not None else 0.0,
            ]
            return vec
        bm_names = _diverse_select(bm_names_all, _fvec, max_bm)
        # Restore the original sort order within the selected subset
        order_map = {b: i for i, b in enumerate(bm_names_all)}
        bm_names = sorted(bm_names, key=lambda b: order_map[b])
    else:
        bm_names = bm_names_all
    n = len(bm_names)

    n_bars  = 4 if has_ipv else 3
    bar_w   = 0.22 if has_ipv else 0.26
    gap_in  = 0.04
    step    = bar_w + gap_in
    group_w = n_bars * bar_w + (n_bars - 1) * gap_in
    gm_gap  = 1.5

    sl_vals  = [benchmarks[b]["optimal_speedup"] for b in bm_names]
    iv_vals  = [benchmarks[b].get("ipv_live_speedup") for b in bm_names] if has_ipv else []
    sr_vals  = [benchmarks[b]["srrip_speedup"]   for b in bm_names]
    lm_vals  = [benchmarks[b]["lru_mid_speedup"] for b in bm_names]

    # Geomean computed over ALL benchmarks (not just the displayed subset)
    sl_gm = _geomean_of_speedups([benchmarks[b]["optimal_speedup"] for b in bm_names_all])
    iv_gm = _geomean_of_speedups([benchmarks[b].get("ipv_live_speedup") for b in bm_names_all
                                   if benchmarks[b].get("ipv_live_speedup") is not None]) if has_ipv else None
    sr_gm = _geomean_of_speedups([benchmarks[b]["srrip_speedup"]   for b in bm_names_all
                                   if benchmarks[b]["srrip_speedup"] is not None])
    lm_gm = _geomean_of_speedups([benchmarks[b]["lru_mid_speedup"] for b in bm_names_all
                                   if benchmarks[b]["lru_mid_speedup"] is not None])

    x_centers = np.arange(n) * (group_w + 0.10)
    x_gm      = x_centers[-1] + group_w + gm_gap if n > 0 else group_w + gm_gap

    if has_ipv:
        sl_offset = -1.5 * step
        iv_offset = -0.5 * step
        sr_offset =  0.5 * step
        lm_offset =  1.5 * step
    else:
        sl_offset = -step
        sr_offset =  0.0
        lm_offset =  step

    # Auto-disable individual-bar annotations for dense plots (>15 benchmarks with ≥4 bars)
    if annotate_individual is None:
        annotate_individual = not (n > 15 and n_bars >= 4)

    thd_idx   = {thd: i for i, thd in enumerate(THD_VALUES)}
    bar_annots = []   # (x_centre, value, is_geomean)

    for i, bm in enumerate(bm_names):
        d     = benchmarks[bm]
        x     = x_centers[i]
        color = shade(SRRIP_LIVE_COLOR, thd_idx.get(d["optimal_thd"], 0), len(THD_VALUES))

        ax.bar(x + sl_offset, d["optimal_speedup"], bar_w * 0.92,
               color=color, edgecolor="black", linewidth=0.35, zorder=3)
        if annotate_individual:
            bar_annots.append((x + sl_offset, d["optimal_speedup"], False))

        if has_ipv and d.get("ipv_live_speedup") is not None:
            iv_color = shade(IPV_LIVE_COLOR, thd_idx.get(d.get("ipv_live_thd"), 0), len(THD_VALUES))
            ax.bar(x + iv_offset, d["ipv_live_speedup"], bar_w * 0.92,
                   color=iv_color, edgecolor="black", linewidth=0.35, zorder=3)
            if annotate_individual:
                bar_annots.append((x + iv_offset, d["ipv_live_speedup"], False))

        if d["srrip_speedup"] is not None:
            ax.bar(x + sr_offset, d["srrip_speedup"], bar_w * 0.92,
                   color=SRRIP_COLOR, edgecolor="black", linewidth=0.35, zorder=3)
            if annotate_individual:
                bar_annots.append((x + sr_offset, d["srrip_speedup"], False))

        if d["lru_mid_speedup"] is not None:
            ax.bar(x + lm_offset, d["lru_mid_speedup"], bar_w * 0.92,
                   color=LRU_MID_COLOR, edgecolor="black", linewidth=0.35, zorder=3)
            if annotate_individual:
                bar_annots.append((x + lm_offset, d["lru_mid_speedup"], False))

    # Geomean column
    if sl_gm is not None:
        gm_color = shade(SRRIP_LIVE_COLOR, len(THD_VALUES) - 1, len(THD_VALUES))
        ax.bar(x_gm + sl_offset, sl_gm, bar_w * 0.92,
               color=gm_color, edgecolor="black", linewidth=0.5, zorder=3)
        bar_annots.append((x_gm + sl_offset, sl_gm, True))
    if has_ipv and iv_gm is not None:
        iv_gm_color = shade(IPV_LIVE_COLOR, len(THD_VALUES) - 1, len(THD_VALUES))
        ax.bar(x_gm + iv_offset, iv_gm, bar_w * 0.92,
               color=iv_gm_color, edgecolor="black", linewidth=0.5, zorder=3)
        bar_annots.append((x_gm + iv_offset, iv_gm, True))
    if sr_gm is not None:
        ax.bar(x_gm + sr_offset, sr_gm, bar_w * 0.92,
               color=SRRIP_COLOR, edgecolor="black", linewidth=0.5, zorder=3)
        bar_annots.append((x_gm + sr_offset, sr_gm, True))
    if lm_gm is not None:
        ax.bar(x_gm + lm_offset, lm_gm, bar_w * 0.92,
               color=LRU_MID_COLOR, edgecolor="black", linewidth=0.5, zorder=3)
        bar_annots.append((x_gm + lm_offset, lm_gm, True))

    # Axis decoration
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--", zorder=1)
    ax.axvline((x_centers[-1] + group_w + gm_gap / 2) if n > 0 else gm_gap / 2,
               color="gray", linewidth=0.7, linestyle=":", zorder=1)

    # X-axis: FixedLocator/FixedFormatter avoids matplotlib auto-tick interference
    all_x    = list(x_centers) + [x_gm]
    xlabels  = list(bm_names) + ["Geomean"]
    ax.xaxis.set_major_locator(mticker.FixedLocator(all_x))
    ax.xaxis.set_major_formatter(mticker.FixedFormatter(xlabels))
    ax.tick_params(axis="x", which="major", length=3, width=0.6, pad=2)
    ax.tick_params(axis="x", which="minor", length=0)
    ax.minorticks_off()
    for tick, lbl in zip(ax.get_xticklabels(), xlabels):
        tick.set_rotation(45)
        tick.set_ha("right")
        tick.set_fontsize(7.5)
        if lbl == "Geomean":
            tick.set_fontweight("bold")

    # Y-axis limits
    all_vals = sl_vals + [v for v in sr_vals if v is not None] + [v for v in lm_vals if v is not None]
    if has_ipv:
        all_vals += [v for v in iv_vals if v is not None]
    if sl_gm is not None:
        all_vals.append(sl_gm)
    if has_ipv and iv_gm is not None:
        all_vals.append(iv_gm)
    if sr_gm is not None:
        all_vals.append(sr_gm)
    if lm_gm is not None:
        all_vals.append(lm_gm)

    y_lo, y_hi = -1.0, 1.0
    if all_vals:
        clean = [v for v in all_vals if v is not None and not math.isnan(v)]
        if clip_outliers:
            y_lo, y_hi = _iqr_ylim(clean)
            ax.set_ylim(y_lo, y_hi)
            _annotate_clipped(ax, y_lo, y_hi)
        else:
            lo, hi = min(clean), max(clean)
            span   = max(hi - lo, 0.2)
            y_lo   = lo - 0.08 * span
            top_pad = 0.20 if annotate_individual else 0.12
            y_hi   = hi + top_pad * span
            ax.set_ylim(y_lo, y_hi)

    # Bar value annotations (rotated 90°, font scales down with workload count)
    ann_fs = max(4.5, 6.5 - n * 0.03)
    span_y = y_hi - y_lo
    for x_bar, val, is_gm in bar_annots:
        fs = ann_fs + 1.5 if is_gm else ann_fs
        fw = "bold"      if is_gm else "normal"
        if val >= 0:
            y_text = min(val, y_hi) + 0.008 * span_y
            va     = "bottom"
        else:
            y_text = max(val, y_lo) - 0.008 * span_y
            va     = "top"
        ax.text(x_bar, y_text, f"{val:+.1f}%",
                ha="center", va=va, fontsize=fs, fontweight=fw,
                rotation=90, clip_on=False, zorder=5)

    # Y-axis: at most 6 ticks so they don't crowd as "0.00%" lines
    ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=6, steps=[1, 2, 5, 10]))
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f%%"))
    ax.set_ylabel("IPC speedup vs LRU (%)", fontsize=9)
    if diversity_active:
        title_str = f"{suite_label}\n({n} most diverse of {n_total})"
    else:
        title_str = suite_label
    ax.set_title(title_str, fontsize=12, fontweight="bold")
    ax.yaxis.grid(True, linestyle="--", color="gray", alpha=0.55, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.set_xlim(-0.6, x_gm + 0.6)
    return {"sl_gm": sl_gm, "iv_gm": iv_gm, "sr_gm": sr_gm, "lm_gm": lm_gm,
            "n_shown": n, "n_total": n_total}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--thd-dirs",         nargs="+", default=None)
    ap.add_argument("--pol-dirs",         nargs="+", default=None)
    ap.add_argument("--ipv-thd-dirs",    nargs="+", default=None,
                    help="ipv_live threshold sweep dirs (ipv_live_thd{N}/), one per suite")
    ap.add_argument("--stlb-thd-dirs",   nargs="+", default=None,
                    help="stlb_srrip_live threshold sweep dirs, one per suite")
    ap.add_argument("--stlb-pol-dirs",   nargs="+", default=None,
                    help="STLB policy dirs providing lru+stlb_srrip+stlb_lru_mid")
    ap.add_argument("--stlb-dirs",        nargs="+", default=None,
                    help="STLB policy sweep result dirs, one per suite (single-threshold mode)")
    ap.add_argument("--sort-by-thd-dirs", nargs="+", default=None,
                    help="Reference dirs for benchmark sort order (threshold mode only)")
    ap.add_argument("--sort-by-pol-dirs", nargs="+", default=None)
    ap.add_argument("--labels",   nargs="+", default=None)
    ap.add_argument("--max-benchmarks", type=int, default=None,
                    help="Maximum number of diverse benchmarks to display per panel "
                         "(default: show all). Geomean always computed over all benchmarks.")
    ap.add_argument("--out", default=None)
    ap.add_argument("--geomean-out", default=None,
                    help="If given, also save a suite-level geomean summary bar chart here")
    args = ap.parse_args()

    stlb_thd_mode = args.stlb_thd_dirs is not None
    stlb_mode     = args.stlb_dirs is not None

    # ── STLB threshold sweep mode ──────────────────────────────────────────────
    if stlb_thd_mode:
        if not args.stlb_pol_dirs:
            sys.exit("ERROR: --stlb-thd-dirs requires --stlb-pol-dirs")
        if len(args.stlb_thd_dirs) != len(args.stlb_pol_dirs):
            sys.exit("ERROR: --stlb-thd-dirs and --stlb-pol-dirs must have the same length")
        n_suites = len(args.stlb_thd_dirs)
        labels   = args.labels or [Path(d).name.split("_")[0].upper()
                                    for d in args.stlb_thd_dirs]

        suites = []
        for thd_d, pol_d, label in zip(args.stlb_thd_dirs, args.stlb_pol_dirs, labels):
            print(f"Loading '{label}' ...")
            bms = load_suite_stlb_thd(Path(thd_d), Path(pol_d))
            print(f"  {len(bms)} benchmarks")
            for bm, d in bms.items():
                sl = d["optimal_speedup"]
                sr = d["srrip_speedup"]
                sr_str = f"{sr:+.3f}%" if sr is not None else "N/A"
                print(f"  {bm:<35} opt_thd={d['optimal_thd']:<3} "
                      f"sl={sl:+.3f}%  stlb_srrip={sr_str}")
            suites.append({"label": label, "benchmarks": bms, "ref_order": None})

        max_bms_raw = max(len(s["benchmarks"]) for s in suites)
        n_shown_max = min(args.max_benchmarks, max_bms_raw) if args.max_benchmarks else max_bms_raw
        fig_w   = max(14, min(22, n_shown_max * 0.45 + 2))
        fig, axes = plt.subplots(n_suites, 1,
                                 figsize=(fig_w, 5.5 * n_suites), sharey=False)
        if n_suites == 1:
            axes = [axes]

        for ax, suite in zip(axes, suites):
            is_spec = any(k in suite["benchmarks"] for k in ("605.mcf_s", "623.xalancbmk_s"))
            draw_panel(ax, suite["benchmarks"], suite["label"],
                       clip_outliers=not is_spec, bm_order=suite["ref_order"],
                       max_bm=args.max_benchmarks)

        thd_patches = [
            mpatches.Patch(facecolor=shade(SRRIP_LIVE_COLOR, i, len(THD_VALUES)),
                           edgecolor="black", linewidth=0.4,
                           label=f"stlb_srrip_live  thd={thd}  (optimal)")
            for i, thd in enumerate(THD_VALUES)
        ]
        srrip_patch   = mpatches.Patch(facecolor=SRRIP_COLOR,   edgecolor="black",
                                       linewidth=0.4, label="STLB-SRRIP")
        lru_mid_patch = mpatches.Patch(facecolor=LRU_MID_COLOR, edgecolor="black",
                                       linewidth=0.4, label="stlb_lru_mid")
        fig.legend(handles=thd_patches + [srrip_patch, lru_mid_patch],
                   loc="lower center", ncol=len(THD_VALUES) + 2, fontsize=9,
                   framealpha=0.9, bbox_to_anchor=(0.5, 0.0))
        fig.suptitle(
            "Per-benchmark IPC speedup vs LRU: stlb_srrip_live at optimal threshold",
            fontsize=11, fontweight="bold",
        )
        fig.tight_layout(rect=[0, 0.05, 1, 1])

        out = Path(args.out or "results/plots/stlb_thd_per_benchmark.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=180, bbox_inches="tight")
        print(f"\nSaved: {out}")
        return

    # ── STLB policy comparison mode ────────────────────────────────────────────
    if stlb_mode:
        n_suites = len(args.stlb_dirs)
        labels   = args.labels or [Path(d).name.split("_")[0].upper()
                                    for d in args.stlb_dirs]

        suites = []
        for stlb_d, label in zip(args.stlb_dirs, labels):
            print(f"Loading '{label}' ...")
            bms = load_suite_stlb(Path(stlb_d))
            print(f"  {len(bms)} benchmarks")
            for bm, d in bms.items():
                sl = d["optimal_speedup"]
                sr = d["srrip_speedup"]
                sr_str = f"{sr:+.3f}%" if sr is not None else "N/A"
                print(f"  {bm:<35} sl={sl:+.3f}%  stlb_srrip={sr_str}")
            suites.append({"label": label, "benchmarks": bms, "ref_order": None})

        max_bms_raw = max(len(s["benchmarks"]) for s in suites)
        n_shown_max = min(args.max_benchmarks, max_bms_raw) if args.max_benchmarks else max_bms_raw
        fig_w   = max(10, min(22, n_shown_max * 0.45 + 2))
        fig, axes = plt.subplots(n_suites, 1,
                                 figsize=(fig_w, 5.5 * n_suites),
                                 sharey=False)
        if n_suites == 1:
            axes = [axes]

        for ax, suite in zip(axes, suites):
            is_spec = any(k in suite["benchmarks"] for k in ("605.mcf_s", "623.xalancbmk_s"))
            draw_panel(ax, suite["benchmarks"], suite["label"],
                       clip_outliers=not is_spec, bm_order=suite["ref_order"],
                       max_bm=args.max_benchmarks)

        srrip_live_patch = mpatches.Patch(facecolor=SRRIP_LIVE_COLOR, edgecolor="black",
                                          linewidth=0.4, label="STLB-srrip_live")
        srrip_patch      = mpatches.Patch(facecolor=SRRIP_COLOR,      edgecolor="black",
                                          linewidth=0.4, label="STLB-SRRIP")
        lru_mid_patch    = mpatches.Patch(facecolor=LRU_MID_COLOR,    edgecolor="black",
                                          linewidth=0.4, label="STLB-lru_mid")
        fig.legend(handles=[srrip_live_patch, srrip_patch, lru_mid_patch],
                   loc="lower center", ncol=3, fontsize=10,
                   framealpha=0.9, bbox_to_anchor=(0.5, 0.0))
        fig.suptitle(
            "Per-benchmark IPC speedup vs LRU: STLB replacement policy comparison",
            fontsize=11, fontweight="bold",
        )
        fig.tight_layout(rect=[0, 0.05, 1, 1])

        out = Path(args.out or "results/plots/stlb_policy_per_benchmark.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=180, bbox_inches="tight")
        print(f"\nSaved: {out}")
        return

    # ── Threshold sweep mode ───────────────────────────────────────────────────
    if not args.thd_dirs or not args.pol_dirs:
        sys.exit("ERROR: --thd-dirs and --pol-dirs are required (or use --stlb-dirs)")
    if len(args.thd_dirs) != len(args.pol_dirs):
        sys.exit("ERROR: --thd-dirs and --pol-dirs must match in length")
    if args.ipv_thd_dirs and len(args.ipv_thd_dirs) != len(args.thd_dirs):
        sys.exit("ERROR: --ipv-thd-dirs must have same length as --thd-dirs")
    if (args.sort_by_thd_dirs is None) != (args.sort_by_pol_dirs is None):
        sys.exit("ERROR: --sort-by-thd-dirs and --sort-by-pol-dirs must be given together")
    if args.sort_by_thd_dirs and len(args.sort_by_thd_dirs) != len(args.thd_dirs):
        sys.exit("ERROR: --sort-by-thd-dirs must have same length as --thd-dirs")

    has_ipv_global = args.ipv_thd_dirs is not None
    n_suites = len(args.thd_dirs)
    labels   = args.labels or [Path(d).name.split("_")[0].upper() for d in args.thd_dirs]

    ref_orders = []
    if args.sort_by_thd_dirs:
        for ref_thd, ref_pol in zip(args.sort_by_thd_dirs, args.sort_by_pol_dirs):
            print(f"Loading reference sort order from {Path(ref_thd).name} ...")
            ref_bms = load_suite(Path(ref_thd), Path(ref_pol))
            order = sorted(ref_bms, key=lambda b: ref_bms[b]["optimal_speedup"], reverse=True)
            ref_orders.append(order)
    else:
        ref_orders = [None] * len(args.thd_dirs)

    ipv_dirs = args.ipv_thd_dirs or ([None] * n_suites)

    suites = []
    for thd_d, pol_d, ipv_d, label, ref_order in zip(
            args.thd_dirs, args.pol_dirs, ipv_dirs, labels, ref_orders):
        print(f"Loading '{label}' ...")
        bms = load_suite(Path(thd_d), Path(pol_d),
                         ipv_thd_dir=Path(ipv_d) if ipv_d else None)
        print(f"  {len(bms)} benchmarks")
        for bm, d in bms.items():
            sl = d["optimal_speedup"]
            iv = d.get("ipv_live_speedup")
            sr = d["srrip_speedup"]
            iv_str = f"{iv:+.3f}%" if iv is not None else "N/A"
            sr_str = f"{sr:+.3f}%" if sr is not None else "N/A"
            print(f"  {bm:<35} opt_thd={d['optimal_thd']:<3} "
                  f"sl={sl:+.3f}%  ipv={iv_str}  srrip={sr_str}")
        suites.append({"label": label, "benchmarks": bms, "ref_order": ref_order})

    max_bms_raw = max(len(s["benchmarks"]) for s in suites)
    n_shown_max = min(args.max_benchmarks, max_bms_raw) if args.max_benchmarks else max_bms_raw
    n_bars_per_group = 4 if has_ipv_global else 3
    # Each benchmark needs ~0.35 * n_bars inches; floor at 14 for small suites
    fig_w   = max(14, min(36, n_shown_max * 0.35 * n_bars_per_group + 3))
    panel_h = 4.0 if n_suites > 1 else 5.5
    fig, axes = plt.subplots(n_suites, 1,
                             figsize=(fig_w, panel_h * n_suites),
                             sharey=False)
    if n_suites == 1:
        axes = [axes]

    panel_stats = []
    for ax, suite in zip(axes, suites):
        is_spec = any(k in suite["benchmarks"] for k in ("605.mcf_s", "623.xalancbmk_s"))
        stats = draw_panel(ax, suite["benchmarks"], suite["label"],
                           clip_outliers=not is_spec, bm_order=suite["ref_order"],
                           max_bm=args.max_benchmarks)
        panel_stats.append(stats)

    if has_ipv_global:
        legend_handles = [
            mpatches.Patch(facecolor=shade(SRRIP_LIVE_COLOR, len(THD_VALUES) - 1, len(THD_VALUES)),
                           edgecolor="black", linewidth=0.4, label="srrip_live (optimal thd)"),
            mpatches.Patch(facecolor=shade(IPV_LIVE_COLOR, len(THD_VALUES) - 1, len(THD_VALUES)),
                           edgecolor="black", linewidth=0.4, label="ipv_live (optimal thd)"),
            mpatches.Patch(facecolor=SRRIP_COLOR,   edgecolor="black", linewidth=0.4, label="SRRIP"),
            mpatches.Patch(facecolor=LRU_MID_COLOR, edgecolor="black", linewidth=0.4, label="lru_mid"),
        ]
        note = "  (bar shading: light→dark = thd 1→16)"
    else:
        sl_thd_patches = [
            mpatches.Patch(facecolor=shade(SRRIP_LIVE_COLOR, i, len(THD_VALUES)),
                           edgecolor="black", linewidth=0.4,
                           label=f"srrip_live  thd={thd}  (optimal)")
            for i, thd in enumerate(THD_VALUES)
        ]
        legend_handles = sl_thd_patches + [
            mpatches.Patch(facecolor=SRRIP_COLOR,   edgecolor="black", linewidth=0.4, label="SRRIP"),
            mpatches.Patch(facecolor=LRU_MID_COLOR, edgecolor="black", linewidth=0.4, label="lru_mid"),
        ]
        note = ""
    n_legend_cols = len(legend_handles)
    fig.legend(handles=legend_handles,
               loc="lower center", ncol=n_legend_cols, fontsize=9,
               framealpha=0.9, bbox_to_anchor=(0.5, 0.0))

    title_policies = "srrip_live + ipv_live" if has_ipv_global else "srrip_live"
    title_note     = "  (bar shading: light→dark = thd 1→16)" if has_ipv_global else ""
    fig.suptitle(
        f"Per-benchmark IPC speedup vs LRU: {title_policies} at optimal threshold vs SRRIP"
        + title_note,
        fontsize=10, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0.05, 1, 1])

    out = Path(args.out or "results/plots/optimal_thd_per_benchmark.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    print(f"\nSaved: {out}")

    # ── Optional geomean summary chart ────────────────────────────────────────
    if args.geomean_out:
        policies = ["srrip_live"]
        colors   = [shade(SRRIP_LIVE_COLOR, len(THD_VALUES) - 1, len(THD_VALUES))]
        gm_key   = ["sl_gm"]
        if has_ipv_global:
            policies.append("ipv_live")
            colors.append(shade(IPV_LIVE_COLOR, len(THD_VALUES) - 1, len(THD_VALUES)))
            gm_key.append("iv_gm")
        policies.append("SRRIP")
        colors.append(SRRIP_COLOR)
        gm_key.append("sr_gm")

        n_pol    = len(policies)
        gm_bar_w = 0.20
        gm_step  = gm_bar_w + 0.04
        offsets  = [(j - (n_pol - 1) / 2) * gm_step for j in range(n_pol)]

        fig2, ax2 = plt.subplots(figsize=(max(5, n_suites * 2.5), 4))
        for j, (pol, col, key) in enumerate(zip(policies, colors, gm_key)):
            vals = [s[key] for s in panel_stats]
            xs   = np.arange(n_suites) + offsets[j]
            bars = ax2.bar(xs, vals, gm_bar_w * 0.92, color=col,
                           edgecolor="black", linewidth=0.5, label=pol, zorder=3)
            for bar, v in zip(bars, vals):
                if v is not None:
                    ax2.text(bar.get_x() + bar.get_width() / 2,
                             v + 0.02 * abs(v) if v >= 0 else v - 0.02 * abs(v),
                             f"{v:+.2f}%", ha="center",
                             va="bottom" if v >= 0 else "top",
                             fontsize=8, fontweight="bold")

        ax2.axhline(0, color="black", linewidth=0.8, linestyle="--")
        ax2.set_xticks(np.arange(n_suites))
        ax2.set_xticklabels(labels, fontsize=10)
        ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f%%"))
        ax2.set_ylabel("Geomean IPC speedup vs LRU (%)", fontsize=10)
        ax2.set_title("Geomean IPC speedup at optimal threshold", fontsize=11, fontweight="bold")
        ax2.legend(fontsize=9, framealpha=0.9)
        ax2.yaxis.grid(True, linestyle="--", color="gray", alpha=0.55, linewidth=0.8, zorder=0)
        ax2.set_axisbelow(True)
        fig2.tight_layout()

        gm_out = Path(args.geomean_out)
        gm_out.parent.mkdir(parents=True, exist_ok=True)
        fig2.savefig(gm_out, dpi=180, bbox_inches="tight")
        print(f"Saved: {gm_out}")


if __name__ == "__main__":
    main()
