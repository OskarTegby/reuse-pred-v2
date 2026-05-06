#!/usr/bin/env python3
"""
plot_liveness.py — plot DoA / mostly-dead / mostly-alive statistics for LLC and STLB.

Usage:
    # Single trace — stacked bar + hit-count histogram
    python3 scripts/analysis/plot_liveness.py <results_dir> --trace TRACE [--config CONFIG]

    # All traces — one bar per workload + geometric mean
    python3 scripts/analysis/plot_liveness.py <results_dir> [--config CONFIG] [--cache CACHE]

    # Direct file
    python3 scripts/analysis/plot_liveness.py --file path/to/champsim.out

    --config  Config sub-dir name inside results_dir (default: lru).
    --trace   Trace name (e.g. srv_128). If omitted, plots all traces with geomean.
    --cache   Cache to plot in multi-workload mode: LLC or STLB (default: both).
    --out     Output PNG path (default: liveness_<label>.png).
    --no-hist Skip the hit-count histogram (single-trace mode only).

Output
------
  Single-trace : stacked bar (DoA/mostly-dead/mostly-alive %) + hit-count histogram.
  Multi-trace  : one stacked bar per workload + geometric mean bar, one panel per cache.
"""

import argparse
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

from spec_weights import benchmark_weighted_geomean_pct, SPEC_WEIGHTS, benchmark_name

MAX_WORKLOADS = 25   # maximum per-workload bars shown in multi-workload plots


def _diverse_select(items, feature_fn, k):
    """Greedy farthest-point sampling: select k items maximally spread in feature space.

    Starts with the item closest to the centroid, then iteratively adds the item
    that maximises the minimum distance to the already-selected set.  Features are
    normalised per-dimension to [0, 1] before computing Euclidean distances.
    Returns a list of indices into items, sorted by the original feature magnitude
    (descending dead fraction) so the displayed bars read left-to-right coherently.
    """
    n = len(items)
    if n <= k:
        return list(range(n))
    vecs = np.array([feature_fn(item) for item in items], dtype=float)
    lo, hi = vecs.min(axis=0), vecs.max(axis=0)
    span = np.where(hi > lo, hi - lo, 1.0)
    v = (vecs - lo) / span
    centroid = v.mean(axis=0)
    selected = [int(np.argmin(np.linalg.norm(v - centroid, axis=1)))]
    min_d = np.full(n, np.inf)
    while len(selected) < k:
        d = np.linalg.norm(v - v[selected[-1]], axis=1)
        min_d = np.minimum(min_d, d)
        min_d[selected] = -1.0
        selected.append(int(np.argmax(min_d)))
    return selected


def _aggregate_spec_benchmarks(rows):
    """Collapse SPEC simpoints into parent benchmark rows.

    For SPEC traces (identified by the -NNNb suffix), compute weighted-average
    liveness fractions within each benchmark and return one synthetic row per
    benchmark.  Non-SPEC rows are kept as-is.
    rows = [(wl_name, {cache: {total, doa, mostly_dead, mostly_alive, ...}})]
    """
    groups: dict = {}
    for wl, data in rows:
        groups.setdefault(benchmark_name(wl), []).append((wl, data))

    result = []
    for bm_name in sorted(groups.keys()):
        items = groups[bm_name]
        # Non-SPEC: name didn't change → keep as-is
        if len(items) == 1 and items[0][0] == bm_name:
            result.append(items[0])
            continue
        # SPEC: aggregate simpoints into one benchmark row
        all_caches: set = set()
        for _, d in items:
            all_caches |= set(d.keys())
        agg_data: dict = {}
        for cache in all_caches:
            sp_fracs = []
            for wl, data in items:
                d = data.get(cache, {})
                tot = d.get("total", 0)
                if tot == 0:
                    continue
                w = SPEC_WEIGHTS.get(wl)
                sp_fracs.append((d.get("doa", 0) / tot,
                                 d.get("mostly_dead", 0) / tot,
                                 d.get("mostly_alive", 0) / tot, w))
            if not sp_fracs:
                continue
            w_valid = [(d, m, a, w) for d, m, a, w in sp_fracs if w is not None]
            if w_valid and SPEC_WEIGHTS:
                total_w = sum(w for _, _, _, w in w_valid)
                if total_w > 0:
                    avg_doa = sum(w / total_w * d for d, _, _, w in w_valid)
                    avg_md  = sum(w / total_w * m for _, m, _, w in w_valid)
                    avg_ma  = sum(w / total_w * a for _, _, a, w in w_valid)
                else:
                    avg_doa = sum(d for d, _, _, _ in sp_fracs) / len(sp_fracs)
                    avg_md  = sum(m for _, m, _, _ in sp_fracs) / len(sp_fracs)
                    avg_ma  = sum(a for _, _, a, _ in sp_fracs) / len(sp_fracs)
            else:
                avg_doa = sum(d for d, _, _, _ in sp_fracs) / len(sp_fracs)
                avg_md  = sum(m for _, m, _, _ in sp_fracs) / len(sp_fracs)
                avg_ma  = sum(a for _, _, a, _ in sp_fracs) / len(sp_fracs)
            SCALE = 10000
            agg_data[cache] = {
                "total":        SCALE,
                "doa":          int(avg_doa * SCALE),
                "mostly_dead":  int(avg_md  * SCALE),
                "mostly_alive": int(avg_ma  * SCALE),
            }
        if agg_data:
            result.append((bm_name, agg_data))
    return result


def _benchmark_weighted_geomean_frac(trace_names, fracs) -> float:
    """Benchmark-weighted geomean of a per-trace fraction list.

    For SPEC traces (simpoint weights found): weighted geomean within each
    benchmark (re-normalised for missing simpoints), then equal-weight geomean
    across benchmarks.  For others: flat equal-weight geomean.
    Clips fracs to a small epsilon before log so zero values don't collapse.
    """
    eps = 1e-6
    by_wl = dict(zip(trace_names, fracs))
    groups: dict = {}
    for wl in by_wl:
        groups.setdefault(benchmark_name(wl), []).append(wl)
    per_bench = []
    for wl_list in groups.values():
        if SPEC_WEIGHTS:
            pairs = [(by_wl[wl], SPEC_WEIGHTS.get(wl)) for wl in wl_list]
            if any(w is not None for _, w in pairs):
                pairs = [(v, w) for v, w in pairs if w is not None]
                total_w = sum(w for _, w in pairs)
                if total_w > 0:
                    per_bench.append(float(np.exp(
                        sum((w / total_w) * np.log(max(v, eps)) for v, w in pairs))))
                    continue
        vals = [by_wl[wl] for wl in wl_list]
        per_bench.append(float(np.exp(np.mean(np.log(np.clip(vals, eps, None))))))
    if not per_bench:
        return 0.0
    return float(np.exp(np.mean(np.log(np.clip(per_bench, eps, None)))))


COLORS = {
    "doa":          "#5B7FA6",   # steel blue
    "mostly_dead":  "#E8A87C",   # soft peach
    "mostly_alive": "#7CB9A8",   # soft teal
}
# Text contrast per segment color
_LABEL_COLOR = {
    "doa":          "white",
    "mostly_dead":  "black",
    "mostly_alive": "white",
}

HIT_HIST_COLORS = [
    "#d73027", "#f46d43", "#fdae61", "#fee08b",
    "#d9ef8b", "#a6d96a", "#66bd63", "#1a9850", "#006837",
]

DISPLAY = {"cpu0_STLB": "STLB", "LLC": "LLC"}
LABELS_NICE = {
    "doa":          "DoA (0 hits)",
    "mostly_dead":  "Mostly-dead",
    "mostly_alive": "Mostly-alive",
}


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_liveness(filepath):
    """Return dict keyed by cache name with doa/mostly_dead/mostly_alive/total/hit_hist."""
    result = {}
    try:
        with open(filepath) as f:
            lines = f.readlines()
    except OSError as e:
        print(f"  ERROR reading {filepath}: {e}", file=sys.stderr)
        return result

    for line in lines:
        m = re.match(
            r"(\S+) LIVENESS EVICTIONS:\s+(\d+)"
            r"\s+DOA:\s+(\d+)\s+\([\d.]+%\)"
            r"\s+MOSTLY_DEAD:\s+(\d+)\s+\([\d.]+%\)"
            r"\s+MOSTLY_ALIVE:\s+(\d+)\s+\([\d.]+%\)",
            line,
        )
        if m:
            name = m.group(1)
            result.setdefault(name, {})["total"]        = int(m.group(2))
            result[name]["doa"]          = int(m.group(3))
            result[name]["mostly_dead"]  = int(m.group(4))
            result[name]["mostly_alive"] = int(m.group(5))

        m2 = re.match(r"(\S+) LIVENESS HIT_HIST:(.*)", line)
        if m2:
            name = m2.group(1)
            hist = [int(tok.group(2))
                    for tok in re.finditer(r"(\d+)\+?:(\d+)", m2.group(2))]
            result.setdefault(name, {})["hit_hist"] = hist

    return result


def locate_file(results_dir, config, trace):
    path = os.path.join(results_dir, config, trace, "champsim.out")
    if os.path.isfile(path):
        return path
    path2 = os.path.join(results_dir, config, "champsim.out")
    if os.path.isfile(path2):
        return path2
    return None


# ── Single-trace plot ─────────────────────────────────────────────────────────

def plot_liveness(data_per_cache, label, out_path, show_hist=True):
    caches = [c for c in ["cpu0_STLB", "LLC"] if c in data_per_cache]
    if not caches:
        sys.exit("ERROR: no liveness data found in the output file.")

    ncols = 2 if (show_hist and any("hit_hist" in data_per_cache[c] for c in caches)) else 1
    fig, axes = plt.subplots(1, ncols, figsize=(7 * ncols, 5))
    if ncols == 1:
        axes = [axes]

    ax = axes[0]
    x = np.arange(len(caches))
    bar_w = 0.45
    bottoms = np.zeros(len(caches))
    pct = {k: [] for k in ("doa", "mostly_dead", "mostly_alive")}
    for c in caches:
        d = data_per_cache[c]
        tot = d.get("total", 1) or 1
        pct["doa"].append(100.0 * d.get("doa", 0) / tot)
        pct["mostly_dead"].append(100.0 * d.get("mostly_dead", 0) / tot)
        pct["mostly_alive"].append(100.0 * d.get("mostly_alive", 0) / tot)

    for key in ("doa", "mostly_dead", "mostly_alive"):
        vals = np.array(pct[key])
        ax.bar(x, vals, bar_w, bottom=bottoms,
               color=COLORS[key], edgecolor="black", linewidth=0.5,
               label=LABELS_NICE[key])
        for xi, (b, v) in enumerate(zip(bottoms, vals)):
            if v > 3:
                ax.text(xi, b + v / 2, f"{v:.1f}%",
                        ha="center", va="center", fontsize=9, fontweight="bold",
                        color=_LABEL_COLOR[key])
        bottoms += vals

    ax.set_xticks(x)
    ax.set_xticklabels([DISPLAY.get(c, c) for c in caches], fontsize=11)
    ax.set_ylabel("% of evictions", fontsize=11)
    ax.set_ylim(0, 102)
    ax.set_title(f"Block/page liveness at eviction\n{label}", fontsize=11)
    ax.legend(loc="upper right", fontsize=9)
    for xi, c in enumerate(caches):
        tot = data_per_cache[c].get("total", 0)
        ax.text(xi, -6, f"n={tot:,}", ha="center", va="top", fontsize=8, color="gray")

    if ncols > 1:
        ax2 = axes[1]
        bin_labels = [str(i) for i in range(8)] + ["8+"]
        n_bins = len(bin_labels)
        group_w = 0.8
        bar_w2 = group_w / max(len(caches), 1)
        offsets = np.linspace(-group_w / 2 + bar_w2 / 2,
                               group_w / 2 - bar_w2 / 2, len(caches))
        for ci, c in enumerate(caches):
            hist = data_per_cache[c].get("hit_hist", [])
            if not hist:
                continue
            hist = (hist + [0] * n_bins)[:n_bins]
            xs = np.arange(n_bins) + offsets[ci]
            ax2.bar(xs, hist, bar_w2,
                    color=[HIT_HIST_COLORS[i % len(HIT_HIST_COLORS)] for i in range(n_bins)],
                    edgecolor="black", linewidth=0.4, alpha=0.85,
                    label=DISPLAY.get(c, c))
        ax2.set_yscale("log")
        ax2.yaxis.set_major_formatter(mticker.LogFormatter())
        ax2.set_xticks(range(n_bins))
        ax2.set_xticklabels(bin_labels, fontsize=10)
        ax2.set_xlabel("Hit count at eviction", fontsize=11)
        ax2.set_ylabel("# evictions (log scale)", fontsize=11)
        ax2.set_title(f"Hit-count histogram at eviction\n{label}", fontsize=11)
        ax2.legend(fontsize=9)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved: {out_path}")


# ── Multi-workload plot ───────────────────────────────────────────────────────

def geomean(values):
    """Geometric mean, clipping zeros to a small epsilon."""
    arr = np.clip(np.asarray(values, dtype=float), 1e-9, None)
    return float(np.exp(np.mean(np.log(arr))))


def plot_liveness_per_workload(trace_data, label, out_path, cache_filter=None):
    """
    trace_data : list of (trace_name, data_per_cache).
    SPEC simpoints are aggregated into parent benchmarks before display.
    Only the top MAX_WORKLOADS benchmarks/workloads (by dead fraction) are shown.
    Produces one panel per cache with one stacked bar per workload + geomean.
    """
    # Aggregate SPEC simpoints into parent benchmarks
    trace_data = _aggregate_spec_benchmarks(trace_data)

    all_caches = ["cpu0_STLB", "LLC"]
    if cache_filter:
        all_caches = [c for c in all_caches if DISPLAY.get(c, c) == cache_filter]
    caches = [c for c in all_caches if any(c in d for _, d in trace_data)]
    if not caches:
        sys.exit("ERROR: no liveness data found.")

    # Keep full list for geomean; select diverse subset for display
    all_trace_data = trace_data

    if len(trace_data) > MAX_WORKLOADS:
        def _fvec(item):
            return [
                (item[1].get(c, {}).get("doa", 0) + item[1].get(c, {}).get("mostly_dead", 0))
                / max(item[1].get(c, {}).get("total", 0), 1)
                for c in caches
            ]
        sel = _diverse_select(trace_data, _fvec, MAX_WORKLOADS)
        trace_data = [trace_data[i] for i in sel]

    # Sort selected subset by descending dead fraction so bars read coherently
    ref_cache = caches[0]
    def dead_key(item):
        d = item[1].get(ref_cache, {})
        tot = d.get("total", 0) or 1
        return (d.get("doa", 0) + d.get("mostly_dead", 0)) / tot
    trace_data = sorted(trace_data, key=dead_key, reverse=True)

    trace_names_all = [t for t, _ in all_trace_data]   # for geomean weighting
    trace_names = [t for t, _ in trace_data]
    n = len(trace_names)
    xlabels = trace_names + ["GeoMean"]
    x = np.arange(len(xlabels))

    nrows = len(caches)
    fig_w = max(10, n * 0.50 + 3)
    fig, axes = plt.subplots(nrows, 1, figsize=(fig_w, 5 * nrows), squeeze=False)

    for row, cache in enumerate(caches):
        ax = axes[row][0]

        # Per-workload fracs for displayed workloads only
        pct = {k: [] for k in ("doa", "mostly_dead", "mostly_alive")}
        for _, data in trace_data:
            d = data.get(cache, {})
            tot = d.get("total", 0) or 1
            pct["doa"].append(100.0 * d.get("doa", 0) / tot)
            pct["mostly_dead"].append(100.0 * d.get("mostly_dead", 0) / tot)
            pct["mostly_alive"].append(100.0 * d.get("mostly_alive", 0) / tot)

        # Geomean computed over ALL workloads (not just the displayed subset)
        all_pct = {k: [] for k in ("doa", "mostly_dead", "mostly_alive")}
        for _, data in all_trace_data:
            d = data.get(cache, {})
            tot = d.get("total", 0) or 1
            all_pct["doa"].append(100.0 * d.get("doa", 0) / tot)
            all_pct["mostly_dead"].append(100.0 * d.get("mostly_dead", 0) / tot)
            all_pct["mostly_alive"].append(100.0 * d.get("mostly_alive", 0) / tot)

        # Append benchmark-weighted geometric mean for each class (over all workloads)
        for key in pct:
            pct[key].append(
                _benchmark_weighted_geomean_frac(trace_names_all, all_pct[key]))
        # Normalise geomean so the geomean bar sums to 100%
        gm_sum = sum(pct[k][-1] for k in ("doa", "mostly_dead", "mostly_alive"))
        if gm_sum > 0:
            for k in ("doa", "mostly_dead", "mostly_alive"):
                pct[k][-1] = pct[k][-1] / gm_sum * 100.0

        bar_w = 0.7
        bottoms = np.zeros(len(xlabels))
        for key in ("doa", "mostly_dead", "mostly_alive"):
            vals = np.array(pct[key])
            ax.bar(x, vals, bar_w, bottom=bottoms,
                   color=COLORS[key], edgecolor="black", linewidth=0.4,
                   label=LABELS_NICE[key])
            tc = _LABEL_COLOR[key]
            # Label every segment (workload bars + geomean bar)
            for xi in range(len(vals)):
                v = vals[xi]
                b = bottoms[xi]
                fs = 10 if xi == len(vals) - 1 else 8   # larger font for geomean
                if v > 5:
                    ax.text(x[xi], b + v / 2, f"{v:.0f}%",
                            ha="center", va="center", fontsize=fs,
                            fontweight="bold", color=tc)
            bottoms += vals

        # Separator before geomean
        ax.axvline(n - 0.5, color="black", linewidth=1.0, linestyle="--")

        ax.set_xticks(x)
        ax.set_xticklabels(xlabels, rotation=40, ha="right", fontsize=9)
        ax.set_ylabel("% of evictions", fontsize=11)
        ax.set_ylim(0, 105)
        n_shown = len(trace_names)
        ax.set_title(
            f"{DISPLAY.get(cache, cache)} liveness at eviction — {label}\n"
            f"({n_shown} most diverse of {len(all_trace_data)}; geomean over all)",
            fontsize=13)
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(axis="y", alpha=0.25)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved: {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results_dir", nargs="?", default=None)
    parser.add_argument("--file",    default=None, help="Direct path to champsim.out")
    parser.add_argument("--trace",   default=None, help="Single trace name to plot")
    parser.add_argument("--config",  default="lru")
    parser.add_argument("--label",   default=None, help="Display name for the suite (overrides directory name)")
    parser.add_argument("--cache",   default=None, choices=["LLC", "STLB"],
                        help="Cache to show in multi-workload mode (default: both)")
    parser.add_argument("--out",     default=None)
    parser.add_argument("--no-hist", action="store_true", dest="no_hist")
    args = parser.parse_args()

    if args.file:
        data = parse_liveness(args.file)
        if not data:
            sys.exit(f"ERROR: no LIVENESS lines found in {args.file}")
        label = os.path.basename(os.path.dirname(args.file))
        out_path = args.out or f"liveness_{label}.png"
        plot_liveness(data, label, out_path, show_hist=not args.no_hist)
        return

    if not args.results_dir:
        parser.print_help()
        sys.exit(1)

    base = args.results_dir.rstrip("/")
    label = args.label or os.path.basename(base)
    config_dir = os.path.join(base, args.config)
    if not os.path.isdir(config_dir):
        sys.exit(f"ERROR: config dir not found: {config_dir}")

    plots_dir = os.path.join(base, "plots")
    os.makedirs(plots_dir, exist_ok=True)

    candidates = sorted(d for d in os.listdir(config_dir)
                        if os.path.isdir(os.path.join(config_dir, d)))

    # Single-trace mode
    if args.trace or len(candidates) <= 1:
        trace = args.trace or (candidates[0] if candidates else None)
        filepath = locate_file(base, args.config, trace) if trace else \
                   os.path.join(config_dir, "champsim.out")
        if not filepath or not os.path.isfile(filepath):
            sys.exit(f"ERROR: champsim.out not found at {filepath}")
        data = parse_liveness(filepath)
        if not data:
            sys.exit(f"ERROR: no LIVENESS lines found in {filepath}")
        out_path = args.out or os.path.join(plots_dir, f"liveness_{args.config}_{trace}.png")
        plot_liveness(data, f"{label} / {trace}", out_path, show_hist=not args.no_hist)
        return

    # Multi-workload mode
    print(f"Plotting {len(candidates)} workloads from {config_dir} ...")
    trace_data = []
    for trace in candidates:
        filepath = locate_file(base, args.config, trace)
        if not filepath:
            print(f"  WARNING: no champsim.out for {trace} — skipped")
            continue
        data = parse_liveness(filepath)
        if not data:
            print(f"  WARNING: no LIVENESS data in {filepath} — skipped")
            continue
        trace_data.append((trace, data))

    if not trace_data:
        sys.exit("ERROR: no usable data found.")

    out_path = args.out or os.path.join(plots_dir, f"liveness_{args.config}.png")
    plot_liveness_per_workload(trace_data, f"{label} / {args.config}",
                               out_path, cache_filter=args.cache)


if __name__ == "__main__":
    main()
