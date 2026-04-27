#!/usr/bin/env python3
"""plot_scope_comparison.py — IPC speedup vs mid_thd across three scopes.

Produces a bar-chart figure in the style of the original mid_thd plot:
bars per threshold N, grouped by scope, one panel per suite.

Single-column mode (one key type):
    python3 scripts/analysis/plot_scope_comparison.py \\
        --stlb  <qmm> <dpc3> <google> \\
        --llc   <qmm> <dpc3> <google> \\
        --both  <qmm> <dpc3> <google> \\
        --suite-labels Qualcomm "SPEC (DPC3)" Google \\
        --max-n 10 \\
        --out results/plots/scope_comparison/addr.png

Two-column combined mode (addr | PC in one figure):
    python3 scripts/analysis/plot_scope_comparison.py \\
        --stlb  <qmm> <dpc3> <google> \\
        --llc   <qmm> <dpc3> <google> \\
        --both  <qmm> <dpc3> <google> \\
        --stlb2 <qmm> <dpc3> <google> \\
        --llc2  <qmm> <dpc3> <google> \\
        --both2 <qmm> <dpc3> <google> \\
        --row-labels "addr-keyed" "PC-keyed" \\
        --suite-labels Qualcomm "SPEC (DPC3)" Google \\
        --max-n 10 \\
        --out results/plots/scope_comparison/combined.png

Layout: rows = benchmark suites, columns = key types (addr | PC).
Each cell: bars grouped by scope (STLB only / LLC only / LLC+STLB),
shaded by N value.

Each directory must contain lru/ and mid_thd1/ .. mid_thdN/ subdirs as
produced by sweep_mid.sh.  A scope can be omitted (e.g. --both is optional).
"""

import argparse
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.colors as mc
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.transforms as mtrans
import numpy as np

# ── Simpoint weights ──────────────────────────────────────────────────────────

_DEFAULT_WEIGHTS_DIR = (
    Path(__file__).parents[2] / ".." / "ChampSim-dev" / "trace-files" / "SPEC2006_weights"
).resolve()


def _load_spec_weights(weights_dir: Path) -> "dict[str, float]":
    result: dict = {}
    if not weights_dir.is_dir():
        return result
    for bm_dir in sorted(weights_dir.iterdir()):
        if not bm_dir.is_dir():
            continue
        w_file = bm_dir / "weights.out"
        s_file = bm_dir / "simpoints.out"
        if not (w_file.exists() and s_file.exists()):
            continue
        w_vals = [float(x) for x in w_file.read_text().split()]
        s_ids  = [int(x)   for x in s_file.read_text().split()]
        for sp_id, w in zip(s_ids, w_vals):
            result[f"{bm_dir.name}-{sp_id}B"] = w
    return result


def _benchmark_name(wl: str) -> str:
    m = re.match(r'^(.+)-\d+[A-Z]+$', wl)
    return m.group(1) if m else wl


_SPEC_WEIGHTS = _load_spec_weights(_DEFAULT_WEIGHTS_DIR)


def _weighted_geomean_pct(ratios_by_wl: "dict[str, float]") -> float:
    groups: dict = {}
    for wl, r in ratios_by_wl.items():
        groups.setdefault(_benchmark_name(wl), []).append(wl)
    per_bench = []
    for wl_list in groups.values():
        if _SPEC_WEIGHTS:
            pairs = [(ratios_by_wl[wl], _SPEC_WEIGHTS.get(wl)) for wl in wl_list]
            if any(w is not None for _, w in pairs):
                pairs = [(r, w) for r, w in pairs if w is not None and r > 0]
                total_w = sum(w for _, w in pairs)
                if total_w > 0:
                    per_bench.append(
                        float(np.exp(sum((w / total_w) * np.log(r) for r, w in pairs))))
                    continue
        vals = [ratios_by_wl[wl] for wl in wl_list if ratios_by_wl[wl] > 0]
        if vals:
            per_bench.append(float(np.exp(np.mean(np.log(vals)))))
    if not per_bench:
        return float("nan")
    return (float(np.exp(np.mean(np.log([r for r in per_bench if r > 0])))) - 1) * 100


# ── Parsing ───────────────────────────────────────────────────────────────────

def _parse_ipc(path: Path):
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


def _compute_speedups(sweep_dir: Path, max_n: int) -> "list[float]":
    """Return list of geomean IPC speedup (%) for N=1..max_n."""
    lru_dir = sweep_dir / "lru"
    baselines: dict = {}
    for f in sorted(lru_dir.glob("*/champsim.out")):
        v = _parse_ipc(f)
        if v is not None:
            baselines[f.parent.name] = v
    if not baselines:
        print(f"  WARNING: no baseline data in {lru_dir}", file=sys.stderr)
        return [float("nan")] * max_n

    result = []
    for n in range(1, max_n + 1):
        thd_dir = sweep_dir / f"mid_thd{n}"
        if not thd_dir.is_dir():
            result.append(float("nan"))
            continue
        ratios: dict = {}
        for wl, b in baselines.items():
            v = _parse_ipc(thd_dir / wl / "champsim.out")
            if v is not None and b > 0:
                ratios[wl] = v / b
        result.append(_weighted_geomean_pct(ratios))
    return result


# ── Styling ───────────────────────────────────────────────────────────────────

SCOPES = [
    ("STLB only",  "#2166ac"),   # blue
    ("LLC only",   "#d6604d"),   # red
    ("LLC + STLB", "#1a9850"),   # green
]

BAR_W     = 0.10   # width of each individual bar
GROUP_GAP = 0.55   # extra whitespace between scope groups


def _shade(hex_color: str, n: int, n_max: int) -> tuple:
    """Interpolate from near-white (n=1) to the full colour (n=n_max)."""
    rgb = np.array(mc.to_rgb(hex_color))
    t = (n - 1) / max(n_max - 1, 1)   # 0 → 1
    white = np.ones(3)
    return tuple(white * (1 - t) * 0.55 + rgb * (1 - (1 - t) * 0.55))


# ── Per-cell plotting ─────────────────────────────────────────────────────────

def _plot_cell(ax, scope_dirs_for_cell, max_n):
    """Fill one axes panel.

    scope_dirs_for_cell: list of (scope_idx, single_dir)
    """
    ns = list(range(1, max_n + 1))
    all_vals = []
    minor_pos, minor_lbl = [], []
    major_pos, major_lbl = [], []

    for si, (scope_idx, d) in enumerate(scope_dirs_for_cell):
        scope_label, scope_color = SCOPES[scope_idx]
        g_start = si * (max_n * BAR_W + GROUP_GAP)

        speedups = _compute_speedups(d, max_n)

        for ni, (n, gm) in enumerate(zip(ns, speedups)):
            x = g_start + ni * BAR_W
            minor_pos.append(x)
            minor_lbl.append(str(n))
            if np.isnan(gm):
                print(f"  WARNING: no data — {scope_label} / N={n}",
                      file=sys.stderr)
                continue
            c = _shade(scope_color, n, max_n)
            ax.bar(x, gm, BAR_W * 0.88, color=c, edgecolor="black",
                   linewidth=0.4, zorder=3)
            all_vals.append(gm)

        major_pos.append(g_start + (max_n - 1) * BAR_W / 2)
        major_lbl.append(scope_label)

    ax.axhline(0, color="black", linewidth=0.8, linestyle="--", zorder=1)

    from matplotlib.ticker import FixedLocator, FixedFormatter
    ax.xaxis.set_minor_locator(FixedLocator(minor_pos))
    ax.xaxis.set_minor_formatter(FixedFormatter(minor_lbl))
    ax.tick_params(axis="x", which="minor", length=3, width=0.6,
                   labelsize=6, pad=2)
    ax.xaxis.set_major_locator(FixedLocator([]))
    ax.tick_params(axis="x", which="major", length=0)

    blend = mtrans.blended_transform_factory(ax.transData, ax.transAxes)
    for cx, lbl in zip(major_pos, major_lbl):
        ax.text(cx, -0.28, lbl, transform=blend,
                ha="center", va="top", fontsize=8.5)

    ax.set_xlabel("N  (mid-insertion threshold)", fontsize=9, labelpad=28)
    ax.set_ylabel("IPC speedup vs LRU (geomean, %)", fontsize=9)
    ax.yaxis.grid(True, linestyle="--", color="gray", alpha=0.55,
                  linewidth=0.9, zorder=0)
    ax.set_axisbelow(True)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f%%"))

    if all_vals:
        lo, hi = min(all_vals), max(all_vals)
        span = max(hi - lo, 0.3)
        ax.set_ylim(lo - 0.20 * span, hi + 0.25 * span)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Column 1 scopes (addr-keyed)
    ap.add_argument("--stlb",  nargs="+", metavar="DIR",
                    help="STLB-only dirs for col 1, one per suite")
    ap.add_argument("--llc",   nargs="+", metavar="DIR",
                    help="LLC-only dirs for col 1, one per suite")
    ap.add_argument("--both",  nargs="+", metavar="DIR",
                    help="LLC+STLB dirs for col 1, one per suite")
    # Column 2 scopes (PC-keyed, optional — triggers 2-column combined layout)
    ap.add_argument("--stlb2", nargs="+", metavar="DIR",
                    help="STLB-only dirs for col 2, one per suite")
    ap.add_argument("--llc2",  nargs="+", metavar="DIR",
                    help="LLC-only dirs for col 2, one per suite")
    ap.add_argument("--both2", nargs="+", metavar="DIR",
                    help="LLC+STLB dirs for col 2, one per suite")
    ap.add_argument("--row-labels", nargs="+", default=["addr-keyed", "PC-keyed"],
                    metavar="LABEL", dest="col_labels",
                    help="Column header labels (one per key type)")
    ap.add_argument("--suite-labels", nargs="+", default=["QMM", "SPEC", "Google"],
                    metavar="LABEL")
    ap.add_argument("--max-n", type=int, default=10, dest="max_n")
    ap.add_argument("--out", default="results/plots/scope_comparison/combined.png")
    args = ap.parse_args()

    n_suites = len(args.suite_labels)
    two_cols = any(x is not None for x in [args.stlb2, args.llc2, args.both2])
    n_cols_layout = 2 if two_cols else 1

    def _build_scope_dirs(stlb, llc, both):
        sd = []
        if stlb:
            assert len(stlb) == n_suites, "--stlb must have one dir per suite"
            sd.append((0, [Path(d) for d in stlb]))
        if llc:
            assert len(llc) == n_suites, "--llc must have one dir per suite"
            sd.append((1, [Path(d) for d in llc]))
        if both:
            assert len(both) == n_suites, "--both must have one dir per suite"
            sd.append((2, [Path(d) for d in both]))
        return sd

    col1_scopes = _build_scope_dirs(args.stlb, args.llc, args.both)
    if not col1_scopes:
        sys.exit("ERROR: at least one of --stlb, --llc, --both is required")

    if two_cols:
        col2_scopes = _build_scope_dirs(args.stlb2, args.llc2, args.both2)
        if not col2_scopes:
            sys.exit("ERROR: at least one of --stlb2, --llc2, --both2 required when using two-column mode")

    # ── Figure layout (rows = suites, cols = key types) ───────────────────────
    panel_w = 5.5
    panel_h = 4.5
    fig, axes = plt.subplots(
        n_suites, n_cols_layout,
        figsize=(panel_w * n_cols_layout, panel_h * n_suites),
        sharey=False,
        squeeze=False,
    )

    for si in range(n_suites):
        cell_scopes_col1 = [(sidx, dirs[si]) for sidx, dirs in col1_scopes]
        _plot_cell(axes[si, 0], cell_scopes_col1, args.max_n)

        if two_cols:
            cell_scopes_col2 = [(sidx, dirs[si]) for sidx, dirs in col2_scopes]
            _plot_cell(axes[si, 1], cell_scopes_col2, args.max_n)

    # Column headers on the top row only
    if two_cols and len(args.col_labels) >= 2:
        for ki, lbl in enumerate(args.col_labels[:n_cols_layout]):
            axes[0, ki].set_title(lbl, fontsize=12, fontweight="bold", pad=6)
    elif not two_cols and args.col_labels:
        axes[0, 0].set_title(args.col_labels[0], fontsize=12, fontweight="bold", pad=6)

    # Suite labels on the left margin of each row
    for si, suite_label in enumerate(args.suite_labels):
        axes[si, 0].annotate(
            suite_label,
            xy=(0, 0.5), xycoords="axes fraction",
            xytext=(-0.18, 0.5), textcoords="axes fraction",
            ha="right", va="center",
            fontsize=11, fontweight="bold",
            rotation=90,
        )

    # ── Shared legend ─────────────────────────────────────────────────────────
    scope_patches = [
        mpatches.Patch(facecolor=color, edgecolor="black", linewidth=0.5,
                       label=label)
        for label, color in SCOPES
    ]

    fig.legend(
        handles=scope_patches,
        loc="lower center",
        ncol=len(scope_patches),
        fontsize=9,
        framealpha=0.9,
        bbox_to_anchor=(0.5, -0.04),
        columnspacing=1.2,
        handlelength=1.4,
    )

    fig.suptitle(
        "IPC speedup vs LRU as a function of mid-insertion threshold — scope comparison",
        fontsize=12, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0.06, 1, 1])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
