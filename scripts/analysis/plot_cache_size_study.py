#!/usr/bin/env python3
"""plot_cache_size_study.py — delta plots for the cache/TLB size study.

Each component (LLC, L2C, STLB, DTLB, ITLB) was varied independently at
÷2 (half) and ×2 (double) while all others are held at baseline.

Produces two figures:

  <out>/liveness_<suite>.png
    5 subplot columns (one per component).
    For each column: grouped bars showing LLC DoA, LLC mostly-dead, STLB DoA,
    STLB mostly-dead at {half, baseline, double}.

  <out>/correlation_<suite>.png
    Same 5 columns.
    Stacked bars showing the five correlation buckets (resident_doa,
    evicted_doa, resident_alive, evicted_alive, uncovered) as % of LLC DoA,
    at {half, baseline, double}.

Values are arithmetic means across workloads (fractions are already %).

Usage
-----
    python3 scripts/analysis/plot_cache_size_study.py  \\
        results/dpc3_cache_size_<date>/                \\
        --suite dpc3 --out results/plots/cache_size_study/
"""

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from liveness_utils import load_suite, load_suite_corr_full

# ── Study geometry ────────────────────────────────────────────────────────────

COMPS      = ["llc", "l2c", "stlb", "dtlb", "itlb"]
COMP_LABEL = {"llc": "LLC", "l2c": "L2C", "stlb": "STLB",
               "dtlb": "DTLB", "itlb": "ITLB"}

# (sets_half, sets_baseline, sets_double)  — matches build_cache_size_study.sh
SIZES = {
    "llc":  (1024, 2048, 4096),
    "l2c":  (256,   512, 1024),
    "stlb": (64,    128,  256),
    "dtlb": (8,      16,   32),
    "itlb": (16,     32,   64),
}
WAYS  = {"llc": 16, "l2c": 8, "stlb": 8, "dtlb": 4, "itlb": 4}
BLOCK = 64  # bytes

VARIANTS = [("half", "÷2"), ("baseline", "×1\n(base)"), ("double", "×2")]

CACHE_NAME = {
    "llc":  "LLC",
    "l2c":  "L2C",
    "stlb": "cpu0_STLB",
    "dtlb": "cpu0_DTLB",
    "itlb": "cpu0_ITLB",
}


def _size_label(comp: str, variant: str) -> str:
    idx = {"half": 0, "baseline": 1, "double": 2}[variant]
    sets = SIZES[comp][idx]
    entries = sets * WAYS[comp]
    if comp in ("llc", "l2c"):
        kb = entries * BLOCK // 1024
        return f"{kb}KB" if kb < 1024 else f"{kb // 1024}MB"
    return f"{entries}"


# ── Data loading ──────────────────────────────────────────────────────────────

def exp_dir_name(comp: str, variant: str) -> str:
    return "baseline" if variant == "baseline" else f"{comp}_{variant}"


def load_liveness(results_dir: Path, comp: str, variant: str):
    d = results_dir / exp_dir_name(comp, variant)
    if not d.is_dir():
        return None
    return load_suite(d)


def load_corr(results_dir: Path, comp: str, variant: str):
    d = results_dir / exp_dir_name(comp, variant)
    if not d.is_dir():
        return None
    return load_suite_corr_full(d)


def mean_frac(rows, cache: str, field: str) -> float:
    vals = []
    for _wl, data in rows:
        if cache not in data or data[cache]["total"] == 0:
            continue
        vals.append(100.0 * data[cache][field] / data[cache]["total"])
    return float(np.mean(vals)) if vals else float("nan")


def mean_corr_field(rows, field: str) -> float:
    import math
    vals = [d[field] for _wl, d in rows
            if not math.isnan(d.get(field, float("nan")))]
    return float(np.mean(vals)) if vals else float("nan")


# ── Liveness figure ───────────────────────────────────────────────────────────

_LIV_SERIES = [
    ("LLC",       "doa",         "LLC DoA",          "#3A6FA6"),
    ("LLC",       "mostly_dead", "LLC mostly-dead",  "#7AAED6"),
    ("cpu0_STLB", "doa",         "STLB DoA",         "#C4683A"),
    ("cpu0_STLB", "mostly_dead", "STLB mostly-dead", "#E8A87C"),
]


def plot_liveness(results_dir: Path, suite: str, out_dir: Path):
    n_series  = len(_LIV_SERIES)
    n_var     = len(VARIANTS)
    width     = 0.8 / n_series
    x_centers = np.arange(n_var)

    fig, axes = plt.subplots(1, len(COMPS), figsize=(3.2 * len(COMPS), 3.8),
                             sharey=True)
    fig.suptitle(f"Liveness fractions — ÷2 / baseline / ×2  [{suite}]", fontsize=11)

    for ax, comp in zip(axes, COMPS):
        for si, (cache_key, field, label, color) in enumerate(_LIV_SERIES):
            ys = []
            for var, _ in VARIANTS:
                rows = load_liveness(results_dir, comp, var)
                ys.append(mean_frac(rows, cache_key, field) if rows else float("nan"))
            offsets = (np.arange(n_series) - (n_series - 1) / 2) * width
            bars = ax.bar(x_centers + offsets[si], ys, width * 0.9,
                          color=color, label=label if comp == COMPS[0] else "")
            # label bar value
            for bar, v in zip(bars, ys):
                if not np.isnan(v) and v > 2:
                    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                            f"{v:.0f}", ha="center", va="bottom", fontsize=5.5)

        ax.set_xticks(x_centers)
        ax.set_xticklabels([lbl for _, lbl in VARIANTS], fontsize=7.5)
        ax.set_title(COMP_LABEL[comp], fontsize=9)
        ax.set_ylabel("% of evictions" if comp == COMPS[0] else "", fontsize=8)
        ax.tick_params(labelsize=7)
        ax.set_ylim(0, 100)
        ax.grid(axis="y", linestyle=":", linewidth=0.5, alpha=0.6)

        # Secondary x-labels: absolute sizes
        for xi, (var, _) in enumerate(VARIANTS):
            ax.text(xi, -8, _size_label(comp, var), ha="center", va="top",
                    fontsize=6, color="gray", transform=ax.get_xaxis_transform())

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, fontsize=8,
               bbox_to_anchor=(0.5, -0.01))
    fig.tight_layout(rect=[0, 0.08, 1, 1])

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"liveness_{suite}.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {out_path}")


# ── Correlation figure ────────────────────────────────────────────────────────

_CORR_STACK = [
    ("resident_doa",    "resident DoA",   "#3A6FA6"),
    ("evicted_doa",     "evicted DoA",    "#7AAED6"),
    ("resident_alive",  "resident alive", "#C4683A"),
    ("evicted_alive",   "evicted alive",  "#E8A87C"),
    ("uncovered",       "uncovered",      "#BBBBBB"),
]
# Convert raw counts to % of llc_doa
def _corr_pct(d: dict, field: str) -> float:
    if d["llc_doa"] == 0:
        return float("nan")
    return 100.0 * d[field] / d["llc_doa"]


def plot_correlation(results_dir: Path, suite: str, out_dir: Path):
    n_var     = len(VARIANTS)
    x_centers = np.arange(n_var)
    bar_w     = 0.55

    fig, axes = plt.subplots(1, len(COMPS), figsize=(3.2 * len(COMPS), 3.8),
                             sharey=True)
    fig.suptitle(
        f"LLC DoA / STLB correlation — ÷2 / baseline / ×2  [{suite}]", fontsize=11
    )

    for ax, comp in zip(axes, COMPS):
        # shape: [n_variants, n_buckets]
        data = np.full((n_var, len(_CORR_STACK)), float("nan"))
        for vi, (var, _) in enumerate(VARIANTS):
            rows = load_corr(results_dir, comp, var)
            if rows is None:
                continue
            for si, (field, *_) in enumerate(_CORR_STACK):
                # convert raw counts → % of llc_doa per workload, then average
                vals = [_corr_pct(d, field) for _wl, d in rows
                        if d["llc_doa"] > 0]
                import math
                vals = [v for v in vals if not math.isnan(v)]
                data[vi, si] = float(np.mean(vals)) if vals else float("nan")

        bottoms = np.zeros(n_var)
        for si, (field, label, color) in enumerate(_CORR_STACK):
            ys = data[:, si]
            valid = ~np.isnan(ys)
            ax.bar(x_centers[valid], ys[valid], bar_w,
                   bottom=bottoms[valid], color=color,
                   label=label if comp == COMPS[0] else "")
            bottoms[valid] += ys[valid]

        ax.set_xticks(x_centers)
        ax.set_xticklabels([lbl for _, lbl in VARIANTS], fontsize=7.5)
        ax.set_title(COMP_LABEL[comp], fontsize=9)
        ax.set_ylabel("% of LLC DoA evictions" if comp == COMPS[0] else "", fontsize=8)
        ax.tick_params(labelsize=7)
        ax.set_ylim(0, 100)
        ax.grid(axis="y", linestyle=":", linewidth=0.5, alpha=0.6)

        for xi, (var, _) in enumerate(VARIANTS):
            ax.text(xi, -8, _size_label(comp, var), ha="center", va="top",
                    fontsize=6, color="gray", transform=ax.get_xaxis_transform())

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=5, fontsize=8,
               bbox_to_anchor=(0.5, -0.01))
    fig.tight_layout(rect=[0, 0.08, 1, 1])

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"correlation_{suite}.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {out_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results_dir",
                        help="Base results directory (e.g. results/dpc3_cache_size_<date>/)")
    parser.add_argument("--suite", default="",
                        help="Label for figure titles and filenames (e.g. dpc3)")
    parser.add_argument("--out", default="results/plots/cache_size_study",
                        help="Output directory for PNG files")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    if not results_dir.is_dir():
        sys.exit(f"ERROR: results directory not found: {results_dir}")

    suite   = args.suite or results_dir.name
    out_dir = Path(args.out)

    print(f"Results : {results_dir}")
    print(f"Suite   : {suite}")
    print(f"Output  : {out_dir}")
    print()

    print("Liveness figure ...")
    plot_liveness(results_dir, suite, out_dir)

    print("Correlation figure ...")
    plot_correlation(results_dir, suite, out_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()
