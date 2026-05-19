#!/usr/bin/env python3
"""plot_policy_comparison.py — IPC speedup and MPKI bar charts across policies.

Compares replacement policies from a sweep_policy.sh results directory.
All IPC values are normalised to a baseline policy (default: lru).

Usage
-----
    python3 scripts/analysis/plot_policy_comparison.py <results_dir> \\
        [--baseline lru] [--out <prefix>]

    <results_dir> must contain subdirectories named after the policies, e.g.:
        lru/  srrip/  drrip/  lru_mid/  lru_pred/  lru_mid_pred/ ...

Outputs (saved alongside --out prefix)
-------
    <out>_ipc.png    — IPC speedup vs baseline, one bar per policy per workload
    <out>_mpki.png   — STLB and LLC MPKI side-by-side, one bar per policy per workload
"""

import argparse
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

from champsim_utils import geomean
from colors import POLICY_COLORS, POLICY_HATCHES
from spec_weights import benchmark_name, load_spec_weights


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_file(path: Path):
    """Return dict with ipc, instrs, stlb_miss, llc_miss, or None values."""
    result = {"ipc": None, "instrs": None, "stlb_miss": None, "llc_miss": None}
    in_roi = False
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return result
    for line in text.splitlines():
        if "Region of Interest Statistics" in line:
            in_roi = True
        if not in_roi:
            continue
        if result["ipc"] is None and "cumulative IPC:" in line:
            m = re.search(r"cumulative IPC:\s+([0-9.]+)", line)
            if m:
                result["ipc"] = float(m.group(1))
        if result["instrs"] is None and "cumulative IPC:" in line:
            m = re.search(r"instructions:\s+(\d+)", line)
            if m:
                result["instrs"] = int(m.group(1))
        if result["stlb_miss"] is None and re.match(r"cpu0_STLB TOTAL\s+ACCESS:", line):
            m = re.search(r"MISS:\s+(\d+)", line)
            if m:
                result["stlb_miss"] = int(m.group(1))
        if result["llc_miss"] is None and re.match(r"LLC TOTAL\s+ACCESS:", line):
            m = re.search(r"MISS:\s+(\d+)", line)
            if m:
                result["llc_miss"] = int(m.group(1))
    return result


def load_policy(policy_dir: Path):
    """Return dict { workload: parsed_stats } for all champsim.out files."""
    files = sorted(policy_dir.glob("*/champsim.out"))  # cluster layout
    nested = True
    if not files:
        files = sorted(policy_dir.glob("*.out"))        # flat layout
        nested = False
    rows = {}
    for f in files:
        wl = f.parent.name if nested else f.stem
        rows[wl] = parse_file(f)
    return rows


# ── Helpers ───────────────────────────────────────────────────────────────────



MAX_WORKLOADS = 15   # maximum per-workload groups shown in the chart


def _diverse_select(items, feature_fn, k):
    """Greedy farthest-point sampling in normalised feature space.  Returns indices."""
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


def aggregate_to_benchmarks(workloads, matrices, weights, use_geomean=True):
    """Aggregate SPEC simpoints into parent benchmarks across all policy matrices.

    For SPEC traces: weighted geomean (IPC ratios) or weighted arithmetic mean
    (absolute MPKI) within each benchmark.  Non-SPEC traces: kept as-is.
    Returns (new_workload_names, new_matrices).
    """
    groups: dict = {}
    for wi, wl in enumerate(workloads):
        groups.setdefault(benchmark_name(wl), []).append((wi, wl))

    new_workloads = []
    new_matrices = [[] for _ in matrices]
    for bm_name in sorted(groups.keys()):
        items = groups[bm_name]
        new_workloads.append(bm_name)
        for pi, matrix in enumerate(matrices):
            if len(items) == 1:
                new_matrices[pi].append(matrix[items[0][0]])
                continue
            raw_pairs = [(matrix[wi], weights.get(wl) if weights else None)
                         for wi, wl in items]
            valid = [(v, w) for v, w in raw_pairs if v is not None]
            if not valid:
                new_matrices[pi].append(None)
                continue
            if use_geomean:
                pos = [(v, w) for v, w in valid if v > 0]
                if not pos:
                    new_matrices[pi].append(None)
                    continue
                w_pos = [(v, w) for v, w in pos if w is not None]
                if w_pos and weights:
                    total_w = sum(w for _, w in w_pos)
                    if total_w > 0:
                        new_matrices[pi].append(float(np.exp(
                            sum(w / total_w * np.log(v) for v, w in w_pos))))
                        continue
                new_matrices[pi].append(float(np.exp(
                    np.mean(np.log([v for v, _ in pos])))))
            else:
                w_all = [(v, w) for v, w in valid if w is not None]
                if w_all and weights:
                    total_w = sum(w for _, w in w_all)
                    if total_w > 0:
                        new_matrices[pi].append(
                            sum(w / total_w * v for v, w in w_all))
                        continue
                new_matrices[pi].append(
                    sum(v for v, _ in valid) / len(valid))
    return new_workloads, new_matrices


def benchmark_geomean(values_by_wl: dict, weights: "dict | None" = None) -> "float | None":
    """Benchmark-weighted geomean using simpoint weights when available.

    Within each benchmark: weighted geometric mean (re-normalised for missing
    simpoints).  Falls back to equal weights.  Across benchmarks: equal-weight
    geometric mean.
    """
    groups: dict = {}
    for wl, v in values_by_wl.items():
        if v is not None and v > 0:
            groups.setdefault(benchmark_name(wl), []).append(wl)
    if not groups:
        return None
    per_bench = []
    for wl_list in groups.values():
        if weights:
            pairs = [(values_by_wl[wl], weights.get(wl)) for wl in wl_list]
            if any(w is not None for _, w in pairs):
                pairs = [(v, w) for v, w in pairs if v is not None and v > 0 and w is not None]
                total_w = sum(w for _, w in pairs)
                if total_w > 0:
                    per_bench.append(float(np.exp(sum((w / total_w) * np.log(v) for v, w in pairs))))
                    continue
        per_bench.append(geomean([values_by_wl[wl] for wl in wl_list]))
    return geomean(per_bench)


def _arith_mean(values_by_wl: dict, weights=None) -> "float | None":
    """Arithmetic mean across workloads — used for MPKI reduction percentages."""
    vals = [v for v in values_by_wl.values() if v is not None and np.isfinite(v)]
    return float(np.mean(vals)) if vals else None


# ── Plot helpers ──────────────────────────────────────────────────────────────

# Linestyle mapped from hatch so LLC-only vs LLC+STLB variants remain distinct.
_HATCH_LS = {
    "":   "-",
    "//": "--",
    "xx": "-.",
    "..": ":",
    "oo": (0, (3, 1, 1, 1, 1, 1)),  # dash-dot-dot
}
_MARKERS = ["o", "s", "^", "D", "v", "p", "<", ">", "h", "P", "X", "H", "d", "+", "x"]


def _line_group(ax, workloads, policy_names, matrix, ylabel, title,
                baseline_val=1.0, ref_line=True, weights=None,
                policy_keys=None, agg_fn=None):
    """Line+marker chart — one line per policy, one x-position per workload.

    Replaces _bar_group for per-workload views where many policies would produce
    unreadably thin bars.  Geomean is drawn as a larger standalone marker after
    a visual gap.
    """
    if policy_keys is None:
        policy_keys = policy_names
    n_policies = len(policy_names)
    n_wl = len(workloads)

    _agg = agg_fn or benchmark_geomean
    gm = [_agg({workloads[w]: matrix[p][w] for w in range(n_wl)}, weights)
          for p in range(n_policies)]

    gap = 1.5
    x_wl = np.arange(n_wl)
    x_gm = n_wl + gap

    _fallback = ["#888888", "#AAAAAA", "#CCCCCC", "#444444", "#666666"]
    for pi, (pname, pkey) in enumerate(zip(policy_names, policy_keys)):
        color = POLICY_COLORS.get(pkey, _fallback[pi % len(_fallback)])
        hatch = POLICY_HATCHES.get(pkey, "")
        ls    = _HATCH_LS.get(hatch, "-")
        mk    = _MARKERS[pi % len(_MARKERS)]
        ys    = [matrix[pi][w] if matrix[pi][w] is not None else np.nan
                 for w in range(n_wl)]
        ax.plot(x_wl, ys, color=color, linestyle=ls, marker=mk,
                markersize=5, linewidth=1.2, label=pname, alpha=0.9,
                markeredgecolor="white", markeredgewidth=0.4)
        if gm[pi] is not None:
            ax.plot(x_gm, gm[pi], color=color, linestyle="none",
                    marker=mk, markersize=9,
                    markeredgecolor="black", markeredgewidth=0.8)

    if ref_line:
        ax.axhline(baseline_val, color="black", linewidth=0.8,
                   linestyle="--", zorder=0)
    ax.axvline(n_wl + gap / 2, color="gray", linewidth=0.8,
               linestyle=":", zorder=0)

    all_x = list(x_wl) + [x_gm]
    all_l = list(workloads) + ["Geomean"]
    ax.set_xticks(all_x)
    ax.set_xticklabels(all_l, rotation=35, ha="right", fontsize=8)
    for tick, lbl in zip(ax.get_xticklabels(), all_l):
        if lbl == "Geomean":
            tick.set_fontweight("bold")

    all_vals = [v for row in matrix for v in row if v is not None]
    all_vals += [g for g in gm if g is not None]
    if ref_line:
        all_vals.append(baseline_val)
    if all_vals:
        lo, hi = min(all_vals), max(all_vals)
        span = max(hi - lo, 1e-6)
        ax.set_ylim(lo - 0.15 * span, hi + 0.15 * span)

    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_title(title, fontsize=13)
    ax.set_xlim(-0.7, x_gm + 0.7)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.85, ncol=2)
    ax.grid(axis="y", alpha=0.3, linewidth=0.5)
    ax.grid(axis="x", alpha=0.15, linewidth=0.5)


def _bar_group(ax, workloads, policy_names, matrix, ylabel, title,
               baseline_val=1.0, ref_line=True, weights=None,
               policy_keys=None, agg_fn=None):
    """Grouped bar chart: one x-position per workload, one bar per policy.

    IPC matrices contain ratios (baseline_val=1.0); subtract baseline and
    multiply by 100 to get speedup %.  MPKI matrices contain percentages
    (baseline_val=0.0); used as-is.
    """
    if policy_keys is None:
        policy_keys = policy_names
    n_policies = len(policy_names)
    n_wl = len(workloads)

    _agg = agg_fn or benchmark_geomean
    gm = [_agg({workloads[w]: matrix[p][w] for w in range(n_wl)}, weights)
          for p in range(n_policies)]

    scale = 100.0 if abs(baseline_val - 1.0) < 1e-6 else 1.0

    bar_w = max(0.08, min(0.20, 0.82 / n_policies))
    step  = bar_w + 0.02
    offsets = [(j - (n_policies - 1) / 2) * step for j in range(n_policies)]

    gap  = 1.5
    x_wl = np.arange(n_wl)
    x_gm = float(n_wl) + gap

    _fallback = ["#888888", "#AAAAAA", "#CCCCCC", "#444444", "#666666"]
    for pi, (pname, pkey) in enumerate(zip(policy_names, policy_keys)):
        color = POLICY_COLORS.get(pkey, _fallback[pi % len(_fallback)])
        hatch = POLICY_HATCHES.get(pkey, "")
        ys = [((matrix[pi][w] or baseline_val) - baseline_val) * scale
              if matrix[pi][w] is not None else 0.0
              for w in range(n_wl)]
        ax.bar(x_wl + offsets[pi], ys, bar_w,
               color=color, hatch=hatch, edgecolor="black", linewidth=0.3,
               label=pname, zorder=3)
        if gm[pi] is not None:
            gm_pct = (gm[pi] - baseline_val) * scale
            ax.bar(x_gm + offsets[pi], gm_pct, bar_w,
                   color=color, hatch=hatch, edgecolor="black", linewidth=0.8,
                   zorder=3)
            yoff = 0.3 if gm_pct >= 0 else -0.3
            ax.text(x_gm + offsets[pi], gm_pct + yoff,
                    f"{gm_pct:+.1f}%", ha="center",
                    va="bottom" if gm_pct >= 0 else "top",
                    fontsize=6.5, rotation=90)

    if ref_line:
        ax.axhline(0.0, color="black", linewidth=0.8, linestyle="--", zorder=0)
    ax.axvline(n_wl + gap / 2, color="gray", linewidth=0.8, linestyle=":", zorder=0)

    all_x = list(x_wl) + [x_gm]
    all_l = list(workloads) + ["Geomean"]
    ax.set_xticks(all_x)
    ax.set_xticklabels(all_l, rotation=35, ha="right", fontsize=8)
    for tick, lbl in zip(ax.get_xticklabels(), all_l):
        if lbl == "Geomean":
            tick.set_fontweight("bold")

    all_pcts = [((matrix[p][w] or baseline_val) - baseline_val) * scale
                for p in range(n_policies) for w in range(n_wl)
                if matrix[p][w] is not None]
    all_pcts += [(g - baseline_val) * scale for g in gm if g is not None]
    all_pcts.append(0.0)
    if all_pcts:
        lo, hi = min(all_pcts), max(all_pcts)
        span = max(hi - lo, 1e-6)
        ax.set_ylim(lo - 0.12 * span, hi + 0.35 * span)

    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_title(title, fontsize=13)
    ax.set_xlim(-0.7, x_gm + 0.7)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.85, ncol=2)
    ax.grid(axis="y", alpha=0.3, linewidth=0.5)


def _iqr_ylim(vals, ref=None, pad=0.08):
    """Tight y-limits via IQR outlier clipping.  ref value is always included."""
    clean = sorted(v for v in vals if v is not None and np.isfinite(v))
    if not clean:
        return None, None
    q1, q3 = np.percentile(clean, 25), np.percentile(clean, 75)
    iqr = q3 - q1
    if iqr > 1e-8:
        inner = [v for v in clean if q1 - 1.5 * iqr <= v <= q3 + 1.5 * iqr]
    else:
        inner = clean
    if ref is not None:
        inner = inner + [ref]
    if not inner:
        inner = clean
    lo, hi = min(inner), max(inner)
    span = max(hi - lo, 1e-8)
    return lo - pad * span, hi + pad * span


def _annotate_clipped(ax, y_lo, y_hi, fmt="%.3f"):
    """For every bar patch clipped by [y_lo, y_hi], write the actual value in plain
    horizontal text just outside the axis edge — no slashes, clean like Fig 9 style."""
    span = y_hi - y_lo
    for patch in ax.patches:
        h = patch.get_height()
        if h <= 0:
            continue
        b = patch.get_y()
        top = b + h
        x = patch.get_x() + patch.get_width() / 2
        if top > y_hi:
            ax.text(x, y_hi + 0.02 * span, fmt % top,
                    ha="center", va="bottom", fontsize=8,
                    fontweight="bold", color="black", clip_on=False)
        elif b < y_lo:
            ax.text(x, y_lo - 0.02 * span, fmt % b,
                    ha="center", va="top", fontsize=8,
                    fontweight="bold", color="black", clip_on=False)


def _bar_group(ax, workloads, policy_names, matrix, ylabel, title,
               baseline_val=1.0, ref_line=True, weights=None, clip_fmt="%.3f",
               policy_keys=None, agg_fn=None):
    """Draw a grouped bar chart.

    matrix[p][w] = value for policy p, workload w (None = missing).
    A geomean bar is appended after a small gap.
    The y-axis is zoomed in to the actual data range so small differences
    between policies are visible.
    policy_keys: canonical policy names for color/hatch lookup (defaults to policy_names).
    """
    if policy_keys is None:
        policy_keys = policy_names
    n_policies = len(policy_names)
    n_wl = len(workloads)

    # Benchmark-weighted geomean column (uses simpoint weights when available)
    _agg = agg_fn or benchmark_geomean
    gm = []
    for p in range(n_policies):
        by_wl = {workloads[w]: matrix[p][w] for w in range(n_wl)}
        gm.append(_agg(by_wl, weights))

    gap = 1.5
    group_w = 0.8
    bar_w = group_w / n_policies
    x_wl = np.arange(n_wl)
    x_gm = n_wl + gap

    _fallback_colors = ["#888888", "#AAAAAA", "#CCCCCC", "#444444", "#666666"]
    for pi, (pname, pkey) in enumerate(zip(policy_names, policy_keys)):
        offsets = (np.arange(n_policies) - (n_policies - 1) / 2) * bar_w
        x_pos_wl = x_wl + offsets[pi]
        x_pos_gm = x_gm + offsets[pi]

        color  = POLICY_COLORS.get(pkey, _fallback_colors[pi % len(_fallback_colors)])
        hatch  = POLICY_HATCHES.get(pkey, "")
        heights_wl = [matrix[pi][w] if matrix[pi][w] is not None else 0
                      for w in range(n_wl)]
        ax.bar(x_pos_wl, heights_wl, bar_w * 0.95,
               color=color, hatch=hatch, edgecolor="black", linewidth=0.4,
               label=pname)
        if gm[pi] is not None:
            ax.bar(x_pos_gm, gm[pi], bar_w * 0.95,
                   color=color, hatch=hatch, edgecolor="black", linewidth=0.4)

    if ref_line:
        ax.axhline(baseline_val, color="black", linewidth=0.8, linestyle="--", zorder=1)

    ax.axvline(n_wl + gap / 2, color="gray", linewidth=0.8, linestyle=":", zorder=1)

    all_x_ticks = list(x_wl) + [x_gm]
    all_x_labels = list(workloads) + ["Geomean"]
    ax.set_xticks(all_x_ticks)
    ax.set_xticklabels(all_x_labels, rotation=35, ha="right", fontsize=8)
    for tick, lbl in zip(ax.get_xticklabels(), all_x_labels):
        if lbl == "Geomean":
            tick.set_fontweight("bold")

    # Full-range y-limits with moderate padding
    all_vals = [v for row in matrix for v in row if v is not None]
    all_vals += [g for g in gm if g is not None]
    if ref_line:
        all_vals.append(baseline_val)
    if all_vals:
        lo, hi = min(all_vals), max(all_vals)
        span = max(hi - lo, 1e-6)
        ax.set_ylim(lo - 0.15 * span, hi + 0.15 * span)

    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_title(title, fontsize=13)
    ax.set_xlim(-0.7, x_gm + 0.7)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.85, ncol=2)
    ax.grid(axis="y", alpha=0.3, linewidth=0.5)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("results_dir", help="Top-level sweep_policy results directory")
    ap.add_argument("--baseline", default="lru",
                    help="Policy subdirectory to normalise against (default: lru)")
    ap.add_argument("--out", default="policy_comparison",
                    help="Output path prefix (default: policy_comparison)")
    ap.add_argument("--label", default=None,
                    help="Human-readable suite label for plot titles (e.g. 'SPEC (DPC3)')")
    ap.add_argument("--suffix", default="",
                    help="Suffix appended to every policy dir name (e.g. '_paper_pref')")
    ap.add_argument("--exclude", nargs="*", default=[],
                    help="Exclude policies whose name contains any of these substrings (e.g. --exclude drrip)")
    ap.add_argument("--include", nargs="*", default=None,
                    help="If given, only show these exact policy names (takes priority over --exclude)")
    ap.add_argument("--max-workloads", type=int, default=None,
                    help="Maximum number of per-workload groups to show (default: show all).")
    ap.add_argument("--weights-dir", default=None,
                    help="Directory with per-benchmark simpoint weight files. "
                         "Default: auto-detected from known location.")
    args = ap.parse_args()

    results_dir = Path(args.results_dir)
    if not results_dir.is_dir():
        sys.exit(f"ERROR: not a directory: {results_dir}")
    suite_label = args.label or results_dir.name

    # Discover policies in a fixed display order
    # lru is the baseline — shown as a reference line, not as a redundant bar
    sfx = args.suffix  # e.g. "" or "_paper_pref"
    ordered = ["srrip", "srrip_both", "lru_mid", "lru_mid_both", "ipv", "ipv_both",
               "srrip_live", "stlb_srrip_live", "srrip_live_both",
               "ipv_live", "ipv_live_both",
               "stlb_ipv", "stlb_ipv_live",
               "lru_dp_only", "lru_pred", "srrip_pred", "lru_mid_pred",
               "stlb_srrip", "stlb_lru_mid"]
    display_labels = {
        "srrip":           "SRRIP",
        "srrip_both":      "SRRIP (LLC+STLB)",
        "srrip_live":      "srrip_live (LLC)",
        "lru_mid":         "lru_mid",
        "lru_mid_both":    "lru_mid (LLC+STLB)",
        "ipv":             "IPV (LLC)",
        "ipv_both":        "IPV (LLC+STLB)",
        "ipv_live":        "ipv_live (LLC)",
        "ipv_live_both":   "ipv_live (LLC+STLB)",
        "stlb_ipv":        "IPV (STLB)",
        "stlb_ipv_live":   "ipv_live (STLB)",
        "srrip_live_both": "srrip_live (LLC+STLB)",
        "lru_dp_only":     "lru+dp",
        "lru_pred":        "lru+pred",
        "srrip_pred":      "srrip+pred",
        "lru_mid_pred":    "lru_mid+pred",
        "stlb_srrip":      "STLB-SRRIP",
        "stlb_srrip_live": "srrip_live (STLB)",
        "stlb_lru_mid":    "STLB-lru_mid",
    }

    if args.include is not None:
        present = [p for p in ordered
                   if (results_dir / (p + sfx)).is_dir()
                   and p in args.include]
    else:
        present = [p for p in ordered
                   if (results_dir / (p + sfx)).is_dir()
                   and not any(s in p for s in args.exclude)]
    if not present:
        sys.exit(f"ERROR: no recognised policy subdirs found in {results_dir}")
    baseline_dir = results_dir / (args.baseline + sfx)
    if not baseline_dir.is_dir():
        sys.exit(f"ERROR: baseline policy '{args.baseline}{sfx}' not found in {results_dir}")

    print(f"Policies found: {present}")

    # Load simpoint weights
    _default_weights = Path(__file__).parents[2] / ".." / "ChampSim-dev" / "trace-files" / "SPEC2006_weights"
    weights_dir = Path(args.weights_dir) if args.weights_dir else _default_weights.resolve()
    weights = load_spec_weights(weights_dir)
    if weights:
        print(f"Loaded simpoint weights for "
              f"{len(set(benchmark_name(k) for k in weights))} benchmarks")
    else:
        print(f"WARNING: no simpoint weights found — using equal weights")

    # Load all data (baseline always loaded, even though it's not plotted as a bar)
    data = {}
    if args.baseline not in present:
        print(f"  Loading {args.baseline}{sfx} (baseline) ...")
        data[args.baseline] = load_policy(baseline_dir)
    for policy in present:
        print(f"  Loading {policy}{sfx} ...")
        data[policy] = load_policy(results_dir / (policy + sfx))

    # Union of workloads present in the baseline
    workloads = sorted(data[args.baseline].keys())
    if not workloads:
        sys.exit(f"ERROR: no workloads found under {baseline_dir}")
    print(f"  {len(workloads)} workloads from baseline '{args.baseline}'")

    policy_labels = [display_labels.get(p, p) for p in present]

    # ── IPC speedup ───────────────────────────────────────────────────────────
    # matrix[pi][wi] = IPC_policy / IPC_baseline
    ipc_matrix = []
    for policy in present:
        row = []
        for wl in workloads:
            base_stats = data[args.baseline].get(wl, {})
            pol_stats  = data[policy].get(wl, {})
            base_ipc = base_stats.get("ipc")
            pol_ipc  = pol_stats.get("ipc")
            if base_ipc and pol_ipc and base_ipc > 0:
                row.append(pol_ipc / base_ipc)
            else:
                row.append(None)
        ipc_matrix.append(row)

    # Aggregate SPEC simpoints into parent benchmarks (weighted geomean of ratios)
    workloads_agg, ipc_matrix_agg = aggregate_to_benchmarks(
        workloads, ipc_matrix, weights, use_geomean=True)
    print(f"  {len(workloads_agg)} benchmarks/workloads after simpoint aggregation")

    n_total = len(workloads_agg)
    max_wl  = args.max_workloads if args.max_workloads is not None else n_total

    # Optionally select a diverse subset
    if n_total > max_wl:
        items_agg = list(range(n_total))
        def _fvec(wi):
            return [ipc_matrix_agg[pi][wi] or 1.0 for pi in range(len(present))]
        sel = _diverse_select(items_agg, _fvec, max_wl)
    else:
        sel = list(range(n_total))

    # Sort selected by descending IPC speedup of the best pred policy for readability
    pred_present = [p for p in present if p.endswith("_pred")]
    if pred_present:
        best_pred_idx = present.index(pred_present[-1])
        sel.sort(key=lambda i: ipc_matrix_agg[best_pred_idx][i] or 0, reverse=True)
    workloads_sorted = [workloads_agg[i] for i in sel]
    ipc_matrix_sorted = [[row[i] for i in sel] for row in ipc_matrix_agg]
    order = sel  # used below for MPKI alignment

    out_obj = Path(args.out)
    out_dir = out_obj.parent
    out_stem = out_obj.stem

    n_shown = len(workloads_sorted)
    title_suffix = (f"({n_shown} most diverse of {n_total}; geomean over all)"
                    if n_shown < n_total else f"({n_total} benchmarks/workloads)")
    n_pol = len(present)
    fig_w = max(10, n_shown * max(0.75, 0.12 * n_pol) + 3)
    fig, ax = plt.subplots(figsize=(fig_w, 5))
    _bar_group(ax, workloads_sorted, policy_labels, ipc_matrix_sorted,
               ylabel=f"IPC speedup vs {args.baseline} (%)",
               title=(f"IPC speedup vs {args.baseline} — {suite_label}\n"
                      f"{title_suffix}"),
               baseline_val=1.0, ref_line=True, weights=weights,
               policy_keys=present)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%+.1f%%"))
    fig.tight_layout()
    ipc_out = str(out_dir / f"{out_stem}_ipc.png")
    fig.savefig(ipc_out, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {ipc_out}")

    # ── MPKI ──────────────────────────────────────────────────────────────────
    # Relative MPKI reduction vs LRU baseline: (base - policy) / base * 100
    def mpki(stats, key):
        instrs = stats.get("instrs")
        misses = stats.get(key)
        if instrs and misses is not None and instrs > 0:
            return misses / (instrs / 1000)
        return None

    base_stlb = {wl: mpki(data[args.baseline].get(wl, {}), "stlb_miss") for wl in workloads}
    base_llc  = {wl: mpki(data[args.baseline].get(wl, {}), "llc_miss")  for wl in workloads}

    stlb_matrix_raw = []
    llc_matrix_raw  = []
    for policy in present:
        stlb_row, llc_row = [], []
        for wl in workloads:
            s = data[policy].get(wl, {})
            b_s = base_stlb[wl];  p_s = mpki(s, "stlb_miss")
            b_l = base_llc[wl];   p_l = mpki(s, "llc_miss")
            stlb_row.append((b_s - p_s) / b_s * 100 if (b_s and b_s > 0 and p_s is not None) else None)
            llc_row.append( (b_l - p_l) / b_l * 100 if (b_l and b_l > 0 and p_l is not None) else None)
        stlb_matrix_raw.append(stlb_row)
        llc_matrix_raw.append(llc_row)

    # Aggregate to benchmarks (arithmetic mean of reduction percentages)
    _, stlb_matrix_agg = aggregate_to_benchmarks(
        workloads, stlb_matrix_raw, weights, use_geomean=False)
    _, llc_matrix_agg  = aggregate_to_benchmarks(
        workloads, llc_matrix_raw, weights, use_geomean=False)

    # Apply same selection and sort order as IPC
    stlb_matrix = [[row[i] for i in order] for row in stlb_matrix_agg]
    llc_matrix  = [[row[i] for i in order] for row in llc_matrix_agg]

    fig, axes = plt.subplots(2, 1, figsize=(fig_w, 9))
    _bar_group(axes[0], workloads_sorted, policy_labels, stlb_matrix,
               ylabel="STLB MPKI reduction vs LRU (%)",
               title=(f"STLB MPKI reduction vs LRU — {suite_label}\n"
                      f"({n_shown} most diverse of {n_total})"),
               baseline_val=0.0, ref_line=True, weights=weights,
               policy_keys=present, agg_fn=_arith_mean)
    axes[0].yaxis.set_major_formatter(mticker.FormatStrFormatter("%+.1f%%"))

    _bar_group(axes[1], workloads_sorted, policy_labels, llc_matrix,
               ylabel="LLC MPKI reduction vs LRU (%)",
               title=(f"LLC MPKI reduction vs LRU — {suite_label}\n"
                      f"({n_shown} most diverse of {n_total})"),
               baseline_val=0.0, ref_line=True, weights=weights,
               policy_keys=present, agg_fn=_arith_mean)
    axes[1].yaxis.set_major_formatter(mticker.FormatStrFormatter("%+.1f%%"))

    fig.tight_layout()
    mpki_out = str(out_dir / f"{out_stem}_mpki.png")
    fig.savefig(mpki_out, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {mpki_out}")


if __name__ == "__main__":
    main()
