#!/usr/bin/env python3
"""plot_size_study.py — effect of cache/TLB size on liveness and DoA/STLB coverage.

Each panel shows one metric vs its causally relevant components only:
  Panel 1 — LLC DoA%   vs  LLC size  (flat, reference) and L2C size  (driver)
  Panel 2 — STLB DoA%  vs  STLB size (flat, reference) and DTLB/ITLB sizes
  Panel 3 — Uncovered% vs  L2C size  (only component that moves it)

Within each panel, x-ticks are the suite names; one dumbbell per suite per
component, showing baseline (dot), halved (▼), and doubled (▲) values.

Usage
-----
    python3 scripts/analysis/plot_size_study.py  \\
        results/size_study/dpc3  results/size_study/google  results/size_study/qmm \\
        [--labels "SPEC (DPC3)" Google Qualcomm]  \\
        [--out results/plots/size_study/]
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
from liveness_utils import parse_liveness_file, parse_correlation_full
from spec_weights import benchmark_weighted_geomean_frac

# ── Component layout ──────────────────────────────────────────────────────────
# Must match the subdirectory names produced by the size sweep
COMPS   = ["llc", "l2c", "stlb", "dtlb", "itlb"]
METRICS = ["llc_doa", "stlb_doa", "doa_match", "precision"]

COMP_COLORS = {
    "llc":  "#4878CF",
    "l2c":  "#E8A87C",
    "stlb": "#6ACC65",
    "dtlb": "#D65F5F",
    "itlb": "#B47CC7",
}

SUITE_COLORS = ["#2C5F8A", "#C46A30", "#2E8B6A"]

# Each panel lists (metric, driver_comps, flat_ref_comps, ylabel, title).
# driver_comps are shown with solid lines and annotated baselines.
# flat_ref_comps are shown with hollow markers only (confirm zero effect visually).
PANELS = [
    ("llc_doa",
     [("l2c", 1)],
     [("llc", 0)],
     "LLC DoA  (Δ percentage points vs baseline)",
     "Cache size → LLC DoA"),
    ("stlb_doa",
     [("dtlb", 3), ("itlb", 4)],
     [("stlb", 2)],
     "STLB DoA  (Δ percentage points vs baseline)",
     "TLB size → STLB DoA"),
    # doa_match = (resident_doa + evicted_doa) / llc_doa: overall recall —
    # what fraction of LLC DoA blocks have any matching STLB DoA event.
    ("doa_match",
     [("dtlb", 3), ("l2c", 1)],
     [("stlb", 2), ("itlb", 4), ("llc", 0)],
     "DoA–STLB match  (Δ percentage points vs baseline)",
     "DoA–STLB coverage"),
    # precision = (resident_doa + evicted_doa) / covered: conditional accuracy —
    # of LLC DoA blocks that have *any* STLB entry, what fraction have a DoA page.
    # Captures the correlation strength between LLC DoA events and STLB DoA events.
    ("precision",
     [("dtlb", 3), ("itlb", 4), ("l2c", 1)],
     [("stlb", 2), ("llc", 0)],
     "DoA correlation  (Δ percentage points vs baseline)",
     "DoA correlation"),
]


# ── Data loading ──────────────────────────────────────────────────────────────

def _geomean_frac(rows, key):
    """Benchmark-weighted geomean of a fractional metric (0–100 scale)."""
    names, vals = [], []
    for wl, v in rows:
        if v is not None and not math.isnan(v):
            names.append(wl)
            vals.append(v)
    if not names:
        return None
    return benchmark_weighted_geomean_frac(names, vals)


def _load_dir(directory: Path):
    """Return geomean metrics for all traces in directory."""
    files = sorted(directory.glob("*/champsim.out"))
    rows_llc_doa, rows_stlb_doa, rows_doa_match, rows_precision = [], [], [], []
    for f in files:
        wl = f.parent.name

        live = parse_liveness_file(f)
        if live:
            llc = live.get("LLC", {})
            tot_llc = llc.get("total", 0)
            if tot_llc > 0:
                rows_llc_doa.append((wl, llc.get("doa", 0) / tot_llc * 100))

            stlb = live.get("cpu0_STLB", {})
            tot_stlb = stlb.get("total", 0)
            if tot_stlb > 0:
                rows_stlb_doa.append((wl, stlb.get("doa", 0) / tot_stlb * 100))

        corr = parse_correlation_full(f)
        if corr is not None and corr["llc_doa"] > 0:
            match_pct = (corr["resident_doa"] + corr["evicted_doa"]) / corr["llc_doa"] * 100
            rows_doa_match.append((wl, match_pct))
            covered = (corr["resident_doa"] + corr["resident_alive"] +
                       corr["evicted_doa"]  + corr["evicted_alive"])
            if covered > 0:
                prec = (corr["resident_doa"] + corr["evicted_doa"]) / covered * 100
                rows_precision.append((wl, prec))

    return {
        "llc_doa":   _geomean_frac(rows_llc_doa,    "llc_doa"),
        "stlb_doa":  _geomean_frac(rows_stlb_doa,   "stlb_doa"),
        "doa_match": _geomean_frac(rows_doa_match,   "doa_match"),
        "precision": _geomean_frac(rows_precision,   "precision"),
    }


def build_data(suite_dirs):
    """Load all size-sweep subdirs for each suite.

    Expected layout (flat, one dir per suite):
        {suite_dir}/baseline/
        {suite_dir}/{comp}_half/
        {suite_dir}/{comp}_double/

    Returns a nested dict:
        data[suite_idx][comp_name] = {
            "base": {metric: float},
            "half": {metric: float} | {},
            "dbl":  {metric: float} | {},
        }
    """
    result = []
    for suite_dir in suite_dirs:
        suite_dir = Path(suite_dir)
        base = _load_dir(suite_dir / "baseline") if (suite_dir / "baseline").is_dir() else {}
        suite = {}
        for comp in COMPS:
            half_dir = suite_dir / f"{comp}_half"
            dbl_dir  = suite_dir / f"{comp}_double"
            half = _load_dir(half_dir) if half_dir.is_dir() else {}
            dbl  = _load_dir(dbl_dir)  if dbl_dir.is_dir()  else {}
            suite[comp] = {"base": base, "half": half, "dbl": dbl}
        result.append(suite)
    return result


# ── Absolute-value line plot ───────────────────────────────────────────────────

def plot_absolute(data, suite_labels, out_dir: Path):
    """Secondary figure: raw % values vs component (one line per suite)."""
    size_order = ["half", "base", "dbl"]
    size_labels_x = ["half", "base", "double"]
    fig, axes = plt.subplots(len(METRICS), len(COMPS),
                             figsize=(3.5 * len(COMPS), 3.5 * len(METRICS)),
                             squeeze=False)

    for mi, metric in enumerate(METRICS):
        for ci, comp in enumerate(COMPS):
            ax = axes[mi][ci]
            for si, (suite, label) in enumerate(zip(data, suite_labels)):
                ys = [suite[comp].get(s, {}).get(metric) for s in size_order]
                ys = [v if v is not None else float("nan") for v in ys]
                ax.plot([0, 1, 2], ys, marker="o",
                        color=SUITE_COLORS[si % len(SUITE_COLORS)],
                        label=label, linewidth=1.4)
            ax.set_xticks([0, 1, 2])
            ax.set_xticklabels(size_labels_x, fontsize=8)
            ax.set_title(f"{metric} / {comp}", fontsize=8)
            ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
            ax.grid(True, linestyle="--", alpha=0.4)
            if ci == 0:
                ax.set_ylabel(metric, fontsize=8)
            if mi == 0 and ci == len(COMPS) - 1:
                ax.legend(fontsize=7, loc="best")

    fig.suptitle("Absolute liveness values vs component size", fontsize=11,
                 fontweight="bold")
    fig.tight_layout()
    out = out_dir / "size_study_abs.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved: {out}")
    plt.close(fig)


# ── Delta dumbbell plot ────────────────────────────────────────────────────────

from matplotlib.transforms import blended_transform_factory


def _draw_panel(ax, panel_metric, driver_comps, flat_comps,
                panel_title, panel_ylabel, data, suite_labels):
    """Draw one panel. driver_comps get full dumbbells; flat_comps get hollow ref dots."""
    n_suites = len(data)
    all_comps = driver_comps + flat_comps
    n_all     = len(all_comps)

    comp_spacing  = n_suites * 0.70 + 1.0
    suite_spacing = 0.58

    x_ticks_suite, suite_labels_x = [], []
    all_delta_vals = []

    for ci, (comp_name, _) in enumerate(all_comps):
        is_driver = ci < len(driver_comps)
        comp_center = ci * comp_spacing
        xs = [comp_center + (si - (n_suites - 1) / 2) * suite_spacing
              for si in range(n_suites)]

        for si, (x, slabel) in enumerate(zip(xs, suite_labels)):
            x_ticks_suite.append(x)
            suite_labels_x.append(slabel)

            comp_data = data[si].get(comp_name, {})
            base_val  = comp_data.get("base", {}).get(panel_metric)
            half_val  = comp_data.get("half", {}).get(panel_metric)
            dbl_val   = comp_data.get("dbl",  {}).get(panel_metric)

            if base_val is None:
                continue

            col = SUITE_COLORS[si % len(SUITE_COLORS)]

            if is_driver:
                # Solid filled baseline dot
                ax.plot(x, 0.0, "o", color=col, ms=7, zorder=5,
                        markeredgecolor="white", markeredgewidth=0.6)

                # Pre-compute deltas so we can anchor the label outside any
                # nearby marker rather than just offsetting from y=0.
                dh_pre = (half_val - base_val) if half_val is not None else 0.0
                dd_pre = (dbl_val  - base_val) if dbl_val  is not None else 0.0

                # Middle suite (si==1) goes below; outer two go above.
                # Anchor at the outer edge of whichever marker is closest to
                # the label so the annotation never overlaps a symbol.
                below = (si == 1)
                if below:
                    anchor_y = min(0.0, dh_pre, dd_pre)
                    y_off, va = -14, "top"
                else:
                    anchor_y = max(0.0, dh_pre, dd_pre)
                    y_off, va = 14, "bottom"
                ax.annotate(f"{base_val:.1f}%", xy=(x, anchor_y),
                            xytext=(0, y_off), textcoords="offset points",
                            ha="center", va=va,
                            fontsize=8.5, color=col, fontweight="bold",
                            bbox=dict(boxstyle="round,pad=0.18", fc="white",
                                      ec=col, linewidth=0.6, alpha=0.9))

                if half_val is not None:
                    dh = half_val - base_val
                    all_delta_vals.append(dh)
                    ax.plot([x, x], [0, dh], color=col, lw=1.4, alpha=0.75)
                    ax.plot(x, dh, "v", color=col, ms=8, zorder=5,
                            markeredgecolor="black", markeredgewidth=0.4)
                if dbl_val is not None:
                    dd = dbl_val - base_val
                    all_delta_vals.append(dd)
                    ax.plot([x, x], [0, dd], color=col, lw=1.4, alpha=0.75,
                            linestyle="--")
                    ax.plot(x, dd, "^", color=col, ms=8, zorder=5,
                            markeredgecolor="black", markeredgewidth=0.4)
            else:
                # Hollow marker only — visually confirms no effect
                ax.plot(x, 0.0, "o", color="none", ms=7, zorder=5,
                        markeredgecolor=col, markeredgewidth=1.2)
                if half_val is not None:
                    dh = half_val - base_val
                    ax.plot(x, dh, "v", color="none", ms=7, zorder=5,
                            markeredgecolor=col, markeredgewidth=1.0)
                if dbl_val is not None:
                    dd = dbl_val - base_val
                    ax.plot(x, dd, "^", color="none", ms=7, zorder=5,
                            markeredgecolor=col, markeredgewidth=1.0)

    ax.axhline(0, color="black", linewidth=0.8, linestyle="--", zorder=2)

    # Separators between component groups
    for ci in range(1, n_all):
        sep = (ci - 0.5) * comp_spacing
        ax.axvline(sep, color="gray", lw=0.5, linestyle=":", zorder=1)

    # Component group name labels centred within each group (inside the plot, at top)
    blend_top = blended_transform_factory(ax.transData, ax.transAxes)
    for ci, (comp_name, _) in enumerate(all_comps):
        comp_center = ci * comp_spacing
        is_driver   = ci < len(driver_comps)
        ax.text(comp_center, 0.97, comp_name.upper(),
                transform=blend_top, ha="center", va="top",
                fontsize=9, fontweight="bold" if is_driver else "normal",
                color="black" if is_driver else "#555555",
                style="italic" if not is_driver else "normal")

    ax.set_xticks(x_ticks_suite)
    ax.set_xticklabels(suite_labels_x, fontsize=7.5, rotation=30, ha="right")
    ax.tick_params(axis="x", length=3, width=0.6, pad=2)

    ax.set_ylabel(panel_ylabel, fontsize=9)
    ax.set_title(panel_title, fontsize=10, fontweight="bold")
    ax.yaxis.grid(True, linestyle="--", color="gray", alpha=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%+.1f%%"))

    # y-limits: extra headroom at top because baseline labels sit above zero line
    if all_delta_vals:
        lo = min(all_delta_vals + [0.0])
        hi = max(all_delta_vals + [0.0])
    else:
        lo, hi = -0.5, 0.5
    span = max(hi - lo, 0.5)
    ax.set_ylim(lo - 0.20 * span, hi + 0.40 * span)


def plot_delta(data, suite_labels, out_dir: Path):
    # 2×2 layout: top row = LLC DoA / STLB DoA; bottom row = DoA coverage / DoA correlation
    fig = plt.figure(figsize=(16, 10))
    gs  = fig.add_gridspec(2, 2,
                           hspace=0.55, wspace=0.22,
                           left=0.07, right=0.98, top=0.90, bottom=0.11)

    axes = [fig.add_subplot(gs[r, c]) for r in range(2) for c in range(2)]

    for ax, (metric, drivers, flats, ylabel, title) in zip(axes, PANELS):
        _draw_panel(ax, metric, drivers, flats, title, ylabel, data, suite_labels)

    # Shared legend at bottom
    leg = []
    for si, label in enumerate(suite_labels):
        col = SUITE_COLORS[si % len(SUITE_COLORS)]
        leg.append(mpatches.Patch(facecolor=col, edgecolor="black",
                                  linewidth=0.5, label=label))
    leg += [
        plt.Line2D([0], [0], marker="v", color="gray", ms=8,
                   markeredgecolor="black", markeredgewidth=0.5,
                   linestyle="none", label="halved"),
        plt.Line2D([0], [0], marker="^", color="gray", ms=8,
                   markeredgecolor="black", markeredgewidth=0.5,
                   linestyle="none", label="doubled"),
        plt.Line2D([0], [0], marker="o", color="gray", ms=7,
                   markeredgecolor="white", markeredgewidth=0.6,
                   linestyle="none", label="baseline (Δ = 0)"),
        plt.Line2D([0], [0], marker="o", color="none", ms=7,
                   markeredgecolor="gray", markeredgewidth=1.2,
                   linestyle="none", label="flat ref (hollow)"),
    ]
    fig.legend(handles=leg, loc="lower center",
               ncol=len(suite_labels) + 4, fontsize=8.5,
               framealpha=0.9, bbox_to_anchor=(0.5, 0.01))

    fig.suptitle(
        "Effect of cache / TLB size on liveness and LLC–STLB DoA correlation\n"
        "Solid = driver component; hollow = flat reference (no effect)",
        fontsize=10, fontweight="bold", y=0.97,
    )

    out = out_dir / "size_study.png"
    fig.savefig(out, dpi=180, bbox_inches="tight")
    print(f"Saved: {out}")
    plt.close(fig)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("result_dirs", nargs="+",
                    help="One result dir per suite; each must contain "
                         "subdirs named llc/base, llc/half, llc/double, "
                         "l2c/base, …, itlb/double")
    ap.add_argument("--labels", nargs="+", default=None,
                    help="Suite labels (default: inferred from dir names)")
    ap.add_argument("--out", default="results/plots/size_study",
                    help="Output directory (default: results/plots/size_study)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    labels = args.labels or [Path(d).name.upper() for d in args.result_dirs]
    if len(labels) != len(args.result_dirs):
        sys.exit("ERROR: --labels count must match result_dirs count")

    print("Loading data …")
    data = build_data(args.result_dirs)

    print("Generating delta (dumbbell) plot …")
    plot_delta(data, labels, out_dir)

    print("Generating absolute line plot …")
    plot_absolute(data, labels, out_dir)


if __name__ == "__main__":
    main()
