#!/usr/bin/env python3
"""plot_dp_cbpred_study.py — dpPred vs dpPred+cbPred speedup and PFQ analysis.

Three-panel strip chart (matching liveness_corr_strip.png style):
  Panel 1 — IPC speedup vs LRU: dpPred-only and dpPred+cbPred overlaid per suite
  Panel 2 — PFQ hit rate per trace (from lru_pred runs; CBPRED=1 only)
  Panel 3 — LLC DoA-on-DoA-page rate from LRU baseline (existing correlation metric)

Also writes a LaTeX explanation snippet to <out_dir>/explanation.tex, templated
from the computed numbers and shaped by the relationship between PFQ hit rate
and DoA correlation.

Usage
-----
    python3 scripts/analysis/plot_dp_cbpred_study.py \\
        --qmm    results/dp_study/qmm_dp_study_20260428_1143 \\
        --dpc3   results/dp_study/dpc3_dp_study_20260428_1143 \\
        --google results/dp_study/google_dp_study_20260428_1143 \\
        --out    results/plots/dp_cbpred_study/
"""

import argparse
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.ticker as mticker
import matplotlib.pyplot as plt
import numpy as np

from colors import SUITE_COLORS
from spec_weights import benchmark_weighted_geomean_pct
from champsim_utils import parse_ipc

# ── Suite colours — match liveness strip ─────────────────────────────────────
# Order: SPEC → Google → Qualcomm  (matches liveness_corr_strip ordering)
SUITE_ORDER  = ["dpc3",   "google",  "qmm"]
SUITE_LABELS = ["SPEC (DPC3)", "Google", "Qualcomm"]

# Config colours — fixed per config across all suites (Panel 1)
COLOR_DP   = "#4393C3"   # blue  — dpPred only
COLOR_BOTH = "#D6604D"   # red-orange — dpPred + cbPred


def _weighted_geomean_pct(speedups_by_wl: "dict[str, float]") -> float:
    ratios = {wl: v / 100.0 + 1.0 for wl, v in speedups_by_wl.items()}
    return benchmark_weighted_geomean_pct(ratios)


# ── Parsing ───────────────────────────────────────────────────────────────────

def _parse_pfq_hit_rate(path: Path):
    """Return PFQ hit rate (%) computed from 'LLC PFQ PROBES: N  HITS: M'."""
    try:
        for line in path.read_text(errors="replace").splitlines():
            m = re.search(r"LLC PFQ PROBES:\s+(\d+)\s+HITS:\s+(\d+)", line)
            if m:
                probes, hits = int(m.group(1)), int(m.group(2))
                return 100.0 * hits / probes if probes > 0 else 0.0
    except OSError:
        pass
    return None


def _parse_doa_on_page(path: Path):
    """Return LLC DoA-on-DoA-STLB-page rate (%) from lru baseline output."""
    try:
        for line in path.read_text(errors="replace").splitlines():
            m = re.search(
                r"LLC LIVENESS DOA_ON_DOA_STLB_PAGE:\s+\d+\s+\(\s*([0-9.]+)%",
                line,
            )
            if m:
                return float(m.group(1))
    except OSError:
        pass
    return None


def _load_suite(suite_dir: Path) -> dict:
    """Load all per-trace stats from a dp_study suite directory.

    Returns dict with keys:
      ipc_speedup_dp   {wl: %}  — dpPred-only vs LRU
      ipc_speedup_both {wl: %}  — dpPred+cbPred vs LRU
      pfq_hit_rate     {wl: %}  — from lru_pred runs
      doa_on_page      {wl: %}  — from lru baseline runs
    """
    lru_dir   = suite_dir / "lru"
    dp_dir    = suite_dir / "lru_dp_only"
    both_dir  = suite_dir / "lru_pred"

    for d in (lru_dir, dp_dir, both_dir):
        if not d.is_dir():
            print(f"  WARNING: missing {d}", file=sys.stderr)

    baselines: dict = {}
    for f in sorted(lru_dir.glob("*/champsim.out")):
        v = parse_ipc(f)
        if v is not None:
            baselines[f.parent.name] = v

    result: dict = {
        "ipc_speedup_dp":   {},
        "ipc_speedup_both": {},
        "pfq_hit_rate":     {},
        "doa_on_page":      {},
    }

    for wl, base in baselines.items():
        if base <= 0:
            continue

        dp_ipc = parse_ipc(dp_dir / wl / "champsim.out")
        if dp_ipc is not None:
            result["ipc_speedup_dp"][wl] = (dp_ipc / base - 1.0) * 100.0

        both_ipc = parse_ipc(both_dir / wl / "champsim.out")
        if both_ipc is not None:
            result["ipc_speedup_both"][wl] = (both_ipc / base - 1.0) * 100.0

        pfq = _parse_pfq_hit_rate(both_dir / wl / "champsim.out")
        if pfq is not None:
            result["pfq_hit_rate"][wl] = pfq

        corr = _parse_doa_on_page(lru_dir / wl / "champsim.out")
        if corr is not None:
            result["doa_on_page"][wl] = corr

    n = len(baselines)
    print(f"  {n} traces: dp={len(result['ipc_speedup_dp'])} "
          f"both={len(result['ipc_speedup_both'])} "
          f"pfq={len(result['pfq_hit_rate'])} "
          f"corr={len(result['doa_on_page'])}")
    return result


# ── Strip chart helper ────────────────────────────────────────────────────────

def _draw_strip(ax, per_suite_vals: "list[dict]", suite_labels, suite_colors,
                ylabel: str, title: str, rng,
                series2: "list[dict] | None" = None,
                label1: str = "", label2: str = "",
                geomean_fn=None):
    """Draw one strip-chart panel.

    per_suite_vals: list of {wl: value} — one dict per suite (primary series)
    series2:        optional secondary series overlaid at x + 0.18
    """
    xs = np.arange(len(suite_labels))
    off = 0.18  # horizontal offset between two series

    for xi, (vals_dict, color) in enumerate(zip(per_suite_vals, suite_colors)):
        vals = np.array(list(vals_dict.values()))
        if len(vals) == 0:
            continue
        j = rng.uniform(-0.14, 0.14, size=len(vals))
        x_pos = xi - (off / 2 if series2 else 0)
        ax.scatter(x_pos + j, vals, s=18, color=color,
                   edgecolors="none", alpha=0.55, zorder=2,
                   label=label1 if xi == 0 and label1 else None)
        gm = (geomean_fn or _weighted_geomean_pct)(vals_dict)
        ax.plot(x_pos, gm, marker="D", markersize=9, color=color,
                markeredgecolor="black", markeredgewidth=0.8, zorder=4)

    if series2:
        for xi, (vals_dict, color) in enumerate(zip(series2, suite_colors)):
            vals = np.array(list(vals_dict.values()))
            if len(vals) == 0:
                continue
            j = rng.uniform(-0.14, 0.14, size=len(vals))
            x_pos = xi + off / 2
            # Darken the color slightly for the second series
            ax.scatter(x_pos + j, vals, s=18, color=color,
                       edgecolors="none", alpha=0.55, zorder=2, marker="s",
                       label=label2 if xi == 0 and label2 else None)
            gm = (geomean_fn or _weighted_geomean_pct)(vals_dict)
            ax.plot(x_pos, gm, marker="D", markersize=9, color=color,
                    markeredgecolor="white", markeredgewidth=1.2,
                    markerfacecolor=color, zorder=4)

    ax.axhline(0, color="black", linewidth=0.7, linestyle="--", zorder=1)
    ax.set_xticks(xs)
    ax.set_xticklabels(suite_labels, fontsize=11)
    ax.set_xlim(-0.5, len(suite_labels) - 0.5)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.yaxis.grid(True, linestyle="--", color="gray", alpha=0.3,
                  linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)


# ── Explanation text generation ───────────────────────────────────────────────

def _geomean_flat(vals_dict: dict) -> float:
    vals = [v for v in vals_dict.values() if v is not None and np.isfinite(v) and v > -100]
    if not vals:
        return float("nan")
    return float(np.mean(vals))   # mean for non-IPC metrics like PFQ hit rate


def _qual(val, lo, hi) -> str:
    """Qualitative label for a value in [0,100]."""
    if val < lo:
        return "low"
    if val > hi:
        return "high"
    return "moderate"


def _write_explanation(suite_stats: "list[dict]", out_path: Path):
    """Template-fill a LaTeX paragraph from computed per-suite stats."""

    lines = []
    lines.append(
        "% Auto-generated by plot_dp_cbpred_study.py — edit freely\n"
        "\\paragraph{dpPred vs.~dpPred+cbPred and PFQ hit rate.}"
    )

    # Build per-suite sentences
    sentences = []
    for stats, lbl in zip(suite_stats, SUITE_LABELS):
        gm_dp   = stats["gm_dp"]
        gm_both = stats["gm_both"]
        delta   = gm_both - gm_dp
        pfq     = stats["mean_pfq"]
        corr    = stats["mean_corr"]

        if np.isnan(gm_dp) or np.isnan(gm_both):
            continue

        # Describe cbPred's marginal contribution
        if delta > 0.10:
            cb_desc = f"adds a further \\SI{{{delta:.2f}}}{{\\percent}} geomean speedup"
        elif delta > 0.0:
            cb_desc = f"adds only \\SI{{{delta:.2f}}}{{\\percent}} additional speedup"
        else:
            cb_desc = f"provides no additional benefit (\\SI{{{delta:.2f}}}{{\\percent}})"

        pfq_q  = _qual(pfq,  20, 50)
        corr_q = _qual(corr, 20, 50)

        s = (
            f"For {lbl}, dpPred alone achieves a geomean IPC speedup of "
            f"\\SI{{{gm_dp:.2f}}}{{\\percent}} over LRU; cbPred {cb_desc}, "
            f"for a combined total of \\SI{{{gm_both:.2f}}}{{\\percent}}. "
            f"The PFQ hit rate is {pfq_q} at \\SI{{{pfq:.1f}}}{{\\percent}}, "
            f"consistent with the {corr_q} LLC DoA-on-DoA-page correlation of "
            f"\\SI{{{corr:.1f}}}{{\\percent}} seen in the liveness study."
        )
        sentences.append(s)

    lines.append("\n".join(sentences))

    # Overall conclusion
    pfq_vals  = [s["mean_pfq"]  for s in suite_stats if not np.isnan(s["mean_pfq"])]
    corr_vals = [s["mean_corr"] for s in suite_stats if not np.isnan(s["mean_corr"])]
    delta_vals = [s["gm_both"] - s["gm_dp"] for s in suite_stats
                  if not np.isnan(s["gm_dp"]) and not np.isnan(s["gm_both"])]

    if pfq_vals and corr_vals and delta_vals:
        pfq_corr = np.corrcoef(pfq_vals, delta_vals)[0, 1] if len(pfq_vals) > 1 else float("nan")
        if not np.isnan(pfq_corr):
            direction = "positively" if pfq_corr > 0.3 else ("negatively" if pfq_corr < -0.3 else "weakly")
            lines.append(
                f"Across suites, the marginal benefit of cbPred is {direction} correlated "
                f"with the PFQ hit rate ($r={pfq_corr:.2f}$), "
                + ("supporting the hypothesis that cbPred's effectiveness is gated "
                   "by how well dpPred's bypassed-page set predicts which LLC blocks "
                   "will also be dead on arrival."
                   if abs(pfq_corr) > 0.3 else
                   "suggesting that other factors beyond PFQ signal quality "
                   "govern cbPred's marginal contribution on these workloads.")
            )

    tex = "\n\n".join(lines) + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(tex)
    print(f"Explanation written to: {out_path}")
    print(tex)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--qmm",    required=True, metavar="DIR")
    ap.add_argument("--dpc3",   required=True, metavar="DIR")
    ap.add_argument("--google", required=True, metavar="DIR")
    ap.add_argument("--out",    default="results/plots/dp_cbpred_study/",
                    metavar="DIR")
    args = ap.parse_args()

    dirs = {
        "dpc3":   Path(args.dpc3),
        "google": Path(args.google),
        "qmm":    Path(args.qmm),
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load data in SPEC → Google → Qualcomm order
    suite_data = []
    for key in SUITE_ORDER:
        print(f"Loading {key} …")
        suite_data.append(_load_suite(dirs[key]))

    rng = np.random.default_rng(0)

    # ── Figure: 2-row layout — context panels on top, IPC speedup below ─────────
    # Top row:    DoA correlation (left) | PFQ hit rate (right)
    # Bottom row: IPC speedup (full width)
    import matplotlib.gridspec as gridspec
    fig = plt.figure(figsize=(10, 9))
    gs = gridspec.GridSpec(2, 2, figure=fig, height_ratios=[1, 1.1],
                           hspace=0.42, wspace=0.35)
    ax0 = fig.add_subplot(gs[0, 0])   # DoA correlation
    ax1 = fig.add_subplot(gs[0, 1])   # PFQ hit rate
    ax2 = fig.add_subplot(gs[1, :])   # IPC speedup — full width

    xs = np.arange(len(SUITE_LABELS))

    # Top-left: LLC DoA-on-DoA-page rate (liveness correlation)
    ax = ax0
    for xi, (sd, color) in enumerate(zip(suite_data, SUITE_COLORS)):
        vals = np.array(list(sd["doa_on_page"].values()))
        if not len(vals):
            continue
        j = rng.uniform(-0.18, 0.18, size=len(vals))
        ax.scatter(xi + j, vals, s=18, color=color, edgecolors="none",
                   alpha=0.55, zorder=2)
        mean = np.mean(vals)
        ax.plot(xi, mean, marker="D", markersize=9, color=color,
                markeredgecolor="black", markeredgewidth=0.8, zorder=4,
                label=f"{SUITE_LABELS[xi]}  (mean {mean:.1f}%)")

    ax.set_xticks(xs)
    ax.set_xticklabels(SUITE_LABELS, fontsize=11)
    ax.set_xlim(-0.5, len(SUITE_LABELS) - 0.5)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("LLC DoA blocks on a DoA STLB page (%)", fontsize=10)
    ax.set_title("LLC DoA-on-DoA-page rate\n(liveness correlation, LRU baseline)",
                 fontsize=11, fontweight="bold")
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.legend(fontsize=8.5, framealpha=0.85, loc="upper right")
    ax.yaxis.grid(True, linestyle="--", color="gray", alpha=0.3,
                  linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)

    # Top-right: PFQ hit rate
    ax = ax1
    for xi, (sd, color) in enumerate(zip(suite_data, SUITE_COLORS)):
        vals = np.array(list(sd["pfq_hit_rate"].values()))
        if not len(vals):
            continue
        j = rng.uniform(-0.18, 0.18, size=len(vals))
        ax.scatter(xi + j, vals, s=18, color=color, edgecolors="none",
                   alpha=0.55, zorder=2)
        mean = np.mean(vals)
        ax.plot(xi, mean, marker="D", markersize=9, color=color,
                markeredgecolor="black", markeredgewidth=0.8, zorder=4,
                label=f"{SUITE_LABELS[xi]}  (mean {mean:.1f}%)")

    ax.set_xticks(xs)
    ax.set_xticklabels(SUITE_LABELS, fontsize=11)
    ax.set_xlim(-0.5, len(SUITE_LABELS) - 0.5)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("PFQ hit rate (%)", fontsize=10)
    ax.set_title("PFQ hit rate\n(LLC misses on a dpPred-bypassed page)", fontsize=11,
                 fontweight="bold")
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.legend(fontsize=8.5, framealpha=0.85, loc="upper right")
    ax.yaxis.grid(True, linestyle="--", color="gray", alpha=0.3,
                  linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)

    # Bottom: IPC speedup (full width)
    ax = ax2
    off = 0.22
    for xi in range(len(SUITE_LABELS)):
        if xi % 2 == 0:
            ax.axvspan(xi - 0.5, xi + 0.5, color="gray", alpha=0.06, zorder=0)

    Y_LO, Y_HI = -2.0, 4.0
    cfg_series = [
        ("ipc_speedup_dp",   -off, COLOR_DP,   "o", "dpPred only"),
        ("ipc_speedup_both",  off, COLOR_BOTH,  "s", "dpPred + cbPred"),
    ]
    for key, x_off, cfg_color, marker, lbl in cfg_series:
        first = True
        for xi, sd in enumerate(suite_data):
            vals = np.array(list(sd[key].values()))
            if not len(vals):
                continue
            j = rng.uniform(-0.14, 0.14, size=len(vals))
            mask = (vals >= Y_LO) & (vals <= Y_HI)
            ax.scatter(xi + x_off + j[mask], vals[mask], s=18, color=cfg_color,
                       edgecolors="none", alpha=0.6, zorder=2, marker=marker,
                       label=lbl if first else None)
            n_above = int((vals > Y_HI).sum())
            if n_above:
                ax.annotate(
                    f"↑{n_above} (max {vals.max():.1f}%)",
                    xy=(xi + x_off, Y_HI), xytext=(0, 4),
                    textcoords="offset points", ha="center", va="bottom",
                    fontsize=7, color=cfg_color,
                )
            gm = _weighted_geomean_pct(sd[key])
            gm_plot = np.clip(gm, Y_LO, Y_HI)
            ax.plot(xi + x_off, gm_plot, marker="D", markersize=9, color=cfg_color,
                    markeredgecolor="black", markeredgewidth=0.8, zorder=4)
            first = False

    ax.axhline(0, color="black", linewidth=0.7, linestyle="--", zorder=1)
    ax.set_xticks(xs)
    ax.set_xticklabels(SUITE_LABELS, fontsize=11)
    ax.set_xlim(-0.5, len(SUITE_LABELS) - 0.5)
    ax.set_ylim(Y_LO, Y_HI)
    ax.set_ylabel("IPC speedup vs LRU (%)", fontsize=10)
    ax.set_title("IPC speedup\n(dpPred only vs. dpPred+cbPred, pconf=bconf=6)",
                 fontsize=11, fontweight="bold")
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
    ax.legend(fontsize=9, framealpha=0.85, loc="upper right")
    ax.yaxis.grid(True, linestyle="--", color="gray", alpha=0.3,
                  linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)

    fig.suptitle(
        r"dpPred vs.\ dpPred+cbPred: liveness signal, PFQ hit rate, and IPC speedup" + "\n"
        "(dots = individual traces · diamond = geomean or mean)",
        fontsize=11, fontweight="bold", y=1.01,
    )
    fig.savefig(out_dir / "speedup_pfq_correlation.png", dpi=200, bbox_inches="tight")
    print(f"Saved: {out_dir / 'speedup_pfq_correlation.png'}")

    # ── Compute summary stats for explanation ─────────────────────────────────
    suite_stats = []
    for sd in suite_data:
        suite_stats.append({
            "gm_dp":    _weighted_geomean_pct(sd["ipc_speedup_dp"]),
            "gm_both":  _weighted_geomean_pct(sd["ipc_speedup_both"]),
            "mean_pfq": _geomean_flat(sd["pfq_hit_rate"]),
            "mean_corr":_geomean_flat(sd["doa_on_page"]),
        })

    _write_explanation(suite_stats, out_dir / "explanation.tex")


if __name__ == "__main__":
    main()
