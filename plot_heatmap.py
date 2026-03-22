#!/usr/bin/env python3
"""
plot_heatmap.py — IPC speedup heatmap from a ChampSim threshold sweep.

Usage:
    python3 plot_heatmap.py <results_dir> [--trace TRACE] [--out OUTPUT.png]

    results_dir   Base sweep directory, e.g. results/qmm_20260322_debug/
                  Must contain a 'baseline/' sub-dir and pthd{N}_bthd{M}/ dirs.
    --trace       Trace name (e.g. srv_128). Auto-detected if only one trace present.
    --out         Output PNG path. Defaults to heatmap_<trace>_<label>.png
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
    """Return the ROI IPC from a champsim.out file, or None on failure."""
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results_dir")
    parser.add_argument("--trace", default=None, help="Trace name, e.g. srv_128")
    parser.add_argument("--out",   default=None, help="Output PNG path")
    args = parser.parse_args()

    base  = args.results_dir.rstrip("/")
    label = os.path.basename(base)

    # ── Locate baseline ───────────────────────────────────────────────────────
    baseline_dir = os.path.join(base, "baseline")
    if not os.path.isdir(baseline_dir):
        sys.exit(f"ERROR: baseline/ not found under {base}")

    traces = [d for d in os.listdir(baseline_dir)
              if os.path.isdir(os.path.join(baseline_dir, d))]
    if not traces:
        sys.exit(f"ERROR: no trace subdirectories found in {baseline_dir}")

    if args.trace:
        trace = args.trace
    elif len(traces) == 1:
        trace = traces[0]
    else:
        sys.exit(f"Multiple traces found: {traces}\nSpecify one with --trace")

    baseline_ipc = parse_ipc(os.path.join(baseline_dir, trace, "champsim.out"))
    if baseline_ipc is None:
        sys.exit(f"ERROR: could not parse baseline IPC for trace '{trace}'")
    print(f"Baseline IPC ({trace}): {baseline_ipc:.4f}")

    # ── Build 7×7 speedup matrix ──────────────────────────────────────────────
    # data[pthd, bthd] — stored so that pthd=0 is row 0 (displayed at bottom)
    data = np.full((7, 7), np.nan)

    for pthd in range(7):
        for bthd in range(7):
            config   = f"pthd{pthd}_bthd{bthd}"
            out_file = os.path.join(base, config, trace, "champsim.out")
            ipc      = parse_ipc(out_file)
            if ipc is None:
                print(f"  WARNING: missing or unparseable: {out_file}", file=sys.stderr)
                continue
            data[pthd, bthd] = (ipc / baseline_ipc - 1.0) * 100.0

    if np.all(np.isnan(data)):
        sys.exit("ERROR: no valid data points found — did the sweep finish?")

    # ── Plot ──────────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 8))

    vmax = max(np.nanmax(np.abs(data)), 0.1)
    norm = mcolors.TwoSlopeNorm(vmin=-vmax, vcenter=0.0, vmax=vmax)

    im = ax.imshow(data, cmap="RdYlGn", norm=norm,
                   origin="lower", aspect="auto")

    # Colorbar with dashed zero-line
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Speedup / Slowdown (%)", fontsize=11)
    cbar.ax.axhline(0, linestyle="--", color="black", linewidth=1)

    # Annotate each cell
    for pthd in range(7):
        for bthd in range(7):
            val = data[pthd, bthd]
            if not np.isnan(val):
                text = f"+{val:.2f}%" if val >= 0 else f"{val:.2f}%"
                ax.text(bthd, pthd, text, ha="center", va="center", fontsize=9)

    # Axis labels and ticks
    ax.set_xticks(range(7))
    ax.set_xticklabels([f"bthd{i}" for i in range(7)])
    ax.set_yticks(range(7))
    ax.set_yticklabels([f"pthd{i}" for i in range(7)])
    ax.set_xlabel("cbPred threshold (bthd)", fontsize=11)
    ax.set_ylabel("dpPred threshold (pthd)", fontsize=11)

    ax.set_title(
        f"Speedup vs baseline — {trace} — {label}\n(IPC)",
        fontsize=12
    )

    plt.tight_layout()

    out_path = args.out or f"heatmap_{trace}_{label}.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
