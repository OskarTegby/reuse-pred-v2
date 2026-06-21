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
SRRIP_COLOR      = "#E8A87C"
LRU_MID_COLOR    = "#A67CB9"
THD_VALUES       = [1, 2, 4, 8, 16]


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


def load_suite(thd_dir: Path, pol_dir: Path):
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
        srrip_sp    = _bench_speedup_pct(wl_list, srrip_ipc,   lru_ipc)
        lru_mid_sp  = _bench_speedup_pct(wl_list, lru_mid_ipc, lru_ipc)

        benchmarks[bm] = {
            "optimal_speedup": best_speedup,
            "optimal_thd":     best_thd,
            "srrip_speedup":   srrip_sp,
            "lru_mid_speedup": lru_mid_sp,
            "thd_speedup":     thd_speedup,
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


def draw_panel(ax, benchmarks, suite_label, clip_outliers=True, bm_order=None):
    if bm_order is not None:
        # Use the reference order; keep only benchmarks present in this suite
        bm_names = [b for b in bm_order if b in benchmarks]
        # Append any benchmarks not in the reference (shouldn't happen, but be safe)
        bm_names += [b for b in sorted(benchmarks, key=lambda b: benchmarks[b]["optimal_speedup"], reverse=True)
                     if b not in bm_names]
    else:
        # Sort by srrip_live optimal speedup descending
        bm_names = sorted(benchmarks, key=lambda b: benchmarks[b]["optimal_speedup"], reverse=True)
    n = len(bm_names)

    bar_w     = 0.26
    gap_in    = 0.04
    group_w   = 3 * bar_w + 2 * gap_in
    gm_gap    = 1.5

    sl_vals  = [benchmarks[b]["optimal_speedup"] for b in bm_names]
    sr_vals  = [benchmarks[b]["srrip_speedup"]   for b in bm_names]
    lm_vals  = [benchmarks[b]["lru_mid_speedup"] for b in bm_names]
    sl_gm    = _geomean_of_speedups(sl_vals)
    sr_gm    = _geomean_of_speedups([v for v in sr_vals if v is not None])
    lm_gm    = _geomean_of_speedups([v for v in lm_vals if v is not None])

    x_centers = np.arange(n) * (group_w + 0.10)
    x_gm      = x_centers[-1] + group_w + gm_gap if n > 0 else group_w + gm_gap

    sl_offset = -(bar_w + gap_in)
    sr_offset = 0.0
    lm_offset =  (bar_w + gap_in)

    thd_idx   = {thd: i for i, thd in enumerate(THD_VALUES)}
    bar_annots = []   # (x_centre, value, is_geomean)

    for i, bm in enumerate(bm_names):
        d     = benchmarks[bm]
        x     = x_centers[i]
        color = shade(SRRIP_LIVE_COLOR, thd_idx.get(d["optimal_thd"], 0), len(THD_VALUES))

        ax.bar(x + sl_offset, d["optimal_speedup"], bar_w * 0.92,
               color=color, edgecolor="black", linewidth=0.35, zorder=3)
        bar_annots.append((x + sl_offset, d["optimal_speedup"], False))

        if d["srrip_speedup"] is not None:
            ax.bar(x + sr_offset, d["srrip_speedup"], bar_w * 0.92,
                   color=SRRIP_COLOR, edgecolor="black", linewidth=0.35, zorder=3)
            bar_annots.append((x + sr_offset, d["srrip_speedup"], False))

        if d["lru_mid_speedup"] is not None:
            ax.bar(x + lm_offset, d["lru_mid_speedup"], bar_w * 0.92,
                   color=LRU_MID_COLOR, edgecolor="black", linewidth=0.35, zorder=3)
            bar_annots.append((x + lm_offset, d["lru_mid_speedup"], False))

    # Geomean column
    if sl_gm is not None:
        gm_color = shade(SRRIP_LIVE_COLOR, len(THD_VALUES) - 1, len(THD_VALUES))
        ax.bar(x_gm + sl_offset, sl_gm, bar_w * 0.92,
               color=gm_color, edgecolor="black", linewidth=0.5, zorder=3)
        bar_annots.append((x_gm + sl_offset, sl_gm, True))
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
    if sl_gm is not None:
        all_vals.append(sl_gm)
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
            y_hi   = hi + 0.20 * span   # extra headroom for rotated annotations
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
    ax.set_title(suite_label, fontsize=12, fontweight="bold")
    ax.yaxis.grid(True, linestyle="--", color="gray", alpha=0.55, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.set_xlim(-0.6, x_gm + 0.6)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--thd-dirs",        nargs="+", required=True)
    ap.add_argument("--pol-dirs",        nargs="+", required=True)
    ap.add_argument("--sort-by-thd-dirs", nargs="+", default=None,
                    help="If given, use these dirs to determine benchmark sort order "
                         "(same length as --thd-dirs). Useful to make PC-keyed plots "
                         "match the addr-keyed sort order.")
    ap.add_argument("--sort-by-pol-dirs", nargs="+", default=None)
    ap.add_argument("--labels",   nargs="+", default=None)
    ap.add_argument("--out", default="results/plots/optimal_thd_per_benchmark.png")
    args = ap.parse_args()

    if len(args.thd_dirs) != len(args.pol_dirs):
        sys.exit("ERROR: --thd-dirs and --pol-dirs must match in length")
    if (args.sort_by_thd_dirs is None) != (args.sort_by_pol_dirs is None):
        sys.exit("ERROR: --sort-by-thd-dirs and --sort-by-pol-dirs must be given together")
    if args.sort_by_thd_dirs and len(args.sort_by_thd_dirs) != len(args.thd_dirs):
        sys.exit("ERROR: --sort-by-thd-dirs must have same length as --thd-dirs")

    n_suites = len(args.thd_dirs)
    labels   = args.labels or [Path(d).name.split("_")[0].upper() for d in args.thd_dirs]

    # Load reference sort order (if provided) — one per suite
    ref_orders = []
    if args.sort_by_thd_dirs:
        for ref_thd, ref_pol in zip(args.sort_by_thd_dirs, args.sort_by_pol_dirs):
            print(f"Loading reference sort order from {Path(ref_thd).name} ...")
            ref_bms = load_suite(Path(ref_thd), Path(ref_pol))
            order = sorted(ref_bms, key=lambda b: ref_bms[b]["optimal_speedup"], reverse=True)
            ref_orders.append(order)
    else:
        ref_orders = [None] * len(args.thd_dirs)

    suites = []
    for thd_d, pol_d, label, ref_order in zip(args.thd_dirs, args.pol_dirs, labels, ref_orders):
        print(f"Loading '{label}' ...")
        bms = load_suite(Path(thd_d), Path(pol_d))
        print(f"  {len(bms)} benchmarks")
        for bm, d in bms.items():
            sl = d["optimal_speedup"]
            sr = d["srrip_speedup"]
            sr_str = f"{sr:+.3f}%" if sr is not None else "N/A"
            print(f"  {bm:<35} opt_thd={d['optimal_thd']:<3} "
                  f"sl={sl:+.3f}%  srrip={sr_str}")
        suites.append({"label": label, "benchmarks": bms, "ref_order": ref_order})

    # Figure width: scale with the largest suite
    max_bms = max(len(s["benchmarks"]) for s in suites)
    fig_w   = max(14, min(22, max_bms * 0.45 + 2))
    fig, axes = plt.subplots(n_suites, 1,
                             figsize=(fig_w, 5.5 * n_suites),
                             sharey=False)
    if n_suites == 1:
        axes = [axes]

    for ax, suite in zip(axes, suites):
        # Don't clip SPEC — mcf_s (+16%) and xalancbmk_s (+7.8%) are real peaks
        is_spec = any(k in suite["benchmarks"] for k in ("605.mcf_s", "623.xalancbmk_s"))
        draw_panel(ax, suite["benchmarks"], suite["label"],
                   clip_outliers=not is_spec, bm_order=suite["ref_order"])

    # Legend
    thd_patches = [
        mpatches.Patch(facecolor=shade(SRRIP_LIVE_COLOR, i, len(THD_VALUES)),
                       edgecolor="black", linewidth=0.4,
                       label=f"srrip_live  thd={thd}  (optimal)")
        for i, thd in enumerate(THD_VALUES)
    ]
    srrip_patch   = mpatches.Patch(facecolor=SRRIP_COLOR,   edgecolor="black",
                                   linewidth=0.4, label="SRRIP")
    lru_mid_patch = mpatches.Patch(facecolor=LRU_MID_COLOR, edgecolor="black",
                                   linewidth=0.4, label="lru_mid")
    fig.legend(handles=thd_patches + [srrip_patch, lru_mid_patch],
               loc="lower center", ncol=len(THD_VALUES) + 2, fontsize=9,
               framealpha=0.9, bbox_to_anchor=(0.5, 0.0))

    fig.suptitle(
        "Per-benchmark IPC speedup vs LRU: srrip_live at optimal threshold vs SRRIP",
        fontsize=11, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0.05, 1, 1])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
