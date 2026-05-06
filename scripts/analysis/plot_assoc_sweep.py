#!/usr/bin/env python3
"""
plot_assoc_sweep.py — IPC speedup vs associativity for the sweep_assoc study.

For each table (pHIST, bHIST) independently, plots IPC speedup over the
no-predictor baseline across all associativity levels (direct-mapped → FA),
comparing LRU and LFU.

Each policy's sweep shows:
  • Geomean speedup line
  • Shaded envelope between the per-trace infimum and supremum at each
    associativity level — the range of outcomes to expect across workloads
  • Dashed reference line at the fully-associative (FA) speedup — the
    asymptotic supremum for that policy's associativity sweep

hash_pred (fully-associative but hashed, no tag matching) is shown as a
separate reference to anchor the scale.

Usage:
    python3 plot_assoc_sweep.py <results_dir> [--out-dir DIR]

    results_dir   Base directory from sweep_assoc.sh, e.g.
                  results/dpc3_assoc_p1024_b4096_20260504_1200/

    --out-dir     Where to write PNGs (default: results_dir)
"""

import argparse
import os
import re
import sys

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np


LRU_COLOR  = "#1a9850"
LFU_COLOR  = "#4393c3"
HASH_COLOR = "#d73027"


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_ipc(path):
    in_roi = False
    try:
        with open(path) as f:
            for line in f:
                if "Region of Interest Statistics" in line:
                    in_roi = True
                if in_roi and "cumulative IPC:" in line:
                    m = re.search(r"cumulative IPC:\s+([0-9.]+)", line)
                    if m:
                        return float(m.group(1))
    except OSError:
        pass
    return None


def speedup_stats(exp_dir, baseline_dir):
    """Return (geomean_pct, min_pct, max_pct) of IPC speedup across all traces."""
    ratios = []
    for trace in os.listdir(exp_dir):
        exp_file  = os.path.join(exp_dir, trace, "champsim.out")
        base_file = os.path.join(baseline_dir, trace, "champsim.out")
        ipc_exp  = parse_ipc(exp_file)
        ipc_base = parse_ipc(base_file)
        if ipc_exp is not None and ipc_base is not None and ipc_base > 0:
            ratios.append(ipc_exp / ipc_base)
    if not ratios:
        return (float("nan"),) * 3
    pct = lambda r: (r - 1.0) * 100.0
    return pct(np.exp(np.mean(np.log(ratios)))), pct(min(ratios)), pct(max(ratios))


# ── Data collection ───────────────────────────────────────────────────────────

def collect_sweep(results_dir, prefix):
    """
    Return (ways, lru_mean, lru_lo, lru_hi, lfu_mean, lfu_lo, lfu_hi).
    lo/hi are the per-trace infimum/supremum at each associativity level.
    """
    baseline_dir = os.path.join(results_dir, "baseline")
    data = {"lru": {}, "lfu": {}}

    for entry in os.listdir(results_dir):
        m = re.fullmatch(rf"{prefix}_s(\d+)_w(\d+)_(lru|lfu)", entry)
        if not m:
            continue
        ways = int(m.group(2))
        pol  = m.group(3)
        data[pol][ways] = speedup_stats(os.path.join(results_dir, entry), baseline_dir)

    all_ways = sorted(set(data["lru"]) | set(data["lfu"]))

    def col(pol, idx):
        return [data[pol].get(w, (float("nan"),) * 3)[idx] for w in all_ways]

    return (all_ways,
            col("lru", 0), col("lru", 1), col("lru", 2),
            col("lfu", 0), col("lfu", 1), col("lfu", 2))


def ref_speedup(results_dir, exp_name):
    baseline_dir = os.path.join(results_dir, "baseline")
    exp_dir      = os.path.join(results_dir, exp_name)
    if not os.path.isdir(exp_dir):
        return float("nan")
    return speedup_stats(exp_dir, baseline_dir)[0]


# ── Plotting ──────────────────────────────────────────────────────────────────

def plot_table_sweep(results_dir, prefix, label, out_path):
    ways, lru_mean, lru_lo, lru_hi, lfu_mean, lfu_lo, lfu_hi = collect_sweep(results_dir, prefix)
    if not ways:
        print(f"  No data found for {prefix} sweep in {results_dir}", file=sys.stderr)
        return

    hash_pred = ref_speedup(results_dir, "hash_pred")
    fa_lru    = ref_speedup(results_dir, "fa_lru")
    fa_lfu    = ref_speedup(results_dir, "fa_lfu")

    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(ways))

    # ── Associativity-range bands (infimum → supremum) ────────────────────────
    # For each policy the infimum is the direct-mapped (1-way) geomean and the
    # supremum is the FA geomean.  Shading the span shows how much associativity
    # is worth for that policy.
    lru_inf, lru_sup = lru_mean[0], fa_lru
    lfu_inf, lfu_sup = lfu_mean[0], fa_lfu

    if not (np.isnan(lru_inf) or np.isnan(lru_sup)):
        lo_b, hi_b = sorted([lru_inf, lru_sup])
        ax.axhspan(lo_b, hi_b, alpha=0.10, color=LRU_COLOR, zorder=0)
    if not (np.isnan(lfu_inf) or np.isnan(lfu_sup)):
        lo_b, hi_b = sorted([lfu_inf, lfu_sup])
        ax.axhspan(lo_b, hi_b, alpha=0.10, color=LFU_COLOR, zorder=0)

    # ── Geomean sweep curves ──────────────────────────────────────────────────
    ax.plot(x, lru_mean, "o-",  color=LRU_COLOR, linewidth=1.8, markersize=5,
            label="LRU — geomean", zorder=3)
    ax.plot(x, lfu_mean, "s--", color=LFU_COLOR, linewidth=1.8, markersize=5,
            label="LFU — geomean", zorder=3)

    # ── Supremum reference lines (FA performance) ─────────────────────────────
    if not np.isnan(fa_lru):
        ax.axhline(fa_lru, color=LRU_COLOR, linestyle="--", linewidth=1.1, alpha=0.75,
                   label=f"LRU supremum — FA ({fa_lru:.2f}%)", zorder=2)
    if not np.isnan(fa_lfu):
        ax.axhline(fa_lfu, color=LFU_COLOR, linestyle="--", linewidth=1.1, alpha=0.75,
                   label=f"LFU supremum — FA ({fa_lfu:.2f}%)", zorder=2)

    # ── Infimum reference lines (direct-mapped performance) ───────────────────
    if not np.isnan(lru_inf):
        ax.axhline(lru_inf, color=LRU_COLOR, linestyle=":", linewidth=0.9, alpha=0.6,
                   label=f"LRU infimum — DM ({lru_inf:.2f}%)", zorder=2)
    if not np.isnan(lfu_inf):
        ax.axhline(lfu_inf, color=LFU_COLOR, linestyle=":", linewidth=0.9, alpha=0.6,
                   label=f"LFU infimum — DM ({lfu_inf:.2f}%)", zorder=2)

    # ── hash_pred reference ───────────────────────────────────────────────────
    if not np.isnan(hash_pred):
        ax.axhline(hash_pred, color=HASH_COLOR, linestyle=":", linewidth=1.2,
                   label=f"hash_pred ({hash_pred:.2f}%)", zorder=2)

    # ── Baseline zero ─────────────────────────────────────────────────────────
    ax.axhline(0, color="black", linewidth=0.6, zorder=2)

    # ── Band legend proxies ───────────────────────────────────────────────────
    lru_patch = mpatches.Patch(color=LRU_COLOR, alpha=0.25,
                               label="LRU — associativity gain band (infimum → supremum)")
    lfu_patch = mpatches.Patch(color=LFU_COLOR, alpha=0.25,
                               label="LFU — associativity gain band (infimum → supremum)")
    handles, labels_list = ax.get_legend_handles_labels()
    ax.legend(handles=[lru_patch, lfu_patch] + handles,
              labels=[lru_patch.get_label(), lfu_patch.get_label()] + labels_list,
              fontsize=7.5, loc="best")

    # ── Axes and labels ───────────────────────────────────────────────────────
    ax.set_xticks(x)
    ax.set_xticklabels([str(w) for w in ways], rotation=45, ha="right")
    ax.set_xlabel("Associativity (ways)")
    ax.set_ylabel("IPC speedup vs. no-predictor baseline (%)")

    suite = os.path.basename(results_dir).split("_assoc_")[0].upper()
    ax.set_title(f"{suite} — {label} associativity sweep")

    # Auto y-range: fit geomeans + reference lines with 20 % padding
    finite = [v for v in
              lru_mean + lfu_mean + [hash_pred, fa_lru, fa_lfu, lru_inf, lfu_inf, 0.0]
              if not np.isnan(v)]
    if finite:
        lo_y, hi_y = min(finite), max(finite)
        pad = max((hi_y - lo_y) * 0.20, 0.05)
        ax.set_ylim(lo_y - pad, hi_y + pad)

    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  Written: {out_path}")


def find_test_dir(suite):
    """Return the most recent results/{suite}_assoc_*_test directory."""
    import glob
    pattern = os.path.join("results", f"{suite}_assoc_*_test")
    matches = sorted(glob.glob(pattern))
    if not matches:
        print(f"No _test results found matching {pattern}", file=sys.stderr)
        sys.exit(1)
    return matches[-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results_dir",
                    help="Results directory, or suite name (dpc3|google|qmm) with --test")
    ap.add_argument("--test", action="store_true",
                    help="Find and plot the most recent _test run for the given suite")
    ap.add_argument("--out-dir", default=None, help="Output directory for PNGs")
    args = ap.parse_args()

    results_dir = (find_test_dir(args.results_dir) if args.test
                   else args.results_dir.rstrip("/"))
    out_dir = args.out_dir or results_dir
    os.makedirs(out_dir, exist_ok=True)

    label = os.path.basename(results_dir)

    plot_table_sweep(results_dir, "phist", "pHIST",
                     os.path.join(out_dir, f"assoc_phist_{label}.png"))
    plot_table_sweep(results_dir, "bhist", "bHIST",
                     os.path.join(out_dir, f"assoc_bhist_{label}.png"))


if __name__ == "__main__":
    main()
