#!/usr/bin/env python3
"""plot_stlb_coverage_breakdown.py — LLC DoA / STLB correlation breakdown.

Two-panel figure (stacked vertically):

  Top    — Horizontal stacked bar: of all LLC DoA evictions (summed across all
            traces in each suite), where does the STLB signal come from?
            Five buckets grouped into three regions:
              Live STLB  (page still in STLB at LLC eviction time)
                · page is DoA   → correct, hardware-accessible
                · page is alive → wrong,   hardware-accessible
              Eviction log (page already evicted; logged by software)
                · page was DoA  → correct, NOT hardware-accessible
                · page was alive→ wrong,   NOT hardware-accessible
              No STLB data

  Bottom — Stacked vertical bar: DoA–STLB correlation (= fraction of LLC DoA
            blocks whose page is also DoA in the STLB) per suite, shown as
            per-workload mean, split into
              · solid   = live STLB only          (hardware-feasible)
              · hatched = eviction-log addition   (not hardware-feasible)
            Values are labelled on each segment.

Usage
-----
    python3 scripts/analysis/plot_stlb_coverage_breakdown.py \\
        results/cluster/dpc3_cache_size_20260511_2342/baseline  \\
        results/cluster/google_cache_size_20260511_2342/baseline \\
        results/cluster/qmm_cache_size_20260511_2342/baseline   \\
        [--labels "SPEC (DPC3)" Google Qualcomm]                \\
        [--out results/plots/size_study/stlb_coverage_breakdown.png]
"""

import argparse
import statistics
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from liveness_utils import parse_correlation_full

COLORS = {
    "res_doa":    "#2E8B6A",
    "res_alive":  "#E8A87C",
    "evict_doa":  "#7BBFA8",
    "evict_alive":"#D4B896",
    "uncovered":  "#CCCCCC",
}
HATCHES = {
    "res_doa":    "",
    "res_alive":  "",
    "evict_doa":  "///",
    "evict_alive":"///",
    "uncovered":  "",
}
LABELS = {
    "res_doa":    "In STLB: page is DoA    (correct)",
    "res_alive":  "In STLB: page is alive  (wrong)",
    "evict_doa":  "Eviction log: page was DoA    (correct)",
    "evict_alive":"Eviction log: page was alive  (wrong)",
    "uncovered":  "No STLB record",
}
BUCKETS = ["res_doa", "res_alive", "evict_doa", "evict_alive", "uncovered"]

SUITE_COLORS = ["#4878CF", "#E8963A", "#5BA85A"]


def load_suite(baseline_dir: Path) -> dict:
    """Return aggregate (sum-of-counts) bucket fractions and per-workload
    arithmetic-mean correlation values (live-only and live+eviction-log).

    Arithmetic mean is used because the per-workload distribution spans 0–100%
    with heavy tails; geomean is not appropriate (it collapses near-zero
    workloads and is not additive: mean(live) + mean(evlog) = mean(total)).
    """
    totals = {k: 0 for k in ["llc_doa", "res_doa", "res_alive",
                              "evict_doa", "evict_alive"]}
    wl_live, wl_evlog = [], []   # per-workload values for bottom panel

    for f in sorted(baseline_dir.glob("*/champsim.out")):
        c = parse_correlation_full(f)
        if c is None or c["llc_doa"] == 0:
            continue
        totals["llc_doa"]    += c["llc_doa"]
        totals["res_doa"]    += c["resident_doa"]
        totals["res_alive"]  += c["resident_alive"]
        totals["evict_doa"]  += c["evicted_doa"]
        totals["evict_alive"]+= c["evicted_alive"]
        n = c["llc_doa"]
        wl_live.append(c["resident_doa"] / n * 100)
        wl_evlog.append(c["evicted_doa"]  / n * 100)

    n = totals["llc_doa"]
    if n == 0:
        return {k: 0.0 for k in BUCKETS + ["corr_live", "corr_evlog"]}

    uncov = n - totals["res_doa"] - totals["res_alive"] \
              - totals["evict_doa"] - totals["evict_alive"]

    return {
        # Aggregate fractions for top panel (sum of counts, sums to 100%)
        "res_doa":    totals["res_doa"]    / n * 100,
        "res_alive":  totals["res_alive"]  / n * 100,
        "evict_doa":  totals["evict_doa"]  / n * 100,
        "evict_alive":totals["evict_alive"]/ n * 100,
        "uncovered":  uncov                / n * 100,
        # Per-workload arithmetic mean for bottom panel (additive, so stacking is valid)
        "corr_live":  statistics.mean(wl_live)  if wl_live  else 0.0,
        "corr_evlog": statistics.mean(wl_evlog) if wl_evlog else 0.0,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("baseline_dirs", nargs="+")
    ap.add_argument("--labels", nargs="+", default=None)
    ap.add_argument("--out",
                    default="results/plots/size_study/stlb_coverage_breakdown.png")
    args = ap.parse_args()

    labels = args.labels or [Path(d).parent.name.split("_")[0].upper()
                              for d in args.baseline_dirs]

    suites = []
    for d, label in zip(args.baseline_dirs, labels):
        data = load_suite(Path(d))
        suites.append((label, data))
        total = data["corr_live"] + data["corr_evlog"]
        print(f"{label}: correlation live={data['corr_live']:.1f}%  "
              f"evlog adds {data['corr_evlog']:.1f}%  "
              f"total={total:.1f}%  (per-workload mean)")

    n_suites = len(suites)
    suite_labels = [s[0] for s in suites]

    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(9, 7.5),
        gridspec_kw={"height_ratios": [1, 1.4], "hspace": 0.55},
    )

    # ── Top panel: 5-bucket stacked horizontal bar (aggregate counts) ─────────
    bar_h = 0.50
    ys = list(range(n_suites))

    for yi, (label, data) in enumerate(suites):
        left = 0.0
        for bucket in BUCKETS:
            w = data[bucket]
            if w < 0.5:
                left += w
                continue
            ax_top.barh(yi, w, left=left, height=bar_h,
                        color=COLORS[bucket], hatch=HATCHES[bucket],
                        edgecolor="white", linewidth=0.5)
            ax_top.text(left + w / 2, yi, f"{w:.0f}%",
                        ha="center", va="center", fontsize=8.5,
                        color="black", fontweight="bold")
            left += w

    # Dividers between live / eviction-log / no-data regions
    _, d0 = suites[0]
    live_end = d0["res_doa"] + d0["res_alive"]
    log_end  = live_end + d0["evict_doa"] + d0["evict_alive"]
    for xv in (live_end, log_end):
        ax_top.axvline(xv, color="#555", lw=0.8, ls="--", alpha=0.6)

    top_y = n_suites - 0.08
    for mid, txt in [(live_end / 2,            "Live STLB"),
                     ((live_end + log_end) / 2, "Eviction log"),
                     ((log_end + 100) / 2,      "No data")]:
        ax_top.text(mid, top_y, txt, ha="center", va="bottom",
                    fontsize=8, color="#444", style="italic")

    ax_top.set_yticks(ys)
    ax_top.set_yticklabels(suite_labels, fontsize=11)
    ax_top.set_xlabel("Fraction of LLC DoA evictions, summed across all traces (%)",
                      fontsize=9)
    ax_top.set_xlim(0, 100)
    ax_top.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax_top.xaxis.set_major_locator(mticker.MultipleLocator(20))
    ax_top.tick_params(axis="x", labelsize=9)
    ax_top.set_axisbelow(True)
    ax_top.xaxis.grid(True, linestyle="--", color="gray", alpha=0.4)
    ax_top.set_title(
        "Where does the STLB signal come from?\n"
        "(green = DoA page → contributes to correlation; "
        "orange = alive page → does not)",
        fontsize=9, pad=4)

    legend_patches = [
        mpatches.Patch(facecolor=COLORS[b], hatch=HATCHES[b],
                       edgecolor="gray", linewidth=0.4, label=LABELS[b])
        for b in BUCKETS
    ]
    ax_top.legend(handles=legend_patches, loc="lower center",
                  bbox_to_anchor=(0.5, -0.54), ncol=2, fontsize=7.5,
                  framealpha=0.9)

    # ── Bottom panel: stacked bars — per-workload mean correlation ─────────────
    xs  = np.arange(n_suites)
    bw  = 0.45

    corr_live  = np.array([s[1]["corr_live"]  for s in suites])
    corr_added = np.array([s[1]["corr_evlog"] for s in suites])
    corr_total = corr_live + corr_added

    colors = [SUITE_COLORS[i % len(SUITE_COLORS)] for i in range(n_suites)]

    ax_bot.bar(xs, corr_live, bw, color=colors, alpha=0.9,
               label="Live STLB only")
    ax_bot.bar(xs, corr_added, bw, bottom=corr_live,
               color=colors, hatch="///", edgecolor="white",
               linewidth=0.5, alpha=0.55,
               label="Eviction-log addition")

    for i, (lv, tot, add) in enumerate(zip(corr_live, corr_total, corr_added)):
        x = xs[i]
        # Live-only geomean — inside solid bar, or above it if too small
        if lv >= 3.5:
            ax_bot.text(x, lv / 2, f"{lv:.0f}%",
                        ha="center", va="center", fontsize=9,
                        color="white", fontweight="bold")
        else:
            ax_bot.text(x, lv + 0.8, f"{lv:.0f}%",
                        ha="center", va="bottom", fontsize=8.5,
                        color=colors[i], fontweight="bold")
        # Eviction-log addition — inside hatched band if tall enough
        if add >= 5:
            ax_bot.text(x, lv + add / 2, f"+{add:.0f}pp",
                        ha="center", va="center", fontsize=8.5,
                        color="white", fontweight="bold")
        # Total geomean — boxed above the bar
        ax_bot.text(x, tot + 1.2, f"{tot:.0f}%",
                    ha="center", va="bottom", fontsize=10,
                    color=colors[i], fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.15", fc="white",
                              ec=colors[i], linewidth=0.7, alpha=0.9))

    ax_bot.set_xticks(xs)
    ax_bot.set_xticklabels(suite_labels, fontsize=11)
    ax_bot.set_ylabel("LLC DoA blocks on a DoA page in STLB (%)", fontsize=9)
    ax_bot.set_ylim(0, 90)
    ax_bot.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax_bot.yaxis.set_major_locator(mticker.MultipleLocator(20))
    ax_bot.tick_params(axis="y", labelsize=9)
    ax_bot.set_axisbelow(True)
    ax_bot.yaxis.grid(True, linestyle="--", color="gray", alpha=0.4)

    leg_patches = [
        mpatches.Patch(facecolor="#888",
                       label="Live STLB only"),
        mpatches.Patch(facecolor="#888", hatch="///", edgecolor="white",
                       linewidth=0.5, label="Eviction-log addition"),
    ]
    ax_bot.legend(handles=leg_patches, fontsize=8.5, framealpha=0.9,
                  loc="upper right")
    ax_bot.set_title(
        "DoA–STLB correlation: how much is hardware-accessible?\n"
        "(per-workload mean; solid = live STLB only, total = live + eviction log)",
        fontsize=9, pad=4)

    fig.suptitle("LLC DoA evictions: STLB signal source and DoA–STLB correlation",
                 fontsize=11, fontweight="bold")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
