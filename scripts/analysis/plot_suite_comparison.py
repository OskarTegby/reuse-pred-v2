#!/usr/bin/env python3
"""plot_suite_comparison.py — IPC speedup across benchmark suites per replacement policy.

For each suite results directory, computes the geomean IPC speedup of every
non-prefetch, non-predictor replacement policy vs a common LRU baseline.
Produces a grouped bar chart: one group per suite + an overall geomean group,
one bar per policy.

Policies included (auto-detected, no-prefetch/no-pred only):
    lru_mid, srrip, drrip

Baseline: lru

Usage
-----
    python3 scripts/analysis/plot_suite_comparison.py \\
        results/qmm_pol_<date>/ results/dpc3_pol_<date>/ results/google_pol_<date>/ \\
        [--labels qmm dpc3 google] \\
        [--out plots/suite_ipc.png]
"""

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

from champsim_utils import parse_stats, geomean
from spec_weights import benchmark_name, load_spec_weights


# ── Policies ──────────────────────────────────────────────────────────────────

POLICIES      = ["lru_mid", "lru_mid_pred", "lru_pred",
                 "srrip", "srrip_pred", "drrip", "drrip_pred"]
POLICY_LABELS = ["lru_mid", "lru_mid+pred", "lru+pred",
                 "SRRIP", "SRRIP+pred", "DRRIP", "DRRIP+pred"]
POLICY_COLORS = ["#A67CB9", "#6A3D8A", "#2C5F8A",
                 "#E8A87C", "#C46A30",  "#7CB9A8", "#3D8A78"]
POLICY_HATCHES = ["", "//", "//", "", "//", "", "//"]
BASELINE      = "lru"


# ── Parsing ───────────────────────────────────────────────────────────────────

def load_policy_stats(policy_dir: Path):
    """Return dict { workload: (ipc, stlb_mpki, llc_mpki) }."""
    files = sorted(policy_dir.glob("*/champsim.out"))
    nested = True
    if not files:
        files = sorted(policy_dir.glob("*.out"))
        nested = False
    out = {}
    for f in files:
        wl = f.parent.name if nested else f.stem
        ipc, stlb, llc = parse_stats(f)
        if ipc is not None:
            out[wl] = (ipc, stlb, llc)
    return out


def load_policy_ipcs(policy_dir: Path):
    """Return dict { workload: ipc } — kept for backward compat."""
    return {wl: v[0] for wl, v in load_policy_stats(policy_dir).items()}


def _weighted_geomean(pairs: "list[tuple[float, float]]") -> "float | None":
    """Weighted geometric mean of (value, weight) pairs.

    Weights need not sum to 1 — they are re-normalised internally so that
    missing simpoints do not bias the result.
    """
    pairs = [(v, w) for v, w in pairs if v is not None and v > 0 and w is not None]
    if not pairs:
        return None
    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        return None
    return float(np.exp(sum((w / total_w) * np.log(v) for v, w in pairs)))


def _weighted_mean(pairs: "list[tuple[float, float]]") -> "float | None":
    """Weighted arithmetic mean of (value, weight) pairs, re-normalised."""
    pairs = [(v, w) for v, w in pairs if v is not None and w is not None]
    if not pairs:
        return None
    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        return None
    return float(sum((w / total_w) * v for v, w in pairs))


def benchmark_geomean(ratios_by_wl: dict, weights: "dict[str, float] | None" = None) -> "float | None":
    """Benchmark-weighted geomean.

    Within each benchmark: weighted geometric mean using simpoint weights when
    available (re-normalised for any missing simpoints), falling back to equal
    weights.  Across benchmarks: equal-weight geometric mean.
    """
    groups: "dict[str, list]" = {}
    for wl, v in ratios_by_wl.items():
        if v is not None and v > 0:
            groups.setdefault(benchmark_name(wl), []).append(wl)
    if not groups:
        return None
    per_bench = []
    for wl_list in groups.values():
        if weights:
            pairs = [(ratios_by_wl[wl], weights.get(wl)) for wl in wl_list]
            if any(w is not None for _, w in pairs):
                per_bench.append(_weighted_geomean(pairs))
                continue
        per_bench.append(geomean([ratios_by_wl[wl] for wl in wl_list]))
    return geomean(per_bench)


def benchmark_mean(values_by_wl: dict, weights: "dict[str, float] | None" = None) -> "float | None":
    """Benchmark-weighted mean.

    Within each benchmark: weighted arithmetic mean using simpoint weights when
    available, falling back to equal weights.  Across benchmarks: equal-weight mean.
    """
    groups: "dict[str, list]" = {}
    for wl, v in values_by_wl.items():
        if v is not None:
            groups.setdefault(benchmark_name(wl), []).append(wl)
    if not groups:
        return None
    per_bench = []
    for wl_list in groups.values():
        if weights:
            pairs = [(values_by_wl[wl], weights.get(wl)) for wl in wl_list]
            if any(w is not None for _, w in pairs):
                per_bench.append(_weighted_mean(pairs))
                continue
        per_bench.append(float(np.mean([values_by_wl[wl] for wl in wl_list])))
    return float(np.mean(per_bench)) if per_bench else None


def suite_speedups(suite_dir: Path, policies: list[str],
                   weights: "dict[str, float] | None" = None):
    """Return (dict { policy: benchmark-weighted geomean IPC ratio }, n_benchmarks)."""
    base = {wl: v[0] for wl, v in load_policy_stats(suite_dir / BASELINE).items()}
    if not base:
        return {}, 0
    result = {}
    n_benchmarks = None
    for pol in policies:
        pol_dir = suite_dir / pol
        if not pol_dir.is_dir():
            result[pol] = None
            continue
        pol_stats = load_policy_stats(pol_dir)
        common = [wl for wl in base if wl in pol_stats and base[wl] > 0]
        if n_benchmarks is None:
            n_benchmarks = len(set(benchmark_name(wl) for wl in common))
        result[pol] = benchmark_geomean(
            {wl: pol_stats[wl][0] / base[wl] for wl in common}, weights)
    return result, (n_benchmarks or 0)


def suite_mpki_reductions(suite_dir: Path, policies: list[str],
                          weights: "dict[str, float] | None" = None):
    """Return (stlb_dict, llc_dict) each { policy: benchmark-weighted mean MPKI reduction % }."""
    base_stats = load_policy_stats(suite_dir / BASELINE)
    base_stlb  = {wl: v[1] for wl, v in base_stats.items() if v[1] is not None}
    base_llc   = {wl: v[2] for wl, v in base_stats.items() if v[2] is not None}

    stlb_res, llc_res = {}, {}
    for pol in policies:
        pol_dir = suite_dir / pol
        if not pol_dir.is_dir():
            stlb_res[pol] = llc_res[pol] = None
            continue
        pol_stats = load_policy_stats(pol_dir)

        stlb_by_wl = {wl: (base_stlb[wl] - pol_stats[wl][1]) / base_stlb[wl] * 100
                      for wl in base_stlb if wl in pol_stats
                      and pol_stats[wl][1] is not None and base_stlb[wl] > 0}
        llc_by_wl  = {wl: (base_llc[wl]  - pol_stats[wl][2]) / base_llc[wl]  * 100
                      for wl in base_llc  if wl in pol_stats
                      and pol_stats[wl][2] is not None and base_llc[wl]  > 0}

        stlb_res[pol] = benchmark_mean(stlb_by_wl, weights)
        llc_res[pol]  = benchmark_mean(llc_by_wl,  weights)

    return stlb_res, llc_res


# ── Plot ──────────────────────────────────────────────────────────────────────

def plot(suite_labels, suite_speedup_rows, out_path: Path):
    """
    suite_speedup_rows : list of { policy: speedup_or_None }, one per suite.
    An extra "Overall" group is appended using geomean across all suites.
    """
    all_labels = suite_labels + ["Overall"]

    # Overall geomean across suites for each policy
    overall = {}
    for pol in POLICIES:
        vals = [row.get(pol) for row in suite_speedup_rows if row.get(pol) is not None]
        overall[pol] = geomean(vals)
    all_rows = suite_speedup_rows + [overall]

    n_groups  = len(all_labels)
    n_pol     = len(POLICIES)
    group_w   = 0.8
    bar_w     = group_w / n_pol
    x_groups  = np.arange(n_groups)

    fig, ax = plt.subplots(figsize=(max(8, n_groups * 2.5 + 2), 5))

    for pi, (pol, label, color, hatch) in enumerate(
            zip(POLICIES, POLICY_LABELS, POLICY_COLORS, POLICY_HATCHES)):
        offsets = (np.arange(n_pol) - (n_pol - 1) / 2) * bar_w
        x_pos   = x_groups + offsets[pi]
        heights = [row.get(pol) or 0 for row in all_rows]
        bars = ax.bar(x_pos, heights, bar_w * 0.92,
                      color=color, edgecolor="black", linewidth=0.5,
                      hatch=hatch, label=label, zorder=3)

        # Value label above each bar
        for bar, h, row in zip(bars, heights, all_rows):
            if row.get(pol) is not None:
                sign = "+" if h >= 1.0 else ""
                pct  = (h - 1.0) * 100
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + 0.001,
                        f"{sign}{pct:.1f}%",
                        ha="center", va="bottom", fontsize=7, rotation=90)

    # Reference line at 1.0 (= LRU baseline)
    ax.axhline(1.0, color="black", linewidth=0.8, linestyle="--", zorder=2)

    # Separator before Overall group
    ax.axvline(n_groups - 1 - 0.5, color="gray", linewidth=0.8, linestyle=":", zorder=1)

    # y-axis zoom
    all_vals = [row.get(pol) for row in all_rows for pol in POLICIES
                if row.get(pol) is not None]
    all_vals.append(1.0)
    lo, hi = min(all_vals), max(all_vals)
    span = max(hi - lo, 1e-4)
    ax.set_ylim(lo - 0.35 * span, hi + 0.45 * span)  # extra headroom for labels

    ax.set_xticks(x_groups)
    ax.set_xticklabels(all_labels, fontsize=10)
    for tick, lbl in zip(ax.get_xticklabels(), all_labels):
        if lbl == "Overall":
            tick.set_fontweight("bold")

    ax.set_ylabel("IPC speedup vs LRU", fontsize=11)
    ax.set_title("IPC speedup vs LRU — per benchmark suite", fontsize=11)
    ax.legend(fontsize=9, loc="upper right", framealpha=0.85, ncol=2)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f×"))
    ax.grid(axis="y", alpha=0.25, linewidth=0.5)

    fig.tight_layout()
    out_path.parent.mkdir(exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


def plot_mpki(suite_labels, stlb_rows, llc_rows, out_path: Path):
    """Two-panel figure: STLB (left) and LLC (right) mean MPKI reduction % vs LRU."""
    all_labels = suite_labels + ["Overall"]

    overall_stlb, overall_llc = {}, {}
    for pol in POLICIES:
        s_vals = [r.get(pol) for r in stlb_rows if r.get(pol) is not None]
        l_vals = [r.get(pol) for r in llc_rows  if r.get(pol) is not None]
        overall_stlb[pol] = float(np.mean(s_vals)) if s_vals else None
        overall_llc[pol]  = float(np.mean(l_vals)) if l_vals else None

    all_stlb = stlb_rows + [overall_stlb]
    all_llc  = llc_rows  + [overall_llc]

    n_groups = len(all_labels)
    n_pol    = len(POLICIES)
    bar_w    = 0.8 / n_pol
    x_groups = np.arange(n_groups)

    fig, axes = plt.subplots(1, 2, figsize=(max(8, n_groups * 2.5 + 2) * 1.6, 5),
                             sharey=False)

    for ax, rows, cache in zip(axes, [all_stlb, all_llc], ["STLB", "LLC"]):
        for pi, (pol, label, color, hatch) in enumerate(
                zip(POLICIES, POLICY_LABELS, POLICY_COLORS, POLICY_HATCHES)):
            offsets = (np.arange(n_pol) - (n_pol - 1) / 2) * bar_w
            x_pos   = x_groups + offsets[pi]
            heights = [r.get(pol) or 0 for r in rows]
            bars = ax.bar(x_pos, heights, bar_w * 0.92,
                          color=color, edgecolor="black", linewidth=0.5,
                          hatch=hatch, label=label, zorder=3)
            for bar, h, row in zip(bars, heights, rows):
                if row.get(pol) is not None:
                    va   = "bottom" if h >= 0 else "top"
                    yoff = 0.15 if h >= 0 else -0.15
                    ax.text(bar.get_x() + bar.get_width() / 2,
                            bar.get_height() + yoff,
                            f"{h:+.1f}%", ha="center", va=va,
                            fontsize=7, rotation=90)

        ax.axhline(0, color="black", linewidth=0.8, linestyle="--", zorder=2)
        ax.axvline(n_groups - 1 - 0.5, color="gray", linewidth=0.8,
                   linestyle=":", zorder=1)
        all_vals = [r.get(pol) for r in rows for pol in POLICIES
                    if r.get(pol) is not None] + [0]
        lo, hi = min(all_vals), max(all_vals)
        span = max(hi - lo, 1e-4)

        # Use symlog when the range spans more than one order of magnitude
        if hi - lo > 200:
            ax.set_yscale("symlog", linthresh=10)
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(
                lambda v, _: f"{v:+.0f}%"))
        else:
            ax.set_ylim(lo - 0.15 * span, hi + 0.55 * span)
            ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))

        ax.set_xticks(x_groups)
        ax.set_xticklabels(all_labels, fontsize=10)
        for tick, lbl in zip(ax.get_xticklabels(), all_labels):
            if lbl == "Overall":
                tick.set_fontweight("bold")
        ax.set_ylabel("MPKI reduction vs LRU (%)", fontsize=11)
        ax.set_title(f"{cache} MPKI reduction vs LRU — per suite", fontsize=11)
        ax.legend(fontsize=9, loc="upper right", framealpha=0.85, ncol=2)
        ax.grid(axis="y", alpha=0.25, linewidth=0.5)

    fig.tight_layout()
    out_path.parent.mkdir(exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("results_dirs", nargs="+",
                    help="One policy-sweep results directory per suite")
    ap.add_argument("--labels", nargs="*", default=None,
                    help="Suite labels (default: directory names)")
    ap.add_argument("--out", default=None,
                    help="Output PNG path (default: plots/suite_ipc.png beside first results dir)")
    ap.add_argument("--exclude", nargs="*", default=[],
                    help="Exclude policies whose name contains any of these substrings (e.g. --exclude drrip)")
    ap.add_argument("--suffix", default="",
                    help="Suffix appended to all policy and baseline directory names (e.g. _paper_pref)")
    ap.add_argument("--weights-dir", default=None,
                    help="Directory containing per-benchmark simpoint weight files "
                         "(subdirs named after benchmarks, each with weights.out + simpoints.out). "
                         "Default: auto-detected from known location.")
    args = ap.parse_args()

    dirs = [Path(d) for d in args.results_dirs]
    for d in dirs:
        if not d.is_dir():
            sys.exit(f"ERROR: not a directory: {d}")

    labels = args.labels or [d.name for d in dirs]
    if len(labels) != len(dirs):
        sys.exit("ERROR: --labels count must match number of result directories")

    # Apply suffix to baseline and policies
    global BASELINE
    BASELINE = BASELINE + args.suffix
    suffixed_policies = [p + args.suffix for p in POLICIES]

    # Filter policy lists according to --exclude substrings
    excl = args.exclude
    def excluded(pol):
        return any(s in pol for s in excl)

    active_policies = [p for p in suffixed_policies if not excluded(p)]
    active_labels   = [l for p, l in zip(POLICIES, POLICY_LABELS)   if not excluded(p)]
    active_colors   = [c for p, c in zip(POLICIES, POLICY_COLORS)   if not excluded(p)]
    active_hatches  = [h for p, h in zip(POLICIES, POLICY_HATCHES)  if not excluded(p)]

    # Narrow the module-level policy lists so plot() and plot_mpki() see only
    # the active subset — reassign via index to avoid the global-before-use error.
    POLICIES[:]       = active_policies
    POLICY_LABELS[:]  = active_labels
    POLICY_COLORS[:]  = active_colors
    POLICY_HATCHES[:] = active_hatches

    # Load simpoint weights
    _default_weights = Path(__file__).parents[2] / ".." / "ChampSim-dev" / "trace-files" / "SPEC2006_weights"
    weights_dir = Path(args.weights_dir) if args.weights_dir else _default_weights.resolve()
    weights = load_spec_weights(weights_dir)
    if weights:
        print(f"Loaded simpoint weights for {len(set(benchmark_name(k) for k in weights))} benchmarks "
              f"from {weights_dir}")
    else:
        print(f"WARNING: no simpoint weights found at {weights_dir} — using equal weights")

    speedup_rows = []
    for lbl, d in zip(labels, dirs):
        if not (d / BASELINE).is_dir():
            sys.exit(f"ERROR: no '{BASELINE}/' baseline subdir found in {d}")
        print(f"Loading '{lbl}' from {d} ...")
        row, n = suite_speedups(d, POLICIES, weights)
        print(f"  {n} common benchmarks (simpoint-weighted geomean)")
        for pol in POLICIES:
            v = row.get(pol)
            tag = f"{(v-1)*100:+.2f}%" if v is not None else "missing"
            print(f"    {pol}: {tag}")
        speedup_rows.append(row)

    out_path = Path(args.out) if args.out else dirs[0].parent / "plots" / "suite_ipc.png"
    plot(labels, speedup_rows, out_path)

    stlb_rows, llc_rows = [], []
    for lbl, d in zip(labels, dirs):
        stlb, llc = suite_mpki_reductions(d, POLICIES, weights)
        stlb_rows.append(stlb)
        llc_rows.append(llc)
    mpki_path = out_path.parent / (out_path.stem.replace("ipc", "mpki") + out_path.suffix)
    plot_mpki(labels, stlb_rows, llc_rows, mpki_path)


if __name__ == "__main__":
    main()
