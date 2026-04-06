#!/usr/bin/env python3
"""plot_liveness_bar.py — per-workload liveness bar chart (Figures 2 & 4 style).

Reproduces the style of Figures 2 and 4 in Mazumdar et al. (HPCA 2021):
one stacked bar per workload, showing the fraction of evictions that are
DoA / mostly-dead / mostly-alive.  Two panels: one for the STLB, one for the LLC.

Bars are sorted by descending (DoA + mostly-dead) fraction so the worst
workloads appear on the left, matching the paper's presentation.

Usage
-----
    # All *.out files in a directory (one bar per file)
    python3 scripts/plot_liveness_bar.py results/maz_<date>/baseline/ \\
        --out maz_liveness_bar.png

    # Multiple suites side-by-side (one panel per suite, or interleaved)
    python3 scripts/plot_liveness_bar.py \\
        results/maz_<date>/baseline/ results/qmm_<date>/baseline/ \\
        --labels maz qmm --out liveness_bar.png
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

# Soft, muted palette — easy on the eye
COLOR_DOA  = "#5B7FA6"   # steel blue   – DoA
COLOR_MD   = "#E8A87C"   # soft peach   – mostly-dead
COLOR_MA   = "#7CB9A8"   # soft teal    – mostly-alive

HATCH_DOA  = ""
HATCH_MD   = ""
HATCH_MA   = ""

# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_liveness_file(path: Path):
    """Return dict { cache_name: {doa, mostly_dead, mostly_alive, total} }."""
    text = path.read_text(errors="replace")
    result = {}
    pat = re.compile(
        r"^(\S+) LIVENESS EVICTIONS:\s+(\d+)"
        r"\s+DOA:\s+(\d+)\s+\([\d.]+%\)"
        r"\s+MOSTLY_DEAD:\s+(\d+)\s+\([\d.]+%\)"
        r"\s+MOSTLY_ALIVE:\s+(\d+)\s+\([\d.]+%\)",
        re.MULTILINE,
    )
    for m in pat.finditer(text):
        result[m.group(1)] = {
            "total":        int(m.group(2)),
            "doa":          int(m.group(3)),
            "mostly_dead":  int(m.group(4)),
            "mostly_alive": int(m.group(5)),
        }
    return result


def load_suite(results_dir: Path):
    """Load all champsim.out files.

    Supports two layouts:
      Flat  (local runs):   <dir>/<trace>.out
      Nested (cluster runs): <dir>/<trace>/champsim.out
    """
    files = sorted(results_dir.glob("*/champsim.out"))  # cluster layout
    nested = True
    if not files:
        files = sorted(results_dir.glob("*.out"))        # flat layout
        nested = False
    if not files:
        sys.exit(f"ERROR: no output files found in {results_dir}\n"
                 "Expected either <dir>/*.out or <dir>/*/champsim.out")
    rows = []
    for f in files:
        workload = f.parent.name if nested else f.stem
        data = parse_liveness_file(f)
        if not data:
            print(f"  WARNING: no LIVENESS lines in {f} — skipped")
            continue
        rows.append((workload, data))
    return rows


# ── Plot ──────────────────────────────────────────────────────────────────────

def plot_cache_panel(ax, rows, cache_name, sort_by_dead=True):
    """Draw one panel (one cache) onto ax.  rows = [(label, data_dict), ...]."""
    # Filter to workloads that have data for this cache
    valid = [(lbl, d[cache_name]) for lbl, d in rows if cache_name in d]
    if not valid:
        ax.set_visible(False)
        return

    if sort_by_dead:
        valid.sort(key=lambda r: (r[1]["doa"] + r[1]["mostly_dead"]) /
                                  max(r[1]["total"], 1),
                   reverse=True)

    labels = [lbl for lbl, _ in valid]
    totals = np.array([d["total"] for _, d in valid], dtype=float)
    doa_pct = np.array([d["doa"] for _, d in valid]) / np.where(totals > 0, totals, 1) * 100
    md_pct  = np.array([d["mostly_dead"]  for _, d in valid]) / np.where(totals > 0, totals, 1) * 100
    ma_pct  = np.array([d["mostly_alive"] for _, d in valid]) / np.where(totals > 0, totals, 1) * 100

    # ── Geomean bar: geomean of each fraction, renormalised to sum to 100% ─────
    # Clip to a small epsilon before log so zero fractions don't collapse to -inf.
    eps = 1e-6
    gm_ma  = np.exp(np.mean(np.log(np.clip(ma_pct,  eps, None))))
    gm_md  = np.exp(np.mean(np.log(np.clip(md_pct,  eps, None))))
    gm_doa = np.exp(np.mean(np.log(np.clip(doa_pct, eps, None))))
    gm_sum = gm_ma + gm_md + gm_doa
    gm_ma  = gm_ma  / gm_sum * 100
    gm_md  = gm_md  / gm_sum * 100
    gm_doa = gm_doa / gm_sum * 100

    # Append geomean as a separate bar, separated by a gap
    n = len(labels)
    gap = 1.2          # extra space between workloads and geomean bar
    x_wl = np.arange(n)
    x_gm = n + gap     # geomean bar position

    w = 0.6

    def draw_bars(xs, ma, md, doa, width, legend=True):
        kw = dict(edgecolor="black", linewidth=0.5)
        ax.bar(xs, ma,  width, label="Mostly-alive" if legend else "_", color=COLOR_MA,  **kw)
        ax.bar(xs, md,  width, bottom=ma,       label="Mostly-dead" if legend else "_", color=COLOR_MD,  **kw)
        ax.bar(xs, doa, width, bottom=ma + md,  label="DoA"         if legend else "_", color=COLOR_DOA, **kw)

    draw_bars(x_wl, ma_pct, md_pct, doa_pct, w, legend=True)
    draw_bars(x_gm, gm_ma,  gm_md,  gm_doa,  w * 1.1, legend=False)

    # Value labels inside individual bars
    for i, (ma, md, doa) in enumerate(zip(ma_pct, md_pct, doa_pct)):
        if ma  > 4: ax.text(i, ma / 2,          f"{ma:.0f}%",  ha="center", va="center", fontsize=6.5, color="white", fontweight="bold")
        if md  > 4: ax.text(i, ma + md / 2,     f"{md:.0f}%",  ha="center", va="center", fontsize=6.5, color="black", fontweight="bold")
        if doa > 4: ax.text(i, ma + md + doa/2, f"{doa:.0f}%", ha="center", va="center", fontsize=6.5, color="white", fontweight="bold")

    # Value labels inside geomean bar
    for val, base, color in [
        (gm_ma,  0,              "white"),
        (gm_md,  gm_ma,          "black"),
        (gm_doa, gm_ma + gm_md,  "white"),
    ]:
        if val > 4:
            ax.text(x_gm, base + val / 2, f"{val:.0f}%",
                    ha="center", va="center", fontsize=7, color=color, fontweight="bold")

    # Vertical separator line between workloads and geomean
    ax.axvline(n + gap / 2, color="gray", linewidth=0.8, linestyle=":", zorder=1)

    display = {"cpu0_STLB": "STLB", "LLC": "LLC"}
    all_x      = list(x_wl) + [x_gm]
    all_labels = labels + ["Geomean"]
    ax.set_xticks(all_x)
    ax.set_xticklabels(all_labels, rotation=35, ha="right", fontsize=8)
    # Make the Geomean label bold
    for tick, lbl in zip(ax.get_xticklabels(), all_labels):
        if lbl == "Geomean":
            tick.set_fontweight("bold")
    ax.set_ylabel("Evictions (%)", fontsize=10)
    ax.set_xlim(-0.7, x_gm + 0.7)
    ax.set_ylim(0, 105)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.set_title(f"{display.get(cache_name, cache_name)} evictions", fontsize=11)
    ax.legend(loc="lower left", fontsize=8, framealpha=0.8)
    ax.grid(axis="y", alpha=0.3, linewidth=0.5)


# ── Main ──────────────────────────────────────────────────────────────────────

def suite_geomean_row(label: str, rows: list, cache: str):
    """Collapse all workloads in a suite into a single geomean row for that cache."""
    eps = 1e-6
    doa_rates, md_rates, ma_rates = [], [], []
    for _, data in rows:
        d = data.get(cache, {})
        tot = d.get("total", 0) or 1
        doa_rates.append(d.get("doa", 0) / tot * 100)
        md_rates.append(d.get("mostly_dead", 0) / tot * 100)
        ma_rates.append(d.get("mostly_alive", 0) / tot * 100)
    if not doa_rates:
        return None
    gm_doa = np.exp(np.mean(np.log(np.clip(doa_rates, eps, None))))
    gm_md  = np.exp(np.mean(np.log(np.clip(md_rates,  eps, None))))
    gm_ma  = np.exp(np.mean(np.log(np.clip(ma_rates,  eps, None))))
    gm_sum = gm_doa + gm_md + gm_ma
    # Synthetic data dict that plot_cache_panel can consume
    n = len(doa_rates)
    return (label, {cache: {
        "total":        n,
        "doa":          int(gm_doa / gm_sum * n),
        "mostly_dead":  int(gm_md  / gm_sum * n),
        "mostly_alive": int(gm_ma  / gm_sum * n),
    }})


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("results_dirs", nargs="+",
                    help="Directories containing *.out files (one per suite)")
    ap.add_argument("--labels", nargs="*",
                    help="Suite labels (default: directory names)")
    ap.add_argument("--out",    default="liveness_bar.png",
                    help="Output PNG (default: liveness_bar.png)")
    ap.add_argument("--no-sort", action="store_true",
                    help="Keep workloads in filename order instead of sorting by dead fraction")
    ap.add_argument("--summary", action="store_true",
                    help="Show one geomean bar per suite (policy comparison) instead of one bar per workload")
    args = ap.parse_args()

    dirs = [Path(d) for d in args.results_dirs]
    for d in dirs:
        if not d.is_dir():
            sys.exit(f"ERROR: {d} is not a directory")

    labels = args.labels or [d.parent.name if d.name == "baseline" else d.name
                              for d in dirs]
    if len(labels) != len(dirs):
        sys.exit("ERROR: --labels count must match number of directories")

    # Load all suites
    suites = []
    for lbl, d in zip(labels, dirs):
        print(f"Loading '{lbl}' from {d} ...")
        suite_rows = load_suite(d)
        suites.append((lbl, suite_rows))
        print(f"  {len(suite_rows)} workloads")

    if not suites:
        sys.exit("ERROR: no data loaded")

    suite_desc = " + ".join(labels)
    out_path_obj = Path(args.out)
    out_stem = out_path_obj.stem
    out_suffix = out_path_obj.suffix or ".png"
    out_dir = out_path_obj.parent

    cache_display = {"cpu0_STLB": "STLB", "LLC": "LLC"}
    for cache in ["cpu0_STLB", "LLC"]:
        if args.summary:
            # One geomean bar per suite — policy comparison view
            all_rows = [r for lbl, rows in suites
                        for r in [suite_geomean_row(lbl, rows, cache)] if r]
            fig_w = max(6, len(all_rows) * 1.0 + 2)
        else:
            # One bar per workload across all suites
            all_rows = []
            for lbl, rows in suites:
                tagged = [(f"{lbl}/{wl}" if len(suites) > 1 else wl, data)
                          for wl, data in rows]
                all_rows.extend(tagged)
            fig_w = max(8, len(all_rows) * 0.55 + 3)

        if not all_rows:
            print(f"  WARNING: no data for {cache} — skipped")
            continue

        fig, ax = plt.subplots(figsize=(fig_w, 6))
        plot_cache_panel(ax, all_rows, cache, sort_by_dead=not args.no_sort and not args.summary)
        title = (f"{cache_display[cache]} liveness at eviction"
                 if args.summary else
                 f"{cache_display[cache]} liveness at eviction — {suite_desc}")
        fig.suptitle(title, fontsize=12)
        fig.tight_layout()
        out_path = str(out_dir / f"{out_stem}_{cache_display[cache]}{out_suffix}")
        fig.savefig(out_path, dpi=200, bbox_inches="tight")
        plt.close(fig)
        print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
