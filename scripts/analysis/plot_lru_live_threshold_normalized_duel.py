#!/usr/bin/env python3
"""DoA threshold sensitivity for LRU-Live WITH SET DUELING (vs plain LRU),
normalised. Same construction as plot_lru_live_threshold_normalized.py, but
built from the dueling rerun of the sweep instead of the older fixed-cfgA
data, to check whether set dueling changes the shape of the curve.

Data sources:
  theta=6      : results/lru_live_theta6_20260624_0126/.../duel/{suite}
  other theta  : results/lru_live_thd_duel_20260627/duel/doa{N}/{suite}
  baseline     : results/baselines/lru/{suite}/{trace}
"""

import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import ConnectionPatch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
from spec_weights import benchmark_weighted_geomean_pct  # noqa: E402

THETA6_DIR = ROOT / "results" / "lru_live_theta6_20260624_0126" / "lru_live_theta6_20260624_0126" / "duel"
DUEL_DIR = ROOT / "results" / "lru_live_thd_duel_20260627" / "duel"

THD = {
    2:  DUEL_DIR / "doa2",
    4:  DUEL_DIR / "doa4",
    6:  THETA6_DIR,
    8:  DUEL_DIR / "doa8",
    16: DUEL_DIR / "doa16",
    20: DUEL_DIR / "doa20",
    25: DUEL_DIR / "doa25",
    30: DUEL_DIR / "doa30",
}
THRESHOLDS = sorted(THD)

SUITES = {"dpc3": "SPEC", "gap": "GAP", "google": "Google",
          "ligra": "Ligra", "ml": "ML", "qmm": "QMM"}
WEIGHTED = {"dpc3"}
COLORS  = {"dpc3": "#8c564b", "gap": "#1f77b4", "google": "#17becf",
           "ligra": "#2ca02c", "ml": "#d62728", "qmm": "#9467bd"}
MARKERS = {"dpc3": "v", "gap": "o", "google": "X",
           "ligra": "^", "ml": "D", "qmm": "P"}


def get_ipc(path):
    try:
        for line in reversed(Path(path).read_text().splitlines()):
            if "CPU 0 cumulative IPC:" in line:
                return float(line.split()[4])
    except Exception:
        pass
    return None


# Break the y-axis across the whole empty band between the two panels
# (-50 to 20): no suite has a normalised value in that range at any theta,
# so nothing real is hidden. Below -50 the bottom panel continues so
# Google's real data (down to -70.0% at theta=2) still renders in full.
GAP_HIGH = 20
GAP_LOW = -50
BOTTOM_MIN = -73


# theta=16 is the best universal compromise across suites: it is the
# threshold at which every suite's worst-case (min over suites) % of peak is
# highest (66.1%, vs. e.g. 61.9% at theta=30 or 36.4% at theta=8).
BEST_OVERALL_THD = 16


def main():
    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, sharex=True, figsize=(7, 4.2),
        gridspec_kw={"height_ratios": [3, 1.4], "hspace": 0.08})
    report = {}

    for suite, label in SUITES.items():
        base_dir = ROOT / "results" / "baselines" / "lru" / suite
        if not base_dir.is_dir():
            continue

        base = {td.name: get_ipc(td / "champsim.out")
                for td in base_dir.iterdir() if td.is_dir()}
        base = {k: v for k, v in base.items() if v}

        common = set(base)
        for thd, thd_dir in THD.items():
            suite_dir = thd_dir / suite
            if suite_dir.is_dir():
                common &= {td.name for td in suite_dir.iterdir() if td.is_dir()}
        common = sorted(common)
        if len(common) < 3:
            continue

        vals = {}
        for thd in THRESHOLDS:
            suite_dir = THD[thd] / suite
            if not suite_dir.is_dir():
                continue
            ratios = {}
            for tr in common:
                live = get_ipc(suite_dir / tr / "champsim.out")
                if live and base[tr] > 0:
                    ratios[tr] = live / base[tr]
            if len(ratios) < 3:
                continue
            if suite in WEIGHTED:
                pct = benchmark_weighted_geomean_pct(ratios)
            else:
                g = math.exp(sum(math.log(r) for r in ratios.values()) / len(ratios))
                pct = (g - 1.0) * 100.0
            vals[thd] = pct

        if not vals:
            continue
        report[suite] = dict(vals)
        peak = max(vals.values())
        if peak <= 0:
            continue

        xs = [thd for thd in THRESHOLDS if thd in vals]
        ys = [vals[thd] / peak * 100.0 for thd in THRESHOLDS if thd in vals]

        # Segments that cross the empty gap between the two panels are drawn
        # dashed: the partial segment within each panel (up to where it
        # crosses that panel's own edge), plus a ConnectionPatch bridging the
        # two exit/entry points through the gap itself, so the dashed line
        # visibly spans the break rather than stopping at one panel's edge.
        # Segments that stay entirely within one panel's range are solid.
        for i in range(len(xs) - 1):
            (x1, y1), (x2, y2) = (xs[i], ys[i]), (xs[i + 1], ys[i + 1])
            crossing = (min(y1, y2) <= GAP_LOW) and (max(y1, y2) >= GAP_HIGH)
            if not crossing:
                for ax in (ax_top, ax_bot):
                    ax.plot([x1, x2], [y1, y2], color=COLORS[suite], linewidth=1.6)
                continue

            # Which endpoint is on top, which is on the bottom.
            if y1 >= y2:
                (x_top_pt, y_top_pt), (x_bot_pt, y_bot_pt) = (x1, y1), (x2, y2)
            else:
                (x_top_pt, y_top_pt), (x_bot_pt, y_bot_pt) = (x2, y2), (x1, y1)

            frac_top = (y_top_pt - GAP_HIGH) / (y_top_pt - y_bot_pt)
            x_at_top_edge = x_top_pt + (x_bot_pt - x_top_pt) * frac_top
            frac_bot = (y_top_pt - GAP_LOW) / (y_top_pt - y_bot_pt)
            x_at_bot_edge = x_top_pt + (x_bot_pt - x_top_pt) * frac_bot

            ax_top.plot([x_top_pt, x_at_top_edge], [y_top_pt, GAP_HIGH],
                        color=COLORS[suite], linestyle="--", linewidth=1.6)
            ax_bot.plot([x_at_bot_edge, x_bot_pt], [GAP_LOW, y_bot_pt],
                        color=COLORS[suite], linestyle="--", linewidth=1.6)
            fig.add_artist(ConnectionPatch(
                xyA=(x_at_top_edge, GAP_HIGH), coordsA=ax_top.transData,
                xyB=(x_at_bot_edge, GAP_LOW), coordsB=ax_bot.transData,
                color=COLORS[suite], linestyle="--", linewidth=1.6))
        for ax in (ax_top, ax_bot):
            ax.plot(xs, ys, color=COLORS[suite], marker=MARKERS[suite],
                    markersize=5, linewidth=0, label=label)

    ax_top.set_ylim(GAP_HIGH, 102)
    ax_bot.set_ylim(BOTTOM_MIN, GAP_LOW)
    for ax in (ax_top, ax_bot):
        ax.set_xticks(THRESHOLDS)
        ax.tick_params(labelsize=9)
        ax.grid(axis="y", linestyle=":", alpha=0.4)
    ax_bot.set_yticks([-50, -60, -70])
    ax_top.spines["bottom"].set_visible(False)
    ax_bot.spines["top"].set_visible(False)
    ax_top.tick_params(labeltop=False, bottom=False)
    ax_bot.xaxis.tick_bottom()
    ax_top.axhline(100, color="black", linestyle="--", linewidth=0.8, alpha=0.5)
    for ax in (ax_top, ax_bot):
        ax.axvline(BEST_OVERALL_THD, color="black", linestyle=":", linewidth=1.2, alpha=0.7, zorder=0)
    ax_top.annotate(r"best overall: $\theta_{\mathrm{doa}}=16$",
                     xy=(BEST_OVERALL_THD, 102), xytext=(BEST_OVERALL_THD + 0.6, 40),
                     fontsize=7.5, ha="left", va="top")

    d = 0.015
    kwargs = dict(transform=ax_top.transAxes, color="black", clip_on=False, linewidth=1)
    ax_top.plot((-d, +d), (-d, +d), **kwargs)
    ax_top.plot((1 - d, 1 + d), (-d, +d), **kwargs)
    kwargs.update(transform=ax_bot.transAxes)
    ax_bot.plot((-d, +d), (1 - 3 * d, 1 + 3 * d), **kwargs)
    ax_bot.plot((1 - d, 1 + d), (1 - 3 * d, 1 + 3 * d), **kwargs)

    ax_bot.set_xlabel(r"DoA threshold $\theta_{\mathrm{doa}}$", fontsize=10)
    fig.text(0.02, 0.55, "% of peak speedup", va="center", rotation="vertical", fontsize=10)
    ax_bot.legend(frameon=True, framealpha=1, edgecolor="black",
                  fontsize=8, ncol=2, loc="lower right")

    fig.tight_layout(rect=(0.03, 0, 1, 1))
    out = ROOT / "results" / "plots" / "lru_live_threshold_normalized_duel.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print("wrote", out)

    print("\nAbsolute geomean speedup vs LRU (%), by suite and theta_doa:")
    for suite, label in SUITES.items():
        if suite not in report:
            continue
        row = "  ".join(f"{t}={report[suite].get(t, float('nan')):+.2f}" for t in THRESHOLDS)
        print(f"  {label:8s} {row}")


if __name__ == "__main__":
    main()
