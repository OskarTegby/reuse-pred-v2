#!/usr/bin/env python3
"""plot_mid_thd.py — bar chart of IPC speedup or MPKI reduction vs mid_thd.

Reads results from a sweep_mid.sh output directory and plots geomean IPC
speedup (or MPKI reduction) against the mid-insertion threshold, showing
how aggressively the lru_mid policy needs to observe dead evictions before
switching from MRU to mid-point insertion.

Usage
-----
    python3 scripts/analysis/plot_mid_thd.py <results_dir> \\
        [--max-n N] [--metric ipc|mpki] [--out <path>]

    <results_dir> must contain:
        lru/                    — plain LRU baseline (produced by sweep_mid.sh)
        mid_thd1/ .. mid_thdN/  — varying threshold
"""

import argparse
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ── Simpoint weights ──────────────────────────────────────────────────────────

_DEFAULT_WEIGHTS_DIR = (
    Path(__file__).parents[2] / ".." / "ChampSim-dev" / "trace-files" / "SPEC2006_weights"
).resolve()


def _load_spec_weights(weights_dir: Path) -> "dict[str, float]":
    result: dict = {}
    if not weights_dir.is_dir():
        return result
    for bm_dir in sorted(weights_dir.iterdir()):
        if not bm_dir.is_dir():
            continue
        w_file = bm_dir / "weights.out"
        s_file = bm_dir / "simpoints.out"
        if not (w_file.exists() and s_file.exists()):
            continue
        w_vals = [float(x) for x in w_file.read_text().split()]
        s_ids  = [int(x)   for x in s_file.read_text().split()]
        for sp_id, w in zip(s_ids, w_vals):
            result[f"{bm_dir.name}-{sp_id}B"] = w
    return result


def _benchmark_name(wl: str) -> str:
    """Strip SPEC simpoint suffix: 602.gcc_s-734B -> 602.gcc_s."""
    m = re.match(r'^(.+)-\d+[A-Z]+$', wl)
    return m.group(1) if m else wl


_SPEC_WEIGHTS: "dict[str, float]" = _load_spec_weights(_DEFAULT_WEIGHTS_DIR)


def _benchmark_weighted_geomean_pct(ratios_by_wl: "dict[str, float]") -> float:
    """Benchmark-weighted geomean speedup/reduction (%).

    For SPEC traces (matched by simpoint weights): weighted geomean within each
    benchmark (re-normalised for missing simpoints), then equal-weight geomean
    across benchmarks.  For other traces: flat equal-weight geomean.
    ratios_by_wl values are raw ratios (ipc_new/ipc_base), not percentages.
    Returns % value (0.0 = no change, positive = improvement).
    """
    groups: dict = {}
    for wl, r in ratios_by_wl.items():
        groups.setdefault(_benchmark_name(wl), []).append(wl)
    per_bench = []
    for wl_list in groups.values():
        if _SPEC_WEIGHTS:
            pairs = [(ratios_by_wl[wl], _SPEC_WEIGHTS.get(wl)) for wl in wl_list]
            if any(w is not None for _, w in pairs):
                pairs = [(r, w) for r, w in pairs if w is not None and r > 0]
                total_w = sum(w for _, w in pairs)
                if total_w > 0:
                    per_bench.append(
                        float(np.exp(sum((w / total_w) * np.log(r) for r, w in pairs))))
                    continue
        vals = [ratios_by_wl[wl] for wl in wl_list if ratios_by_wl[wl] > 0]
        if vals:
            per_bench.append(float(np.exp(np.mean(np.log(vals)))))
    if not per_bench:
        return float("nan")
    return (float(np.exp(np.mean(np.log([r for r in per_bench if r > 0])))) - 1) * 100


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


def parse_mpki(path: Path):
    """Return ROI total MPKI (STLB + LLC), or None."""
    in_roi = False
    stlb_miss = llc_miss = instrs = None
    try:
        for line in path.read_text(errors="replace").splitlines():
            if "Region of Interest Statistics" in line:
                in_roi = True
            if not in_roi:
                continue
            if instrs is None and "cumulative IPC:" in line:
                m = re.search(r"instructions:\s+(\d+)", line)
                if m:
                    instrs = int(m.group(1))
            if stlb_miss is None and re.match(r"cpu0_STLB TOTAL\s+ACCESS:", line):
                m = re.search(r"MISS:\s+(\d+)", line)
                if m:
                    stlb_miss = int(m.group(1))
            if llc_miss is None and re.match(r"LLC TOTAL\s+ACCESS:", line):
                m = re.search(r"MISS:\s+(\d+)", line)
                if m:
                    llc_miss = int(m.group(1))
    except OSError:
        pass
    if None not in (stlb_miss, llc_miss, instrs) and instrs > 0:
        return (stlb_miss + llc_miss) / (instrs / 1000)
    return None


def geomean_ratios(pct_list):
    ratios = [v / 100.0 + 1.0 for v in pct_list if not np.isnan(v)]
    if not ratios:
        return float("nan")
    return (np.exp(np.mean(np.log(ratios))) - 1.0) * 100.0


def geomean_ratios_weighted(pct_by_wl: "dict[str, float]") -> float:
    """Wrapper: convert %-speedup dict to ratio dict, apply benchmark-weighted geomean."""
    ratios = {wl: v / 100.0 + 1.0 for wl, v in pct_by_wl.items() if not np.isnan(v)}
    return _benchmark_weighted_geomean_pct(ratios)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("results_dir")
    ap.add_argument("--max-n",   type=int, default=5, dest="max_n",
                    help="Highest mid_thd value present (default: 5)")
    ap.add_argument("--metric",  default="ipc", choices=["ipc", "mpki"])
    ap.add_argument("--mid-key", default=None, choices=["addr", "pc"], dest="mid_key",
                    help="History key used (addr or pc) — added to plot title")
    ap.add_argument("--out",     default=None)
    args = ap.parse_args()

    base = Path(args.results_dir)
    if not base.is_dir():
        sys.exit(f"ERROR: not a directory: {base}")

    baseline_dir = base / "lru" if (base / "lru").is_dir() else base / "baseline"
    if not baseline_dir.is_dir():
        sys.exit(f"ERROR: no baseline found under {base} (expected lru/ or baseline/)")

    parse_fn = parse_ipc if args.metric == "ipc" else parse_mpki

    # Discover traces from baseline dir (supports */champsim.out and *.out layouts)
    out_files = sorted(baseline_dir.glob("*/champsim.out"))
    nested = True
    if not out_files:
        out_files = sorted(baseline_dir.glob("*.out"))
        nested = False
    if not out_files:
        sys.exit(f"ERROR: no output files found in {baseline_dir}")

    traces = [f.parent.name if nested else f.stem for f in out_files]
    print(f"Traces: {len(traces)}  Metric: {args.metric}  max_n: {args.max_n}")

    # Load LRU baselines
    baselines = {}
    for t, f in zip(traces, out_files):
        v = parse_fn(f)
        if v is None:
            print(f"  WARNING: missing baseline for {t}", file=sys.stderr)
        baselines[t] = v
    valid_traces = [t for t in traces if baselines[t] is not None]
    if not valid_traces:
        sys.exit("ERROR: no valid baseline data found")

    # Compute per-threshold geomean speedup / MPKI reduction
    ns = list(range(1, args.max_n + 1))
    agg_values = []
    for n in ns:
        cfg_dir = base / f"mid_thd{n}"
        pct_by_wl: dict = {}
        for t in valid_traces:
            v = parse_fn(cfg_dir / t / "champsim.out")
            if v is None:
                print(f"  WARNING: missing mid_thd{n}/{t}", file=sys.stderr)
                continue
            if args.metric == "ipc":
                pct_by_wl[t] = (v / baselines[t] - 1.0) * 100.0
            else:
                if v == 0:
                    continue  # no misses — skip; can't compute reduction
                pct_by_wl[t] = (baselines[t] / v - 1.0) * 100.0
        agg_values.append(geomean_ratios_weighted(pct_by_wl))

    # ── Plot ──────────────────────────────────────────────────────────────────
    color  = "#1a9850" if args.metric == "ipc" else "#2166ac"
    ylabel = ("IPC speedup vs baseline (%)"
              if args.metric == "ipc"
              else "Total MPKI reduction vs baseline (%, STLB+LLC)")
    key_tag = f", mid_key={args.mid_key}" if args.mid_key else ""
    title  = (f"mid-insertion threshold sweep — {args.metric.upper()} "
              f"(geomean, {len(valid_traces)} traces{key_tag}) — {base.name}")

    fig, ax = plt.subplots(figsize=(max(6, args.max_n + 2), 5))
    bars = ax.bar(range(len(ns)), agg_values,
                  color=color, edgecolor="black", linewidth=0.6)
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--")

    # Zoom y-axis to the data range
    valid_vals = [v for v in agg_values if not np.isnan(v)]
    if valid_vals:
        lo, hi = min(valid_vals), max(valid_vals)
        span = max(hi - lo, 1e-4)
        ax.set_ylim(lo - 0.3 * span, hi + 0.3 * span)

    for bar, v in zip(bars, agg_values):
        if not np.isnan(v):
            yoff = (hi - lo) * 0.03 if valid_vals else 0.05
            label = f"+{v:.2f}%" if v >= 0 else f"{v:.2f}%"
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + yoff,
                    label, ha="center", va="bottom", fontsize=9)

    ax.set_xticks(range(len(ns)))
    ax.set_xticklabels([f"N={n}" for n in ns])
    ax.set_xlabel("Minimum consecutive dead evictions required for mid-insertion (N)",
                  fontsize=10)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.set_title(title, fontsize=11)
    fig.tight_layout()

    out_path = args.out or str(base / f"mid_thd_{args.metric}.png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
