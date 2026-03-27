#!/usr/bin/env python3
"""
plot_liveness.py — plot DoA / mostly-dead / mostly-alive statistics for LLC and STLB.

Usage:
    python3 scripts/plot_liveness.py <results_dir> [--trace TRACE] [--out OUT]

    results_dir   Sweep results directory containing config sub-dirs.
                  Use a single run dir (e.g. cluster_results/foo/baseline/srv_128/)
                  by passing the path to a champsim.out file directly via --file,
                  or pass the parent sweep dir and --trace to pick one trace.

    --file        Path to a single champsim.out file (overrides results_dir logic).
    --trace       Trace name (e.g. srv_128).  Required when results_dir contains many.
    --config      Config sub-dir name inside results_dir (default: baseline).
    --out         Output PNG path (default: liveness_<label>.png).
    --no-hist     Skip the hit-count histogram subplot.

Output
------
  Left panel  – stacked bar chart: % DoA / mostly-dead / mostly-alive for LLC & STLB.
  Right panel – hit-count histogram (# evictions per hit-count bin, log y-axis).
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


# ── Parser ────────────────────────────────────────────────────────────────────

def parse_liveness(filepath):
    """
    Parse a champsim.out file and return a dict keyed by cache name:
      {
        "cpu0_STLB": {"total": N, "doa": N, "mostly_dead": N, "mostly_alive": N,
                      "hit_hist": [n0, n1, ..., n8plus]},
        "LLC":       { ... },
      }
    Returns an empty dict if no liveness lines are found.
    """
    result = {}
    try:
        with open(filepath) as f:
            lines = f.readlines()
    except OSError as e:
        print(f"  ERROR reading {filepath}: {e}", file=sys.stderr)
        return result

    for line in lines:
        # LIVENESS EVICTIONS line
        m = re.match(
            r"(\S+) LIVENESS EVICTIONS:\s+(\d+)"
            r"\s+DOA:\s+(\d+)\s+\([\d.]+%\)"
            r"\s+MOSTLY_DEAD:\s+(\d+)\s+\([\d.]+%\)"
            r"\s+MOSTLY_ALIVE:\s+(\d+)\s+\([\d.]+%\)",
            line,
        )
        if m:
            name = m.group(1)
            result.setdefault(name, {})["total"]       = int(m.group(2))
            result[name]["doa"]         = int(m.group(3))
            result[name]["mostly_dead"] = int(m.group(4))
            result[name]["mostly_alive"]= int(m.group(5))

        # LIVENESS HIT_HIST line
        m2 = re.match(r"(\S+) LIVENESS HIT_HIST:(.*)", line)
        if m2:
            name = m2.group(1)
            rest = m2.group(2)
            # Each token looks like "  0:1234" or "  8+:567"
            hist = []
            for tok in re.finditer(r"(\d+)\+?:(\d+)", rest):
                hist.append(int(tok.group(2)))
            result.setdefault(name, {})["hit_hist"] = hist

    return result


def locate_file(results_dir, config, trace):
    path = os.path.join(results_dir, config, trace, "champsim.out")
    if os.path.isfile(path):
        return path
    # Try without sub-trace dir
    path2 = os.path.join(results_dir, config, "champsim.out")
    if os.path.isfile(path2):
        return path2
    return None


# ── Plotting ──────────────────────────────────────────────────────────────────

COLORS = {
    "doa":         "#d73027",   # red
    "mostly_dead": "#fdae61",   # orange
    "mostly_alive":"#1a9850",   # green
}

HIT_HIST_COLORS = [
    "#d73027", "#f46d43", "#fdae61", "#fee08b",
    "#d9ef8b", "#a6d96a", "#66bd63", "#1a9850", "#006837",
]


def plot_liveness(data_per_cache, label, out_path, show_hist=True):
    """
    data_per_cache: dict  { "LLC": {...}, "cpu0_STLB": {...} }
    """
    caches = [c for c in ["cpu0_STLB", "LLC"] if c in data_per_cache]
    if not caches:
        sys.exit("ERROR: no liveness data found in the output file.")

    ncols = 2 if (show_hist and any("hit_hist" in data_per_cache[c] for c in caches)) else 1
    fig, axes = plt.subplots(1, ncols, figsize=(7 * ncols, 5))
    if ncols == 1:
        axes = [axes]

    # ── Left: stacked bar chart ───────────────────────────────────────────────
    ax = axes[0]
    x = np.arange(len(caches))
    bar_w = 0.45
    display_names = {"cpu0_STLB": "STLB", "LLC": "LLC"}

    bottoms = np.zeros(len(caches))
    pct = {k: [] for k in ("doa", "mostly_dead", "mostly_alive")}
    for c in caches:
        d = data_per_cache[c]
        tot = d.get("total", 1) or 1
        pct["doa"].append(100.0 * d.get("doa", 0) / tot)
        pct["mostly_dead"].append(100.0 * d.get("mostly_dead", 0) / tot)
        pct["mostly_alive"].append(100.0 * d.get("mostly_alive", 0) / tot)

    labels_nice = {"doa": "DoA (0 hits)",
                   "mostly_dead":  "Mostly-dead\n(dead tail > 50%)",
                   "mostly_alive": "Mostly-alive\n(dead tail ≤ 50%)"}
    for key in ("doa", "mostly_dead", "mostly_alive"):
        vals = np.array(pct[key])
        bars = ax.bar(x, vals, bar_w, bottom=bottoms,
                      color=COLORS[key], edgecolor="black", linewidth=0.5,
                      label=labels_nice[key])
        for xi, (b, v) in enumerate(zip(bottoms, vals)):
            if v > 3:
                ax.text(xi, b + v / 2, f"{v:.1f}%",
                        ha="center", va="center", fontsize=9, fontweight="bold",
                        color="white" if v > 12 else "black")
        bottoms += vals

    ax.set_xticks(x)
    ax.set_xticklabels([display_names.get(c, c) for c in caches], fontsize=11)
    ax.set_ylabel("% of evictions", fontsize=11)
    ax.set_ylim(0, 102)
    ax.set_title(f"Block/page liveness at eviction\n{label}", fontsize=11)
    ax.legend(loc="upper right", fontsize=9)

    # Annotate absolute eviction counts
    for xi, c in enumerate(caches):
        tot = data_per_cache[c].get("total", 0)
        ax.text(xi, -6, f"n={tot:,}", ha="center", va="top", fontsize=8, color="gray")

    # ── Right: hit-count histogram ────────────────────────────────────────────
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
            # Pad or trim to n_bins
            hist = (hist + [0] * n_bins)[:n_bins]
            xs = np.arange(n_bins) + offsets[ci]
            ax2.bar(xs, hist, bar_w2,
                    color=[HIT_HIST_COLORS[i % len(HIT_HIST_COLORS)] for i in range(n_bins)],
                    edgecolor="black", linewidth=0.4, alpha=0.85,
                    label=display_names.get(c, c))

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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results_dir", nargs="?", default=None)
    parser.add_argument("--file",   default=None, help="Direct path to champsim.out")
    parser.add_argument("--trace",  default=None)
    parser.add_argument("--config", default="baseline")
    parser.add_argument("--out",    default=None)
    parser.add_argument("--no-hist", action="store_true", dest="no_hist")
    args = parser.parse_args()

    if args.file:
        filepath = args.file
        label = os.path.basename(os.path.dirname(filepath))
    elif args.results_dir:
        base = args.results_dir.rstrip("/")
        label = os.path.basename(base)

        if args.trace:
            trace = args.trace
        else:
            # Auto-detect trace
            config_dir = os.path.join(base, args.config)
            if os.path.isdir(config_dir):
                candidates = [d for d in os.listdir(config_dir)
                              if os.path.isdir(os.path.join(config_dir, d))]
                if len(candidates) == 1:
                    trace = candidates[0]
                elif len(candidates) == 0:
                    # champsim.out directly in config_dir
                    trace = None
                else:
                    sys.exit(f"Multiple traces found: {candidates}\nSpecify one with --trace")
            else:
                sys.exit(f"ERROR: config dir not found: {config_dir}")

        filepath = locate_file(base, args.config, trace) if trace else \
                   os.path.join(base, args.config, "champsim.out")
        if not filepath or not os.path.isfile(filepath):
            sys.exit(f"ERROR: champsim.out not found at {filepath}")
    else:
        parser.print_help()
        sys.exit(1)

    data = parse_liveness(filepath)
    if not data:
        sys.exit(f"ERROR: no LIVENESS lines found in {filepath}\n"
                 "Make sure the simulation was built with liveness tracking enabled.")

    out_path = args.out or f"liveness_{label}.png"
    plot_liveness(data, label, out_path, show_hist=not args.no_hist)


if __name__ == "__main__":
    main()
