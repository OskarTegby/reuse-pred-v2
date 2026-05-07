#!/usr/bin/env python3
"""plot_stlb_llc_comparison.py — compare lru_mid applied to LLC-only vs LLC+STLB.

Both runs are normalised to their own LRU baseline, so the bars show
IPC speedup (or MPKI reduction) vs LRU with the same scope of change.

Produces two figures:
  <out>          — IPC speedup over LRU
  <out stem>_mpki.png — STLB and LLC MPKI reduction over LRU (side-by-side subplots)

Usage
-----
    python3 scripts/analysis/plot_stlb_llc_comparison.py \\
        --llc-only  results/llc_repl_pol_study/dpc3_...  ...google...  ...qmm...  \\
        --both      results/repl_pol_without_pref_study/dpc3_...  ...google...  ...qmm... \\
        --labels    SPEC Google Qualcomm \\
        --out       results/plots/stlb_llc_comparison/suite_ipc.png
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from colors import POLICY_COLORS
from champsim_utils import parse_stats, geomean
from spec_weights import SPEC_WEIGHTS, benchmark_name


POLICIES       = ["lru_mid", "lru_mid_pred"]
POLICY_LABELS  = ["lru_mid", "lru_mid+pred"]
BASELINE       = "lru"


# ── Parsing ───────────────────────────────────────────────────────────────────

def load_policy(policy_dir: Path):
    out = {}
    for f in sorted(policy_dir.glob("*/champsim.out")):
        ipc, stlb, llc = parse_stats(f)
        if ipc is not None:
            out[f.parent.name] = (ipc, stlb, llc)
    return out



def wmean(vals, weights):
    pairs = [(v, w) for v, w in zip(vals, weights) if v is not None and w is not None]
    if not pairs:
        return None
    total = sum(w for _, w in pairs)
    return sum(v * w / total for v, w in pairs)


def benchmark_geomean(ratios: dict, weights: dict) -> float | None:
    groups: dict[str, list] = {}
    for wl, v in ratios.items():
        if v is not None and v > 0:
            groups.setdefault(benchmark_name(wl), []).append(wl)
    per_bench = []
    for wl_list in groups.values():
        pairs = [(ratios[wl], weights.get(wl)) for wl in wl_list]
        valid = [(v, w) for v, w in pairs if w is not None]
        if valid:
            total_w = sum(w for _, w in valid)
            per_bench.append(float(np.exp(sum((w / total_w) * np.log(v) for v, w in valid))))
        else:
            per_bench.append(geomean([ratios[wl] for wl in wl_list]))
    return geomean(per_bench)


def benchmark_mean(vals: dict, weights: dict) -> float | None:
    """Equal-weight mean across benchmarks, weighted mean within each benchmark."""
    groups: dict[str, list] = {}
    for wl, v in vals.items():
        if v is not None:
            groups.setdefault(benchmark_name(wl), []).append(wl)
    per_bench = []
    for wl_list in groups.values():
        pairs = [(vals[wl], weights.get(wl)) for wl in wl_list]
        valid = [(v, w) for v, w in pairs if w is not None]
        if valid:
            total_w = sum(w for _, w in valid)
            per_bench.append(sum(v * w / total_w for v, w in valid))
        else:
            per_bench.append(float(np.mean([vals[wl] for wl in wl_list])))
    return float(np.mean(per_bench)) if per_bench else None


def suite_stats(suite_dir: Path, policy: str, weights: dict):
    """Return (ipc_ratio, stlb_mpki_reduction_pct, llc_mpki_reduction_pct) vs LRU baseline."""
    base = load_policy(suite_dir / BASELINE)
    pol  = load_policy(suite_dir / policy)
    if not base or not pol:
        return None, None, None
    common = [wl for wl in base if wl in pol and base[wl][0] > 0]

    ipc_ratios   = {wl: pol[wl][0] / base[wl][0] for wl in common}
    stlb_reductions = {wl: (base[wl][1] - pol[wl][1]) / base[wl][1] * 100
                       for wl in common
                       if base[wl][1] and base[wl][1] > 0 and pol[wl][1] is not None}
    llc_reductions  = {wl: (base[wl][2] - pol[wl][2]) / base[wl][2] * 100
                       for wl in common
                       if base[wl][2] and base[wl][2] > 0 and pol[wl][2] is not None}

    ipc  = benchmark_geomean(ipc_ratios, weights)
    stlb = benchmark_mean(stlb_reductions, weights)
    llc  = benchmark_mean(llc_reductions, weights)
    return ipc, stlb, llc


# ── Plotting helpers ──────────────────────────────────────────────────────────

def _bar_layout(n_policies):
    group_w = 0.72
    bar_w   = group_w / (2 * n_policies + 0.5)
    offsets_llc  = np.array([(i - (n_policies - 0.5) / 2) * bar_w * 2 for i in range(n_policies)])
    offsets_both = offsets_llc + bar_w
    return bar_w, offsets_llc, offsets_both


def _draw_bars(ax, x, pi, bar_w, offset_llc, offset_both, color, plabel, llc_vals, both_vals):
    ax.bar(x + offset_llc,  llc_vals,  bar_w, color=color,
           label=f"{plabel} — LLC only")
    ax.bar(x + offset_both, both_vals, bar_w, color=color, hatch="//",
           edgecolor="white", alpha=0.85, label=f"{plabel} — LLC+STLB")


# ── IPC plot ──────────────────────────────────────────────────────────────────

def plot_ipc(labels, llc_rows, both_rows, out_path: Path):
    n = len(labels)
    bar_w, off_llc, off_both = _bar_layout(len(POLICIES))
    fig, ax = plt.subplots(figsize=(max(7, 2.5 * n), 4))
    x = np.arange(n)

    for pi, (pol, plabel) in enumerate(zip(POLICIES, POLICY_LABELS)):
        color = POLICY_COLORS[pol]
        llc_pct  = [(r.get(pol, 1) - 1) * 100 for r in llc_rows]
        both_pct = [(r.get(pol, 1) - 1) * 100 for r in both_rows]
        _draw_bars(ax, x, pi, bar_w, off_llc[pi], off_both[pi],
                   color, plabel, llc_pct, both_pct)

    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel("IPC speedup vs LRU (%)", fontsize=10)
    ax.set_title("lru_mid: LLC-only vs LLC+STLB  |  baseline: LRU (same scope)", fontsize=10)
    ax.legend(fontsize=8, ncol=1, loc="lower right")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:+.1f}%"))
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


# ── MPKI plot ─────────────────────────────────────────────────────────────────

def plot_mpki(labels, llc_stlb_rows, both_stlb_rows, llc_llc_rows, both_llc_rows, out_path: Path):
    n = len(labels)
    bar_w, off_llc, off_both = _bar_layout(len(POLICIES))
    fig, axes = plt.subplots(1, 2, figsize=(max(10, 3.5 * n), 4), sharey=False)

    for ax, (stlb_l, stlb_b, cache_label) in zip(
        axes,
        [(llc_stlb_rows, both_stlb_rows, "STLB MPKI reduction vs LRU (%)"),
         (llc_llc_rows,  both_llc_rows,  "LLC MPKI reduction vs LRU (%)")],
    ):
        x = np.arange(n)
        for pi, (pol, plabel) in enumerate(zip(POLICIES, POLICY_LABELS)):
            color = POLICY_COLORS[pol]
            llc_vals  = [r.get(pol, 0) or 0 for r in stlb_l]
            both_vals = [r.get(pol, 0) or 0 for r in stlb_b]
            _draw_bars(ax, x, pi, bar_w, off_llc[pi], off_both[pi],
                       color, plabel, llc_vals, both_vals)
        ax.axhline(0, color="black", linewidth=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=11)
        ax.set_ylabel(cache_label, fontsize=9)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:+.1f}%"))

    axes[0].set_title("STLB", fontsize=10)
    axes[1].set_title("LLC", fontsize=10)
    fig.suptitle("lru_mid: LLC-only vs LLC+STLB  |  MPKI reduction vs LRU baseline", fontsize=10)
    handles, lbls = axes[0].get_legend_handles_labels()
    fig.legend(handles, lbls, fontsize=8, ncol=2, loc="lower center",
               bbox_to_anchor=(0.5, -0.12))
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--llc-only", nargs="+", metavar="DIR", required=True)
    parser.add_argument("--both",     nargs="+", metavar="DIR", required=True)
    parser.add_argument("--labels",   nargs="+", metavar="LABEL", required=True)
    parser.add_argument("--out", default="results/plots/stlb_llc_comparison/suite_ipc.png")
    args = parser.parse_args()

    weights = SPEC_WEIGHTS
    if weights:
        print(f"Loaded simpoint weights for {len(set(benchmark_name(k) for k in weights))} benchmarks")

    llc_ipc_rows,  both_ipc_rows  = [], []
    llc_stlb_rows, both_stlb_rows = [], []
    llc_llc_rows,  both_llc_rows  = [], []

    for lbl, llc_dir, both_dir in zip(args.labels, args.llc_only, args.both):
        llc_d, both_d = Path(llc_dir), Path(both_dir)
        li, ls, ll = {}, {}, {}
        bi, bs, bl = {}, {}, {}
        for pol in POLICIES:
            ipc_l, stlb_l, llc_l = suite_stats(llc_d,  pol, weights)
            ipc_b, stlb_b, llc_b = suite_stats(both_d, pol, weights)
            li[pol], ls[pol], ll[pol] = ipc_l, stlb_l, llc_l
            bi[pol], bs[pol], bl[pol] = ipc_b, stlb_b, llc_b
            print(f"  {lbl:10s}  {pol:18s}  "
                  f"IPC LLC-only: {(ipc_l-1)*100:+.2f}%  both: {(ipc_b-1)*100:+.2f}%  |  "
                  f"STLB MPKI LLC-only: {stlb_l:+.2f}%  both: {stlb_b:+.2f}%  |  "
                  f"LLC MPKI LLC-only: {llc_l:+.2f}%  both: {llc_b:+.2f}%")
        llc_ipc_rows.append(li);  both_ipc_rows.append(bi)
        llc_stlb_rows.append(ls); both_stlb_rows.append(bs)
        llc_llc_rows.append(ll);  both_llc_rows.append(bl)

    out_path = Path(args.out)
    mpki_path = out_path.parent / (out_path.stem.replace("ipc", "mpki") + out_path.suffix)

    plot_ipc(args.labels, llc_ipc_rows, both_ipc_rows, out_path)
    plot_mpki(args.labels, llc_stlb_rows, both_stlb_rows,
              llc_llc_rows, both_llc_rows, mpki_path)


if __name__ == "__main__":
    main()
