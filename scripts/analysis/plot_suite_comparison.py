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

    # STLB policy comparison:
    python3 scripts/analysis/plot_suite_comparison.py \\
        results/dpc3_stlb_policy_<date>/ results/google_stlb_policy_pc_<date>/ results/qmm_stlb_policy_pc_<date>/ \\
        --policies stlb_srrip stlb_srrip_live stlb_lru_mid \\
        --labels "SPEC (DPC3)" Google Qualcomm \\
        --out results/plots/stlb_policy/suite_stlb_policy.png
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
from colors import POLICY_COLORS as _COLOR_MAP, POLICY_HATCHES as _HATCH_MAP
from spec_weights import benchmark_name, load_spec_weights


# ── Policies ──────────────────────────────────────────────────────────────────

_ALL_POLICIES = [
    ("srrip",            "SRRIP"),
    ("srrip_both",       "SRRIP (LLC+STLB)"),
    ("lru_mid",          "lru_mid"),
    ("lru_mid_both",     "lru_mid (LLC+STLB)"),
    ("ipv",              "IPV (LLC)"),
    ("ipv_both",         "IPV (LLC+STLB)"),
    ("srrip_live",       "srrip_live (LLC)"),
    ("stlb_srrip_live",  "srrip_live (STLB)"),
    ("srrip_live_both",  "srrip_live (LLC+STLB)"),
    ("ipv_live",         "ipv_live (LLC)"),
    ("ipv_live_both",    "ipv_live (LLC+STLB)"),
    ("stlb_ipv",         "IPV (STLB)"),
    ("stlb_ipv_live",    "ipv_live (STLB)"),
    ("lru_dp_only",      "lru+dp"),
    ("hash_pred",        "hash+pred"),
    ("lru_pred",         "lru+pred"),
    ("lfu_pred",         "lfu+pred"),
    ("lru_pred_no_pfq",  "lru+pred (no PFQ)"),
    ("lfu_pred_no_pfq",  "lfu+pred (no PFQ)"),
    ("lru_pred_adaptive","lru+pred (adaptive)"),
    ("srrip_pred",       "SRRIP+pred"),
    ("lru_mid_pred",     "lru_mid+pred"),
    ("drrip",            "DRRIP"),
    ("drrip_pred",       "DRRIP+pred"),
    ("stlb_srrip",       "STLB-SRRIP"),
    ("stlb_lru_mid",     "STLB-lru_mid"),
]
_DEFAULT_COLORS = ["#888888"] * len(_ALL_POLICIES)

POLICIES      = [p for p, _ in _ALL_POLICIES]
POLICY_LABELS = [l for _, l in _ALL_POLICIES]
POLICY_COLORS  = [_COLOR_MAP.get(p, "#888888") for p, _ in _ALL_POLICIES]
POLICY_HATCHES = [_HATCH_MAP.get(p, "")        for p, _ in _ALL_POLICIES]
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
    """Grouped bar chart: one group per policy, one bar per suite.

    Policies sorted descending by their mean speedup across suites.
    Each bar shows the per-suite benchmark-weighted geomean IPC speedup vs LRU.
    """
    n_suites = len(suite_labels)

    # Find policies with data in at least one suite
    has_data = [i for i in range(len(POLICIES))
                if any(row.get(POLICIES[i]) is not None for row in suite_speedup_rows)]

    # Sort by mean speedup across suites (descending)
    def _mean_speedup(pol_idx):
        vals = [suite_speedup_rows[si].get(POLICIES[pol_idx])
                for si in range(n_suites)
                if suite_speedup_rows[si].get(POLICIES[pol_idx]) is not None]
        return np.mean(vals) if vals else 1.0

    order = sorted(has_data, key=_mean_speedup, reverse=True)
    pol_s    = [POLICIES[i]       for i in order]
    labels_s = [POLICY_LABELS[i]  for i in order]
    colors_s = [POLICY_COLORS[i]  for i in order]
    hatches_s= [POLICY_HATCHES[i] for i in order]

    n_pol = len(pol_s)
    # Within each policy group, one bar per suite (hatched to distinguish)
    suite_hatches = ["", "//", "..", "xx", "\\\\", "++", "oo"]
    bar_w = max(0.10, min(0.25, 0.75 / n_suites))
    step  = bar_w + 0.02
    offsets = [(j - (n_suites - 1) / 2) * step for j in range(n_suites)]
    x = np.arange(n_pol)

    fig, ax = plt.subplots(figsize=(max(8, n_pol * (n_suites * 0.35 + 0.3) + 2), 5))

    for si, (slabel, row, shatch) in enumerate(zip(suite_labels, suite_speedup_rows,
                                                    suite_hatches)):
        for pi, (pol, color, phatch) in enumerate(zip(pol_s, colors_s, hatches_s)):
            h = (row.get(pol) - 1.0) * 100 if row.get(pol) is not None else None
            if h is None:
                continue
            label = slabel if pi == 0 else None
            ax.bar(x[pi] + offsets[si], h, bar_w,
                   color=color, hatch=phatch + shatch,
                   edgecolor="black", linewidth=0.5,
                   label=label, zorder=3)
            yoff = 0.03 if h >= 0 else -0.03
            ax.text(x[pi] + offsets[si], h + yoff,
                    f"{h:+.1f}%", ha="center",
                    va="bottom" if h >= 0 else "top",
                    fontsize=6, rotation=90)

    ax.axhline(0.0, color="black", linewidth=0.8, linestyle="--", zorder=2)

    all_vals = [(row.get(p) - 1.0) * 100 for row in suite_speedup_rows
                for p in pol_s if row.get(p) is not None] + [0.0]
    lo, hi = min(all_vals), max(all_vals)
    span = max(hi - lo, 1e-4)
    ax.set_ylim(lo - 0.12 * span, hi + 0.55 * span)

    ax.set_xticks(x)
    ax.set_xticklabels(labels_s, rotation=40, ha="right", fontsize=9)
    ax.set_ylabel("IPC speedup vs LRU (%)", fontsize=11)
    ax.set_title("IPC speedup vs LRU — geomean per suite and policy", fontsize=10)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%+.2f%%"))
    ax.grid(axis="y", alpha=0.25, linewidth=0.5)
    ax.legend(title="Suite", fontsize=8, title_fontsize=8, loc="upper right")

    fig.tight_layout()
    out_path.parent.mkdir(exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


def plot_mpki(suite_labels, stlb_rows, llc_rows, out_path: Path):
    """Two-panel figure: STLB (left) and LLC (right) mean MPKI reduction % vs LRU.

    Shows overall mean across suites only, sorted descending by STLB reduction.
    """
    overall_stlb, overall_llc = {}, {}
    for pol in POLICIES:
        s_vals = [r.get(pol) for r in stlb_rows if r.get(pol) is not None]
        l_vals = [r.get(pol) for r in llc_rows  if r.get(pol) is not None]
        overall_stlb[pol] = float(np.mean(s_vals)) if s_vals else None
        overall_llc[pol]  = float(np.mean(l_vals)) if l_vals else None

    # Drop policies with no data in either cache metric
    has_data = [i for i in range(len(POLICIES))
                if overall_stlb.get(POLICIES[i]) is not None
                or overall_llc.get(POLICIES[i]) is not None]

    # Sort descending by STLB reduction (primary); LLC reduction as tiebreak
    order = sorted(has_data,
                   key=lambda i: (overall_stlb.get(POLICIES[i]) or 0.0,
                                  overall_llc.get(POLICIES[i])  or 0.0),
                   reverse=True)
    pol_s    = [POLICIES[i]       for i in order]
    labels_s = [POLICY_LABELS[i]  for i in order]
    colors_s = [POLICY_COLORS[i]  for i in order]
    hatches_s= [POLICY_HATCHES[i] for i in order]

    x = np.arange(len(pol_s))
    fig, axes = plt.subplots(1, 2, figsize=(max(8, len(pol_s) * 0.85 + 2) * 1.6, 5),
                             sharey=False)

    for ax, overall, cache in zip(axes, [overall_stlb, overall_llc], ["STLB", "LLC"]):
        heights = [overall.get(p) or 0.0 for p in pol_s]
        bars = ax.bar(x, heights, 0.72, edgecolor="black", linewidth=0.5, zorder=3)
        for bar, color, hatch in zip(bars, colors_s, hatches_s):
            bar.set_facecolor(color)
            bar.set_hatch(hatch)

        for bar, h in zip(bars, heights):
            va   = "bottom" if h >= 0 else "top"
            yoff = 0.05 if h >= 0 else -0.05
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + yoff,
                    f"{h:+.1f}%", ha="center", va=va,
                    fontsize=8, rotation=90)

        ax.axhline(0, color="black", linewidth=0.8, linestyle="--", zorder=2)
        valid = heights + [0]
        lo, hi = min(valid), max(valid)
        span = max(hi - lo, 1e-4)

        if hi - lo > 200:
            ax.set_yscale("symlog", linthresh=10)
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(
                lambda v, _: f"{v:+.0f}%"))
        else:
            ax.set_ylim(lo - 0.15 * span, hi + 0.55 * span)
            ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))

        ax.set_xticks(x)
        ax.set_xticklabels(labels_s, rotation=40, ha="right", fontsize=9)
        ax.set_ylabel("MPKI reduction vs LRU (%)", fontsize=11)
        suite_str = " + ".join(suite_labels)
        ax.set_title(f"{cache} MPKI reduction vs LRU — mean across {suite_str}", fontsize=10)
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
    ap.add_argument("--policies", nargs="*", default=None,
                    help="Whitelist of policy names to show (default: all known policies "
                         "that have matching subdirectories). E.g. --policies stlb_srrip stlb_srrip_live")
    ap.add_argument("--exclude", nargs="*", default=[],
                    help="Exclude policies whose name contains any of these substrings (e.g. --exclude drrip)")
    ap.add_argument("--suffix", default="",
                    help="Suffix appended to all policy and baseline directory names (e.g. _paper_pref)")
    ap.add_argument("--baseline", default=None,
                    help="Baseline policy subdirectory name (default: lru)")
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
    if args.baseline is not None:
        BASELINE = args.baseline
    BASELINE = BASELINE + args.suffix
    suffixed_policies = [p + args.suffix for p in POLICIES]

    # Whitelist filter (--policies) then exclusion filter (--exclude).
    # Always drop the baseline itself from the plotted bars (it would show 0% by construction).
    whitelist = set(args.policies) if args.policies else None
    excl = args.exclude
    def excluded(pol_base, pol_sfx):
        if pol_sfx == BASELINE:
            return True
        if whitelist is not None and pol_base not in whitelist:
            return True
        return any(s in pol_sfx for s in excl)

    active_policies = [ps for pb, ps in zip(POLICIES, suffixed_policies) if not excluded(pb, ps)]
    active_labels   = [l  for pb, ps, l in zip(POLICIES, suffixed_policies, POLICY_LABELS)
                       if not excluded(pb, ps)]
    active_colors   = [c  for pb, ps, c in zip(POLICIES, suffixed_policies, POLICY_COLORS)
                       if not excluded(pb, ps)]
    active_hatches  = [h  for pb, ps, h in zip(POLICIES, suffixed_policies, POLICY_HATCHES)
                       if not excluded(pb, ps)]

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
    stem = out_path.stem
    mpki_stem = stem.replace("ipc", "mpki") if "ipc" in stem else stem + "_mpki"
    mpki_path = out_path.parent / (mpki_stem + out_path.suffix)
    plot_mpki(labels, stlb_rows, llc_rows, mpki_path)


if __name__ == "__main__":
    main()
