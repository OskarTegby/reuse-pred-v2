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

# ── Colours: one per policy slot (baselines solid, pred variants hatched) ─────
POLICY_COLORS = [
    "#5B7FA6",  # lru         — steel blue
    "#E8A87C",  # srrip       — soft peach
    "#7CB9A8",  # drrip       — soft teal
    "#A67CB9",  # lru_mid     — muted purple
    "#2C5F8A",  # lru+pred    — deep blue
    "#C46A30",  # srrip+pred  — burnt orange
    "#3D8A78",  # drrip+pred  — deep teal
    "#6A3D8A",  # lru_mid+pred — deep purple
]
POLICY_HATCHES = ["", "", "", "", "//", "//", "//", "//"]


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

def geomean(vals):
    """Geometric mean of a list; ignores None and non-positive values."""
    v = [x for x in vals if x is not None and x > 0]
    if not v:
        return None
    return float(np.exp(np.mean(np.log(v))))


# ── Plot helpers ──────────────────────────────────────────────────────────────

def _bar_group(ax, workloads, policy_names, matrix, ylabel, title,
               baseline_val=1.0, ref_line=True):
    """Draw a grouped bar chart.

    matrix[p][w] = value for policy p, workload w (None = missing).
    A geomean bar is appended after a small gap.
    The y-axis is zoomed in to the actual data range so small differences
    between policies are visible.
    """
    n_policies = len(policy_names)
    n_wl = len(workloads)

    # Geomean column
    gm = []
    for p in range(n_policies):
        vals = [matrix[p][w] for w in range(n_wl) if matrix[p][w] is not None]
        gm.append(geomean(vals))

    gap = 1.5
    group_w = 0.8
    bar_w = group_w / n_policies
    x_wl = np.arange(n_wl)
    x_gm = n_wl + gap

    colors = POLICY_COLORS[:n_policies]
    hatches = POLICY_HATCHES[:n_policies]

    for pi, (pname, color, hatch) in enumerate(zip(policy_names, colors, hatches)):
        offsets = (np.arange(n_policies) - (n_policies - 1) / 2) * bar_w
        x_pos_wl = x_wl + offsets[pi]
        x_pos_gm = x_gm + offsets[pi]

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

    # Zoom y-axis to the actual data range with 20% padding on each side.
    # Include the reference line value so it stays visible.
    all_vals = [v for row in matrix for v in row if v is not None]
    all_vals += [g for g in gm if g is not None]
    if ref_line:
        all_vals.append(baseline_val)
    if all_vals:
        lo, hi = min(all_vals), max(all_vals)
        span = max(hi - lo, 1e-6)
        ax.set_ylim(lo - 0.2 * span, hi + 0.2 * span)

    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_title(title, fontsize=11)
    ax.set_xlim(-0.7, x_gm + 0.7)
    ax.legend(loc="upper right", fontsize=7, framealpha=0.8, ncol=2)
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
    args = ap.parse_args()

    results_dir = Path(args.results_dir)
    if not results_dir.is_dir():
        sys.exit(f"ERROR: not a directory: {results_dir}")

    # Discover policies in a fixed display order
    ordered = ["lru", "srrip", "drrip", "lru_mid",
               "lru_pred", "srrip_pred", "drrip_pred", "lru_mid_pred"]
    display_labels = {
        "lru": "lru", "srrip": "srrip", "drrip": "drrip", "lru_mid": "lru_mid",
        "lru_pred": "lru+pred", "srrip_pred": "srrip+pred",
        "drrip_pred": "drrip+pred", "lru_mid_pred": "lru_mid+pred",
    }

    present = [p for p in ordered if (results_dir / p).is_dir()]
    if not present:
        sys.exit(f"ERROR: no recognised policy subdirs found in {results_dir}")
    if args.baseline not in present:
        sys.exit(f"ERROR: baseline policy '{args.baseline}' not found in {results_dir}")

    print(f"Policies found: {present}")

    # Load all data
    data = {}
    for policy in present:
        print(f"  Loading {policy} ...")
        data[policy] = load_policy(results_dir / policy)

    # Union of workloads present in the baseline
    workloads = sorted(data[args.baseline].keys())
    if not workloads:
        sys.exit(f"ERROR: no workloads found under {results_dir / args.baseline}")
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

    # Sort workloads by descending geomean IPC speedup of the best pred policy
    pred_present = [p for p in present if p.endswith("_pred")]
    if pred_present:
        best_pred_idx = present.index(pred_present[-1])
        sort_key = [ipc_matrix[best_pred_idx][wi] or 0 for wi in range(len(workloads))]
        order = sorted(range(len(workloads)), key=lambda i: sort_key[i], reverse=True)
    else:
        order = list(range(len(workloads)))
    workloads_sorted = [workloads[i] for i in order]
    ipc_matrix_sorted = [[row[i] for i in order] for row in ipc_matrix]

    out_obj = Path(args.out)
    out_dir = out_obj.parent
    out_stem = out_obj.stem

    fig_w = max(10, len(workloads) * 0.7 + 3)
    fig, ax = plt.subplots(figsize=(fig_w, 5))
    _bar_group(ax, workloads_sorted, policy_labels, ipc_matrix_sorted,
               ylabel=f"IPC speedup vs {args.baseline}",
               title=f"IPC speedup vs {args.baseline} — {results_dir.name}",
               baseline_val=1.0, ref_line=True)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    fig.tight_layout()
    ipc_out = str(out_dir / f"{out_stem}_ipc.png")
    fig.savefig(ipc_out, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {ipc_out}")

    # ── MPKI ──────────────────────────────────────────────────────────────────
    # Two sub-matrices: STLB MPKI and LLC MPKI
    def mpki(stats, key):
        instrs = stats.get("instrs")
        misses = stats.get(key)
        if instrs and misses is not None and instrs > 0:
            return misses / (instrs / 1000)
        return None

    stlb_matrix = []
    llc_matrix  = []
    for policy in present:
        stlb_row, llc_row = [], []
        for wl in workloads_sorted:
            s = data[policy].get(wl, {})
            stlb_row.append(mpki(s, "stlb_miss"))
            llc_row.append(mpki(s, "llc_miss"))
        stlb_matrix.append(stlb_row)
        llc_matrix.append(llc_row)

    fig, axes = plt.subplots(2, 1, figsize=(fig_w, 9))
    _bar_group(axes[0], workloads_sorted, policy_labels, stlb_matrix,
               ylabel="STLB MPKI",
               title=f"STLB MPKI — {results_dir.name}",
               ref_line=False)
    axes[0].yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))

    _bar_group(axes[1], workloads_sorted, policy_labels, llc_matrix,
               ylabel="LLC MPKI",
               title=f"LLC MPKI — {results_dir.name}",
               ref_line=False)
    axes[1].yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))

    fig.tight_layout()
    mpki_out = str(out_dir / f"{out_stem}_mpki.png")
    fig.savefig(mpki_out, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {mpki_out}")


if __name__ == "__main__":
    main()
