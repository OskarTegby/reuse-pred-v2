#!/usr/bin/env python3
"""
plot_heatmap.py — IPC/MPKI/bypass heatmap & dpPred 1-D chart from a ChampSim threshold sweep.

Usage:
    python3 plot_heatmap.py <results_dir> [--trace TRACE] [--metric METRIC] [--dppred] [--out OUT]

    results_dir   Base sweep directory, e.g. cluster_results/qmm_20260322/
                  Must contain a 'baseline/' sub-dir plus pthd{N}/ and pthd{N}_bthd{M}/ dirs.

    --trace       Trace name (e.g. srv_128).  If omitted with multiple traces, geomean is used.

    --metric      ipc              : IPC speedup vs baseline heatmap (default)
                  mpki             : total MPKI reduction vs baseline (STLB+LLC, %)
                  mpki_abs         : absolute total MPKI (STLB+LLC, geomean across traces)
                  stlb_bypass_pct  : STLB bypass % — use with --dppred (dpPred bypasses STLB only)
                  total_bypass_pct : total bypass % (STLB+LLC) — use for 2-D heatmap
                  speedup_range    : max − min IPC speedup across all traces (sensitivity map)
                  dppred           : alias for --metric ipc --dppred (backward compat)

    --dppred      1-D bar chart over pthd0..6 (dpPred-only, cbPred off) instead of 2-D heatmap.
                  Works with any metric.

    --stlb-only   With --dppred and mpki/mpki_abs: count only STLB misses (ignore LLC).
                  Default (without this flag): count STLB+LLC misses, same as the 2-D heatmap.

    --out         Output PNG path.  Defaults to <metric>_<mode>_<trace>_<label>.png

For the mid-insertion threshold sweep (sweep_mid.sh results) use plot_mid_thd.py instead.
"""

import argparse
import os
import re
import sys

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_ipc(filepath):
    """Return ROI cumulative IPC, or None."""
    in_roi = False
    try:
        with open(filepath) as f:
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


def parse_mpki(filepath):
    """Return ROI total MPKI (STLB + LLC misses per kilo-instruction), or None."""
    in_roi = False
    stlb_miss = None
    llc_miss = None
    instrs = None
    try:
        with open(filepath) as f:
            for line in f:
                if "Region of Interest Statistics" in line:
                    in_roi = True
                if in_roi and "cumulative IPC:" in line and instrs is None:
                    m = re.search(r"instructions:\s+(\d+)", line)
                    if m:
                        instrs = int(m.group(1))
                if in_roi and re.match(r"cpu0_STLB TOTAL\s+ACCESS:", line):
                    m = re.search(r"MISS:\s+(\d+)", line)
                    if m:
                        stlb_miss = int(m.group(1))
                if in_roi and re.match(r"LLC TOTAL\s+ACCESS:", line):
                    m = re.search(r"MISS:\s+(\d+)", line)
                    if m:
                        llc_miss = int(m.group(1))
    except OSError:
        pass
    if llc_miss is not None and stlb_miss is not None and instrs is not None and instrs > 0:
        return (stlb_miss + llc_miss) / (instrs / 1000)
    return None


def parse_stlb_mpki(filepath):
    """Return ROI STLB-only MPKI (STLB misses per kilo-instruction), or None."""
    in_roi = False
    stlb_miss = None
    instrs = None
    try:
        with open(filepath) as f:
            for line in f:
                if "Region of Interest Statistics" in line:
                    in_roi = True
                if in_roi and "cumulative IPC:" in line and instrs is None:
                    m = re.search(r"instructions:\s+(\d+)", line)
                    if m:
                        instrs = int(m.group(1))
                if in_roi and re.match(r"cpu0_STLB TOTAL\s+ACCESS:", line):
                    m = re.search(r"MISS:\s+(\d+)", line)
                    if m:
                        stlb_miss = int(m.group(1))
    except OSError:
        pass
    if stlb_miss is not None and instrs is not None and instrs > 0:
        return stlb_miss / (instrs / 1000)
    return None


def parse_llc_bypass_pct(filepath):
    """Return LLC bypass % = LLC_BYPASSES / (LLC_ACCESS + LLC_BYPASSES) * 100, or None."""
    llc_access = None
    llc_bypass = None
    try:
        with open(filepath) as f:
            for line in f:
                if re.match(r"LLC TOTAL\s+ACCESS:", line):
                    m = re.search(r"ACCESS:\s+(\d+)", line)
                    if m:
                        llc_access = int(m.group(1))
                if re.match(r"LLC BYPASSES:", line):
                    m = re.search(r"LLC BYPASSES:\s+(\d+)", line)
                    if m:
                        llc_bypass = int(m.group(1))
    except OSError:
        pass
    if llc_access is not None and llc_bypass is not None:
        total = llc_access + llc_bypass
        return (llc_bypass / total * 100.0) if total > 0 else 0.0
    return None


def parse_stlb_bypass_pct(filepath):
    """Return STLB bypass % = STLB_BYPASSES / (STLB_ACCESS + STLB_BYPASSES) * 100, or None."""
    stlb_access = None
    stlb_bypass = None
    try:
        with open(filepath) as f:
            for line in f:
                if re.match(r"cpu0_STLB TOTAL\s+ACCESS:", line):
                    m = re.search(r"ACCESS:\s+(\d+)", line)
                    if m:
                        stlb_access = int(m.group(1))
                if re.match(r"cpu0_STLB BYPASSES:", line):
                    m = re.search(r"BYPASSES:\s+(\d+)", line)
                    if m:
                        stlb_bypass = int(m.group(1))
    except OSError:
        pass
    if stlb_access is not None and stlb_bypass is not None:
        total = stlb_access + stlb_bypass
        return (stlb_bypass / total * 100.0) if total > 0 else 0.0
    return None


def parse_total_bypass_pct(filepath):
    """Return combined bypass % = (STLB_BYPASSES + LLC_BYPASSES) /
    (STLB_ACCESS + STLB_BYPASSES + LLC_ACCESS + LLC_BYPASSES) * 100, or None."""
    stlb_access = stlb_bypass = llc_access = llc_bypass = None
    try:
        with open(filepath) as f:
            for line in f:
                if re.match(r"cpu0_STLB TOTAL\s+ACCESS:", line):
                    m = re.search(r"ACCESS:\s+(\d+)", line)
                    if m:
                        stlb_access = int(m.group(1))
                if re.match(r"cpu0_STLB BYPASSES:", line):
                    m = re.search(r"BYPASSES:\s+(\d+)", line)
                    if m:
                        stlb_bypass = int(m.group(1))
                if re.match(r"LLC TOTAL\s+ACCESS:", line):
                    m = re.search(r"ACCESS:\s+(\d+)", line)
                    if m:
                        llc_access = int(m.group(1))
                if re.match(r"LLC BYPASSES:", line):
                    m = re.search(r"LLC BYPASSES:\s+(\d+)", line)
                    if m:
                        llc_bypass = int(m.group(1))
    except OSError:
        pass
    if None not in (stlb_access, stlb_bypass, llc_access, llc_bypass):
        total = stlb_access + stlb_bypass + llc_access + llc_bypass
        bypasses = stlb_bypass + llc_bypass
        return (bypasses / total * 100.0) if total > 0 else 0.0
    return None


# ── Per-metric fixed colors for 1-D bar charts ────────────────────────────────
METRIC_COLORS = {
    "ipc":             "#1a9850",  # green  (family 1)
    "mpki":            "#2166ac",  # blue   (family 2)
    "mpki_abs":        "#f46d43",  # orange (family 3)
    "stlb_bypass_pct":  "#762a83",  # purple (family 4)
    "total_bypass_pct": "#762a83",  # purple (family 4)
}

# ── Aggregation helpers ───────────────────────────────────────────────────────

def geomean_ratios(pct_list):
    """Geomean of a list of % speedup/reduction values (ratio-space average)."""
    ratios = [v / 100.0 + 1.0 for v in pct_list if not np.isnan(v)]
    if not ratios:
        return float("nan")
    return (np.exp(np.mean(np.log(ratios))) - 1.0) * 100.0


def geomean_abs(vals):
    """Geomean of a list of absolute values (e.g. MPKI)."""
    pos = [v for v in vals if not np.isnan(v) and v > 0]
    if not pos:
        return float("nan")
    return np.exp(np.mean(np.log(pos)))


def mean_pct(vals):
    """Arithmetic mean for bypass percentages (geomean breaks at 0%)."""
    valid = [v for v in vals if not np.isnan(v)]
    return float(np.mean(valid)) if valid else float("nan")


# ── Plot helpers ──────────────────────────────────────────────────────────────

def _bar_chart(ax, xs, values, ylabel, title, x_labels):
    colors = ["#d73027" if (np.isnan(v) or v < 0) else "#1a9850" for v in values]
    bars = ax.bar(xs, values, color=colors, edgecolor="black", linewidth=0.6)
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
    for bar, v in zip(bars, values):
        if not np.isnan(v):
            yoff = max(abs(v) * 0.02, 0.05)
            yoff = yoff if v >= 0 else -yoff * 3
            label = f"+{v:.2f}%" if v >= 0 else f"{v:.2f}%"
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + yoff,
                    label, ha="center", va="bottom", fontsize=9)
    ax.set_xticks(xs)
    ax.set_xticklabels(x_labels)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.set_title(title, fontsize=12)


def _heatmap(fig, ax, data, cmap, norm, cell_fmt, xlabel, ylabel, title, cbar_label):
    im = ax.imshow(data, cmap=cmap, norm=norm, origin="lower", aspect="auto")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label(cbar_label, fontsize=11)
    for pthd in range(7):
        for bthd in range(7):
            v = data[pthd, bthd]
            if not np.isnan(v):
                ax.text(bthd, pthd, cell_fmt(v), ha="center", va="center", fontsize=9)
    ax.set_xticks(range(7))
    ax.set_xticklabels([str(i) for i in range(7)])
    ax.set_yticks(range(7))
    ax.set_yticklabels([str(i) for i in range(7)])
    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.set_title(title, fontsize=12)
    if isinstance(norm, mcolors.TwoSlopeNorm):
        cbar.ax.axhline(0, linestyle="--", color="black", linewidth=1)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results_dir")
    parser.add_argument("--trace",  default=None)
    parser.add_argument("--metric", default="ipc",
                        choices=["ipc", "mpki", "mpki_abs",
                                 "stlb_bypass_pct", "total_bypass_pct",
                                 "speedup_range", "dppred"])
    parser.add_argument("--dppred", action="store_true",
                        help="1-D chart over pthd0..6 (dpPred-only) instead of 2-D heatmap")
    parser.add_argument("--stlb-only", action="store_true", dest="stlb_only",
                        help="With --dppred and mpki/mpki_abs: use STLB-only misses")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    # backward-compat alias
    if args.metric == "dppred":
        args.metric = "ipc"
        args.dppred = True

    base        = args.results_dir.rstrip("/")
    _raw        = os.path.basename(base).lower()
    _SUITE_NAMES = {
        "dpc3":   "SPEC CPU2006 (DPC3)",
        "google": "Google Warehouse",
        "qmm":    "Qualcomm Mobile",
    }
    label = next((v for k, v in _SUITE_NAMES.items() if _raw.startswith(k)),
                 os.path.basename(base))
    metric      = args.metric
    dppred_mode = args.dppred

    # Map metric → parse function.
    # In dpPred-only mode, MPKI metrics use STLB-only data (LLC is unaffected).
    parse_fn = {"ipc": parse_ipc, "mpki": parse_mpki, "mpki_abs": parse_mpki,
                "stlb_bypass_pct":  parse_stlb_bypass_pct,
                "total_bypass_pct": parse_total_bypass_pct,
                "speedup_range":    parse_ipc}[metric]
    if dppred_mode and args.stlb_only and metric in ("mpki", "mpki_abs"):
        parse_fn = parse_stlb_mpki

    # ── Locate baseline & traces ───────────────────────────────────────────────
    baseline_dir = os.path.join(base, "baseline")
    if not os.path.isdir(baseline_dir):
        sys.exit(f"ERROR: baseline/ not found under {base}")

    all_traces = sorted(d for d in os.listdir(baseline_dir)
                        if os.path.isdir(os.path.join(baseline_dir, d)))
    if not all_traces:
        sys.exit(f"ERROR: no trace subdirectories in {baseline_dir}")

    if args.trace:
        trace_list  = [args.trace]
        trace_label = args.trace
    elif len(all_traces) == 1:
        trace_list  = all_traces
        trace_label = all_traces[0]
    else:
        trace_list  = all_traces
        trace_label = "geomean"
        print(f"Multiple traces ({len(trace_list)}): computing geomean/mean across all.")

    # Baselines are needed for ratio-based metrics; bypass_pct is absolute
    needs_baseline = metric in ("ipc", "mpki", "speedup_range")
    is_bypass = metric in ("stlb_bypass_pct", "total_bypass_pct")
    if needs_baseline:
        baselines = {}
        for t in trace_list:
            v = parse_fn(os.path.join(baseline_dir, t, "champsim.out"))
            if v is None:
                print(f"  WARNING: missing baseline for '{t}'", file=sys.stderr)
            baselines[t] = v
        valid_traces = [t for t in trace_list if baselines[t] is not None]
    else:
        valid_traces = trace_list

    if not valid_traces:
        sys.exit("ERROR: no valid baselines found")

    # ── Per-config value computation ──────────────────────────────────────────

    def config_value(config_dir, trace):
        """Return the scalar metric value for one (config, trace) pair."""
        out_file = os.path.join(base, config_dir, trace, "champsim.out")
        val = parse_fn(out_file)
        if val is None:
            return None
        if metric in ("ipc", "speedup_range"):
            return (val / baselines[trace] - 1.0) * 100.0
        elif metric == "mpki":
            if val == 0:
                return None
            return (baselines[trace] / val - 1.0) * 100.0
        else:  # mpki_abs, bypass_pct — absolute
            return val

    def aggregate(vals):
        """Aggregate a list of per-trace values into a single scalar."""
        if not vals:
            return float("nan")
        if metric == "speedup_range":
            return max(vals) - min(vals)
        elif metric in ("ipc", "mpki"):
            return geomean_ratios(vals)
        elif metric == "mpki_abs":
            return geomean_abs(vals)
        else:  # stlb_bypass_pct, llc_bypass_pct — arithmetic mean (can be 0%)
            return mean_pct(vals)

    def collect(config_dir):
        vals = []
        for t in valid_traces:
            v = config_value(config_dir, t)
            if v is None:
                print(f"  WARNING: missing: {os.path.join(base, config_dir, t, 'champsim.out')}",
                      file=sys.stderr)
            else:
                vals.append(v)
        return aggregate(vals)

    # ── 1-D dpPred-only chart ─────────────────────────────────────────────────
    if dppred_mode:
        values = [collect(f"pthd{i}") for i in range(7)]

        metric_labels = {
            "ipc":              ("IPC speedup vs baseline (%)",       "dpPred-only IPC speedup"),
            "mpki":     ("STLB MPKI reduction vs baseline (%)"       if args.stlb_only else "Total MPKI reduction vs baseline (%, STLB+LLC)",
                         "dpPred-only STLB MPKI reduction"            if args.stlb_only else "dpPred-only MPKI reduction"),
            "mpki_abs": ("STLB MPKI (geomean)"                        if args.stlb_only else "Total MPKI (STLB+LLC, geomean)",
                         "dpPred-only STLB MPKI (absolute)"           if args.stlb_only else "dpPred-only total MPKI (absolute)"),
            "stlb_bypass_pct":  ("STLB bypass %",         "dpPred-only STLB bypass %"),
            "total_bypass_pct": ("Total bypass % (STLB+LLC)", "dpPred-only total bypass %"),
        }
        ylabel, chart_title = metric_labels[metric]
        title = f"{chart_title} — {trace_label} — {label}"
        color = METRIC_COLORS[metric]
        fig, ax = plt.subplots(figsize=(8, 5))

        if metric == "mpki_abs":
            # Truncate y-axis so small differences are visible
            bars = ax.bar(range(7), values, color=color, edgecolor="black", linewidth=0.6)
            valid_vals = [v for v in values if not np.isnan(v)]
            ymin = min(valid_vals) * 0.998
            ymax = max(valid_vals) * 1.004
            ax.set_ylim(ymin, ymax)
            for bar, v in zip(bars, values):
                if not np.isnan(v):
                    ax.text(bar.get_x() + bar.get_width() / 2,
                            bar.get_height() + (ymax - ymin) * 0.01,
                            f"{v:.3f}", ha="center", va="bottom", fontsize=9)
        else:
            bars = ax.bar(range(7), values, color=color, edgecolor="black", linewidth=0.6)
            ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
            fmt = (lambda v: f"{v:.2f}%") if is_bypass else \
                  (lambda v: f"+{v:.2f}%" if v >= 0 else f"{v:.2f}%")
            for bar, v in zip(bars, values):
                if not np.isnan(v):
                    yoff = max(abs(v) * 0.02, 0.05) * (1 if v >= 0 else -3)
                    ax.text(bar.get_x() + bar.get_width() / 2,
                            bar.get_height() + yoff,
                            fmt(v), ha="center", va="bottom", fontsize=9)

        ax.set_xticks(range(7))
        ax.set_xticklabels([f"pthd{i}" for i in range(7)])
        ax.set_xlabel("dpPred threshold (pthd)", fontsize=11)
        ax.set_ylabel(ylabel, fontsize=11)
        ax.set_title(title, fontsize=12)

        plt.tight_layout()
        out_path = args.out or f"dppred_{metric}_{trace_label}_{label}.png"
        plt.savefig(out_path, dpi=150, bbox_inches="tight")
        print(f"Saved: {out_path}")
        return

    # ── 2-D heatmap ───────────────────────────────────────────────────────────
    data = np.full((7, 7), np.nan)
    for pthd in range(7):
        for bthd in range(7):
            data[pthd, bthd] = collect(f"pthd{pthd}_bthd{bthd}")

    if np.all(np.isnan(data)):
        sys.exit("ERROR: no valid data — did the sweep finish?")

    fig, ax = plt.subplots(figsize=(10, 8))

    if metric == "speedup_range":
        norm      = mcolors.Normalize(vmin=0, vmax=np.nanmax(data))
        cmap      = "YlOrRd"
        cell_fmt  = lambda v: f"{v:.2f}pp"
        cbar_lbl  = "Speedup range (max − min, pp)"
        title_str = f"IPC speedup range across workloads — {label}"
    elif metric == "mpki_abs":
        norm      = mcolors.Normalize(vmin=np.nanmin(data), vmax=np.nanmax(data))
        cmap      = "Oranges"          # orange — family 3
        cell_fmt  = lambda v: f"{v:.2f}"
        cbar_lbl  = "Total MPKI (STLB+LLC, geomean)"
        title_str = f"Total MPKI absolute (STLB+LLC) — {trace_label} — {label}"
    elif is_bypass:
        norm      = mcolors.Normalize(vmin=0, vmax=max(np.nanmax(data), 1))
        cmap      = "Purples"          # purple — family 4
        cell_fmt  = lambda v: f"{v:.1f}%"
        bypass_names = {"stlb_bypass_pct":  "STLB bypass %",
                        "total_bypass_pct":  "Total bypass % (STLB+LLC)"}
        cbar_lbl  = bypass_names[metric]
        title_str = f"{cbar_lbl} — {trace_label} — {label}"
    else:
        vmax      = max(np.nanmax(np.abs(data)), 0.1)
        norm      = mcolors.TwoSlopeNorm(vmin=-vmax, vcenter=0.0, vmax=vmax)
        cmap      = "RdYlGn" if metric == "ipc" else "RdYlBu"  # green / blue — families 1 & 2
        cell_fmt  = lambda v: f"+{v:.2f}%" if v >= 0 else f"{v:.2f}%"
        if metric == "ipc":
            cbar_lbl  = "Speedup / Slowdown (%)"
            title_str = f"IPC speedup vs baseline — {trace_label} — {label}"
        else:
            cbar_lbl  = "Total MPKI Reduction / Increase (%, STLB+LLC)"
            title_str = f"Total MPKI reduction vs baseline (STLB+LLC) — {trace_label} — {label}"

    _heatmap(fig, ax, data, cmap, norm, cell_fmt,
             xlabel="cbPred threshold (bthd)",
             ylabel="dpPred threshold (pthd)",
             title=title_str,
             cbar_label=cbar_lbl)

    plt.tight_layout()
    out_path = args.out or f"heatmap_{metric}_{trace_label}_{label}.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
