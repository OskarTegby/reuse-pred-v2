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
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np


# ── Policies ──────────────────────────────────────────────────────────────────

POLICIES      = ["lru_mid", "srrip", "drrip"]
POLICY_LABELS = ["lru_mid", "SRRIP", "DRRIP"]
POLICY_COLORS = ["#A67CB9", "#E8A87C", "#7CB9A8"]   # muted purple / peach / teal
BASELINE      = "lru"


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_ipc(path: Path):
    """Return ROI cumulative IPC, or None."""
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


def load_policy_ipcs(policy_dir: Path):
    """Return dict { workload: ipc } for all champsim.out files."""
    files = sorted(policy_dir.glob("*/champsim.out"))
    nested = True
    if not files:
        files = sorted(policy_dir.glob("*.out"))
        nested = False
    out = {}
    for f in files:
        wl = f.parent.name if nested else f.stem
        v = parse_ipc(f)
        if v is not None:
            out[wl] = v
    return out


def geomean(vals):
    v = [x for x in vals if x is not None and x > 0]
    if not v:
        return None
    return float(np.exp(np.mean(np.log(v))))


def suite_speedups(suite_dir: Path, policies: list[str]):
    """Return dict { policy: geomean_speedup } for one suite.

    Also returns the number of common traces used.
    """
    base_ipcs = load_policy_ipcs(suite_dir / BASELINE)
    if not base_ipcs:
        return {}, 0

    result = {}
    n_common = None
    for pol in policies:
        pol_dir = suite_dir / pol
        if not pol_dir.is_dir():
            result[pol] = None
            continue
        pol_ipcs = load_policy_ipcs(pol_dir)
        common = [wl for wl in base_ipcs if wl in pol_ipcs and base_ipcs[wl] > 0]
        if n_common is None:
            n_common = len(common)
        ratios = [pol_ipcs[wl] / base_ipcs[wl] for wl in common]
        result[pol] = geomean(ratios)

    return result, (n_common or 0)


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

    fig, ax = plt.subplots(figsize=(max(6, n_groups * 1.5 + 2), 5))

    for pi, (pol, label, color) in enumerate(zip(POLICIES, POLICY_LABELS, POLICY_COLORS)):
        offsets = (np.arange(n_pol) - (n_pol - 1) / 2) * bar_w
        x_pos   = x_groups + offsets[pi]
        heights = [row.get(pol) or 0 for row in all_rows]
        bars = ax.bar(x_pos, heights, bar_w * 0.92,
                      color=color, edgecolor="black", linewidth=0.5,
                      label=label, zorder=3)

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
    ax.legend(fontsize=9, loc="upper right", framealpha=0.85)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f×"))
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
    args = ap.parse_args()

    dirs = [Path(d) for d in args.results_dirs]
    for d in dirs:
        if not d.is_dir():
            sys.exit(f"ERROR: not a directory: {d}")

    labels = args.labels or [d.name for d in dirs]
    if len(labels) != len(dirs):
        sys.exit("ERROR: --labels count must match number of result directories")

    speedup_rows = []
    for lbl, d in zip(labels, dirs):
        if not (d / BASELINE).is_dir():
            sys.exit(f"ERROR: no '{BASELINE}/' baseline subdir found in {d}")
        print(f"Loading '{lbl}' from {d} ...")
        row, n = suite_speedups(d, POLICIES)
        print(f"  {n} common traces")
        for pol in POLICIES:
            v = row.get(pol)
            tag = f"{(v-1)*100:+.2f}%" if v is not None else "missing"
            print(f"    {pol}: {tag}")
        speedup_rows.append(row)

    out_path = Path(args.out) if args.out else dirs[0].parent / "plots" / "suite_ipc.png"
    plot(labels, speedup_rows, out_path)


if __name__ == "__main__":
    main()
