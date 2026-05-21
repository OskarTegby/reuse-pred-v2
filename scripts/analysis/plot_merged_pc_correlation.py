#!/usr/bin/env python3
"""plot_merged_pc_correlation.py — cross-level per-PC DoA correlation study.

Reads the "# merged_pc_hist" section appended to pc_liveness.csv files
(written when CBPRED_IDX=merged and PC_STATS=1) and analyses whether PCs
that cause DoA pages in the STLB also cause DoA blocks in the LLC.

The central question: is per-PC STLB DoA rate predictive of per-PC LLC
DoA rate?  If yes, the merged history table has a sound theoretical basis.

Plots generated
---------------
1. Correlation scatter (one per suite or pooled)
   X = STLB DoA rate per PC   Y = LLC DoA rate per PC
   Size  = LLC eviction count (√ scaled)
   Colour= STLB eviction count (log scale)
   Annotates Spearman ρ and the count of PCs that appear in both caches.

2. Rank-correlation plot
   X = STLB DoA rank (1 = highest STLB DoA rate)
   Y = LLC  DoA rank (1 = highest LLC  DoA rate)
   Perfect correlation → diagonal.  Jitter applied to reveal density.

3. Top-K STLB-DoA PCs — LLC DoA rate
   For the top-K PCs by STLB DoA rate: what is their LLC DoA rate?
   A bar chart showing STLB and LLC DoA rates side-by-side, sorted by
   STLB DoA rate, to directly see how well the STLB ranking transfers.

Usage
-----
    # Single results dir (one config, multiple traces pooled)
    python3 scripts/analysis/plot_merged_pc_correlation.py \\
        results/<label>/behavioral_study/ --suite maz

    # Compare two suites
    python3 scripts/analysis/plot_merged_pc_correlation.py \\
        results/<labelA>/behavioral_study/ results/<labelB>/behavioral_study/ \\
        --suite maz qmm
"""

import argparse
import csv
import io
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from scipy import stats

try:
    from colors import LIVENESS_COLORS
except ImportError:
    LIVENESS_COLORS = {"doa": "#d62728", "mostly_dead": "#ff7f0e", "mostly_alive": "#2ca02c"}

SUITE_COLORS = ["#1f77b4", "#9467bd", "#8c564b", "#e377c2"]

# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_merged_section(csv_path: Path):
    """Parse the '# merged_pc_hist' section from a pc_liveness.csv file.

    Returns a dict: pc (int) → {stlb_total, stlb_doa, stlb_mostly_dead,
    stlb_mostly_alive, llc_total, llc_doa, llc_mostly_dead, llc_mostly_alive}.
    Returns None if the section is absent.
    """
    if not csv_path.exists():
        return None

    text = csv_path.read_text(errors="replace")
    marker = "# merged_pc_hist"
    idx = text.find(marker)
    if idx == -1:
        return None

    section = text[idx + len(marker):].lstrip("\n")
    entries = {}
    try:
        reader = csv.DictReader(io.StringIO(section))
        for row in reader:
            pc = int(row["pc"], 16)
            entries[pc] = {
                "stlb_total":       int(row["stlb_total"]),
                "stlb_doa":         int(row["stlb_doa"]),
                "stlb_mostly_dead": int(row["stlb_mostly_dead"]),
                "stlb_mostly_alive":int(row["stlb_mostly_alive"]),
                "llc_total":        int(row["llc_total"]),
                "llc_doa":          int(row["llc_doa"]),
                "llc_mostly_dead":  int(row["llc_mostly_dead"]),
                "llc_mostly_alive": int(row["llc_mostly_alive"]),
            }
    except Exception as e:
        print(f"  WARNING: parse error in {csv_path}: {e}")
        return None
    return entries or None


def pool_suite(results_dir: Path):
    """Sum merged_pc_hist entries across all traces in results_dir.

    Returns (pool, n_files) where pool maps pc → summed dict.
    """
    out_files = sorted(results_dir.glob("*/champsim.out"))
    if not out_files:
        out_files = sorted(results_dir.glob("*.out"))
    if not out_files:
        sys.exit(f"ERROR: no output files found in {results_dir}")

    pool = defaultdict(lambda: defaultdict(int))
    n_files = 0
    n_skipped = 0

    for f in out_files:
        csv_path = f.parent / "pc_liveness.csv"
        entries = parse_merged_section(csv_path)
        if entries is None:
            n_skipped += 1
            continue
        for pc, d in entries.items():
            for k, v in d.items():
                pool[pc][k] += v
        n_files += 1

    if n_skipped:
        print(f"  Note: {n_skipped}/{n_files + n_skipped} files had no merged_pc_hist section")
    if n_files == 0:
        sys.exit(f"ERROR: no merged_pc_hist sections found in {results_dir}\n"
                 "Run with CBPRED_IDX=merged and PC_STATS=1.")
    return dict(pool), n_files


def pool_to_arrays(pool: dict):
    """Extract numpy arrays from pooled pool.  Only PCs with both levels > 0."""
    pcs, stlb_tot, stlb_doa, llc_tot, llc_doa = [], [], [], [], []
    for pc, d in pool.items():
        if d["stlb_total"] == 0 or d["llc_total"] == 0:
            continue
        pcs.append(pc)
        stlb_tot.append(d["stlb_total"])
        stlb_doa.append(d["stlb_doa"])
        llc_tot.append(d["llc_total"])
        llc_doa.append(d["llc_doa"])
    if not pcs:
        return None
    return (
        np.array(pcs,      dtype=np.uint64),
        np.array(stlb_tot, dtype=float),
        np.array(stlb_doa, dtype=float),
        np.array(llc_tot,  dtype=float),
        np.array(llc_doa,  dtype=float),
    )


# ── Plot 1: correlation scatter ───────────────────────────────────────────────

def plot_correlation_scatter(suite_pools: list, out_path: Path):
    """Scatter of STLB DoA rate vs LLC DoA rate, one panel per suite."""
    n = len(suite_pools)
    fig, axes = plt.subplots(1, n, figsize=(7 * n, 6), squeeze=False)

    for ax, (label, pool, n_files) in zip(axes[0], suite_pools):
        arrays = pool_to_arrays(pool)
        if arrays is None:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                    transform=ax.transAxes)
            ax.set_title(label)
            continue

        _, stlb_tot, stlb_doa, llc_tot, llc_doa = arrays
        stlb_rate = stlb_doa / stlb_tot * 100
        llc_rate  = llc_doa  / llc_tot  * 100

        rho, pval = stats.spearmanr(stlb_rate, llc_rate)

        # Size: √(LLC evictions), clipped for readability
        sizes = np.sqrt(llc_tot)
        sizes = 10 + 200 * sizes / sizes.max()

        # Colour: log10 of STLB eviction count
        log_stlb = np.log10(np.clip(stlb_tot, 1, None))

        sc = ax.scatter(stlb_rate, llc_rate,
                        s=sizes, c=log_stlb,
                        cmap="viridis", alpha=0.65,
                        edgecolors="none", zorder=3)
        cbar = fig.colorbar(sc, ax=ax, pad=0.02)
        cbar.set_label("log₁₀(STLB evictions)")

        # Diagonal reference
        ax.plot([0, 100], [0, 100], color="gray", linewidth=0.8,
                linestyle="--", zorder=1, label="y = x")

        # Annotate top-5 by LLC eviction count
        top5 = np.argsort(llc_tot)[-5:]
        for i in top5:
            ax.annotate(f"0x{_[i]:x}",
                        (stlb_rate[i], llc_rate[i]),
                        textcoords="offset points", xytext=(4, 2),
                        fontsize=6, color="black", zorder=5)

        ax.set_xlim(-2, 102)
        ax.set_ylim(-2, 102)
        ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
        ax.set_xlabel("STLB DoA rate per PC")
        ax.set_ylabel("LLC DoA rate per PC")
        ax.set_title(
            f"{label}  ({n_files} traces, {len(stlb_rate):,} PCs)\n"
            f"Spearman ρ = {rho:.3f}  (p = {pval:.2e})"
        )
        ax.grid(True, alpha=0.2)

        print(f"  {label}: {len(stlb_rate):,} PCs  Spearman ρ = {rho:.3f}  p = {pval:.2e}")

    fig.suptitle("Cross-level per-PC DoA correlation: STLB page DoA ↔ LLC block DoA",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(out_path, dpi=300)
    plt.close(fig)
    print(f"  Saved: {out_path}")


# ── Plot 2: rank-correlation ──────────────────────────────────────────────────

def plot_rank_correlation(suite_pools: list, out_path: Path):
    """STLB DoA rank vs LLC DoA rank scatter with diagonal reference."""
    n = len(suite_pools)
    fig, axes = plt.subplots(1, n, figsize=(6 * n, 5), squeeze=False)

    for ax, (label, pool, n_files) in zip(axes[0], suite_pools):
        arrays = pool_to_arrays(pool)
        if arrays is None:
            ax.set_title(label); continue

        _, stlb_tot, stlb_doa, llc_tot, llc_doa = arrays
        stlb_rate = stlb_doa / stlb_tot
        llc_rate  = llc_doa  / llc_tot

        # Rank 1 = highest rate
        stlb_rank = stats.rankdata(-stlb_rate)
        llc_rank  = stats.rankdata(-llc_rate)
        rho, _ = stats.spearmanr(stlb_rate, llc_rate)

        # Hex-bin for density when many PCs
        n_pcs = len(stlb_rank)
        if n_pcs > 2000:
            ax.hexbin(stlb_rank, llc_rank, gridsize=40,
                      cmap="Blues", mincnt=1, linewidths=0.1, zorder=3)
        else:
            ax.scatter(stlb_rank, llc_rank,
                       s=8, alpha=0.5, color="#1f77b4",
                       edgecolors="none", zorder=3)

        ax.plot([1, n_pcs], [1, n_pcs], color="gray", linewidth=0.8,
                linestyle="--", zorder=1)
        ax.set_xlabel("STLB DoA rank (1 = highest STLB DoA rate)")
        ax.set_ylabel("LLC DoA rank  (1 = highest LLC DoA rate)")
        ax.set_title(f"{label}  ({n_pcs:,} PCs, ρ = {rho:.3f})")
        ax.grid(True, alpha=0.2)

    fig.suptitle("Rank correlation: STLB DoA rank vs LLC DoA rank per PC",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(out_path, dpi=300)
    plt.close(fig)
    print(f"  Saved: {out_path}")


# ── Plot 3: top-K bar chart ───────────────────────────────────────────────────

def plot_topk_bar(suite_pools: list, k: int, out_path: Path):
    """For top-K STLB-DoA PCs: show STLB vs LLC DoA rate side-by-side."""
    n = len(suite_pools)
    fig, axes = plt.subplots(n, 1,
                             figsize=(10, max(4, k * 0.45 + 2) * n),
                             squeeze=False)

    for ax, (label, pool, n_files) in zip(axes[:, 0], suite_pools):
        arrays = pool_to_arrays(pool)
        if arrays is None:
            ax.set_title(label); continue

        pcs, stlb_tot, stlb_doa, llc_tot, llc_doa = arrays
        stlb_rate = stlb_doa / stlb_tot * 100
        llc_rate  = llc_doa  / llc_tot  * 100

        # Select top-K by STLB DoA rate (minimum 50 STLB evictions to avoid noise)
        mask = stlb_tot >= 50
        idx_valid = np.where(mask)[0]
        if len(idx_valid) == 0:
            idx_valid = np.arange(len(pcs))
        top_k = idx_valid[np.argsort(stlb_rate[idx_valid])[::-1][:k]]
        # Sort by STLB rate for the chart (already sorted but re-sort for clarity)
        top_k = top_k[np.argsort(stlb_rate[top_k])]  # ascending for horizontal bar

        y = np.arange(len(top_k))
        w = 0.35
        labels = [f"0x{pcs[i]:x}" for i in top_k]

        ax.barh(y - w/2, stlb_rate[top_k], height=w,
                color=LIVENESS_COLORS["doa"], label="STLB DoA rate")
        ax.barh(y + w/2, llc_rate[top_k],  height=w,
                color="#1f77b4", alpha=0.8, label="LLC DoA rate")

        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=7)
        ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
        ax.set_xlabel("DoA rate (%)")
        ax.set_xlim(0, 105)
        ax.axvline(50, color="gray", linewidth=0.6, linestyle=":", zorder=1)
        ax.set_title(
            f"{label} — top-{len(top_k)} PCs by STLB DoA rate  "
            f"({n_files} traces pooled, ≥50 STLB evictions)"
        )
        ax.legend(loc="lower right", fontsize=9)
        ax.grid(True, axis="x", alpha=0.2)

    fig.suptitle("Do high-STLB-DoA PCs also produce high LLC DoA rates?",
                 fontsize=12)
    fig.tight_layout()
    fig.savefig(out_path, dpi=300)
    plt.close(fig)
    print(f"  Saved: {out_path}")


# ── Summary stats ─────────────────────────────────────────────────────────────

def print_summary(label: str, pool: dict, n_files: int):
    arrays = pool_to_arrays(pool)
    if arrays is None:
        print(f"  {label}: no data")
        return
    _, stlb_tot, stlb_doa, llc_tot, llc_doa = arrays
    stlb_rate = stlb_doa / stlb_tot
    llc_rate  = llc_doa  / llc_tot
    rho, pval = stats.spearmanr(stlb_rate, llc_rate)

    all_pcs = len(pool)
    both_pcs = len(stlb_rate)

    # How many of the top-10% STLB-DoA PCs are also in the top-10% LLC-DoA PCs?
    n10 = max(1, int(0.10 * both_pcs))
    top_stlb = set(np.argsort(stlb_rate)[-n10:])
    top_llc  = set(np.argsort(llc_rate)[-n10:])
    overlap = len(top_stlb & top_llc)

    print(f"\n  [{label}]  {n_files} traces  |  {all_pcs:,} PCs total  "
          f"|  {both_pcs:,} with both STLB+LLC data")
    print(f"    Spearman ρ = {rho:.3f}   p = {pval:.2e}")
    print(f"    Top-10% overlap (STLB ∩ LLC): {overlap}/{n10}  "
          f"({100*overlap/n10:.1f}%)")
    print(f"    STLB DoA rate mean={stlb_rate.mean()*100:.1f}%  "
          f"median={np.median(stlb_rate)*100:.1f}%")
    print(f"    LLC  DoA rate mean={llc_rate.mean()*100:.1f}%  "
          f"median={np.median(llc_rate)*100:.1f}%")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("results_dirs", nargs="+",
                    help="One or more directories with behavioral study results")
    ap.add_argument("--suite", nargs="*", dest="labels",
                    help="Suite labels (default: directory names)")
    ap.add_argument("--topk", type=int, default=30,
                    help="Number of top STLB-DoA PCs for the bar chart (default: 30)")
    ap.add_argument("--out", default=None,
                    help="Output file prefix (default: <run_dir>/plots/merged_pc_corr)")
    args = ap.parse_args()

    dirs = [Path(d) for d in args.results_dirs]
    for d in dirs:
        if not d.is_dir():
            sys.exit(f"ERROR: {d} is not a directory")

    labels = args.labels or [d.parent.name if d.name in ("behavioral_study", "baseline")
                              else d.name for d in dirs]
    if len(labels) != len(dirs):
        sys.exit("ERROR: --suite count must match number of directories")

    run_dir   = dirs[0].parent
    plots_dir = run_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    out_prefix = args.out or str(plots_dir / "merged_pc_corr")

    suite_pools = []
    for label, d in zip(labels, dirs):
        print(f"\nPooling '{label}' from {d} ...")
        pool, n_files = pool_suite(d)
        suite_pools.append((label, pool, n_files))
        print_summary(label, pool, n_files)

    print("\nGenerating correlation scatter ...")
    plot_correlation_scatter(suite_pools, Path(f"{out_prefix}_scatter.png"))

    print("\nGenerating rank-correlation plot ...")
    plot_rank_correlation(suite_pools, Path(f"{out_prefix}_rank.png"))

    print(f"\nGenerating top-{args.topk} STLB-DoA bar chart ...")
    plot_topk_bar(suite_pools, args.topk, Path(f"{out_prefix}_topk.png"))

    print("\nDone.")


if __name__ == "__main__":
    main()
