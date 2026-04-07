#!/usr/bin/env python3
"""plot_suite_liveness.py — aggregate liveness bar and distribution plots across suites.

Produces per-cache figures (saved as <out>_<cache>_<kind>.png):
  bar       — aggregate stacked bar, one bar per suite (geomean across workloads)
              showing DoA / mostly-dead / mostly-alive fractions.
  lorenz    — eviction-weighted Lorenz curves, one curve per suite, showing
              how concentrated DoA / mostly-dead evictions are across workloads.
  cdf_pooled    — hit-count CDF with all evictions pooled per suite.
  cdf_per_wl    — hit-count CDF with per-workload curves + bold pooled line.

Usage
-----
    python3 scripts/analysis/plot_suite_liveness.py \\
        --dpc3   results/dpc3_pol_<date>/lru \\
        --google results/google_pol_<date>/lru \\
        --qmm    results/qmm_pol_<date>/lru \\
        [--labels "SPEC" "Google" "Qualcomm"] \\
        [--out    plots/suite_liveness]
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

# ── Palette ───────────────────────────────────────────────────────────────────

COLOR_DOA = "#5B7FA6"   # steel blue
COLOR_MD  = "#E8A87C"   # soft peach
COLOR_MA  = "#7CB9A8"   # soft teal

SUITE_COLORS = ["#2C7BB6", "#D7191C", "#1A9641"]   # blue / red / green

CACHE_DISPLAY = {"cpu0_STLB": "STLB", "LLC": "LLC"}
X_COMMON = np.linspace(0, 1, 1000)


# ── Parsing ───────────────────────────────────────────────────────────────────

N_HIST_BINS = 9
HIST_LABELS = ["0", "1", "2", "3", "4", "5", "6", "7", "8+"]


def parse_liveness_file(path: Path):
    """Return dict { cache_name: {doa, mostly_dead, mostly_alive, total, hit_hist} }."""
    text = path.read_text(errors="replace")
    result = {}

    evict_pat = re.compile(
        r"^(\S+) LIVENESS EVICTIONS:\s+(\d+)"
        r"\s+DOA:\s+(\d+)\s+\([\d.]+%\)"
        r"\s+MOSTLY_DEAD:\s+(\d+)\s+\([\d.]+%\)"
        r"\s+MOSTLY_ALIVE:\s+(\d+)\s+\([\d.]+%\)",
        re.MULTILINE,
    )
    for m in evict_pat.finditer(text):
        result[m.group(1)] = {
            "total":        int(m.group(2)),
            "doa":          int(m.group(3)),
            "mostly_dead":  int(m.group(4)),
            "mostly_alive": int(m.group(5)),
            "hit_hist":     np.zeros(N_HIST_BINS, dtype=float),
        }

    hist_pat = re.compile(r"^(\S+) LIVENESS HIT_HIST:(.*)", re.MULTILINE)
    for m in hist_pat.finditer(text):
        name = m.group(1)
        counts = re.findall(r"(\d+)\+?:(\d+)", m.group(2))
        hist = np.zeros(N_HIST_BINS, dtype=float)
        for idx_str, cnt_str in counts:
            idx = min(int(idx_str), N_HIST_BINS - 1)
            hist[idx] += int(cnt_str)
        if name in result:
            result[name]["hit_hist"] = hist

    return result


def load_suite(results_dir: Path):
    """Load all champsim.out files. Returns list of (workload_name, data_dict)."""
    files = sorted(results_dir.glob("*/champsim.out"))
    nested = True
    if not files:
        files = sorted(results_dir.glob("*.out"))
        nested = False
    if not files:
        sys.exit(f"ERROR: no output files found in {results_dir}")
    rows = []
    for f in files:
        workload = f.parent.name if nested else f.stem
        data = parse_liveness_file(f)
        if not data:
            print(f"  WARNING: no LIVENESS lines in {f} — skipped")
            continue
        rows.append((workload, data))
    return rows


# ── Geomean helper ────────────────────────────────────────────────────────────

def geomean(values, eps=1e-6):
    arr = np.clip(np.asarray(values, dtype=float), eps, None)
    return float(np.exp(np.mean(np.log(arr))))


def suite_geomean_fracs(rows, cache):
    """Return (gm_doa_pct, gm_md_pct, gm_ma_pct) renormalised to sum to 100."""
    doa_rates, md_rates, ma_rates = [], [], []
    for _, data in rows:
        d = data.get(cache, {})
        tot = d.get("total", 0) or 1
        doa_rates.append(d.get("doa", 0) / tot * 100)
        md_rates.append(d.get("mostly_dead", 0) / tot * 100)
        ma_rates.append(d.get("mostly_alive", 0) / tot * 100)
    if not doa_rates:
        return None
    gm_doa = geomean(doa_rates)
    gm_md  = geomean(md_rates)
    gm_ma  = geomean(ma_rates)
    total  = gm_doa + gm_md + gm_ma
    return gm_doa / total * 100, gm_md / total * 100, gm_ma / total * 100


# ── Figure 1: aggregate stacked bar ──────────────────────────────────────────

def plot_aggregate_bar(suites, cache, out_path: Path):
    """One stacked bar per suite (geomean across workloads): DoA / mostly-dead / mostly-alive."""
    labels, doa_vals, md_vals, ma_vals = [], [], [], []
    for lbl, rows in suites:
        result = suite_geomean_fracs(rows, cache)
        if result is None:
            print(f"  WARNING: no data for {cache} in suite '{lbl}' — skipped")
            continue
        gm_doa, gm_md, gm_ma = result
        labels.append(lbl)
        doa_vals.append(gm_doa)
        md_vals.append(gm_md)
        ma_vals.append(gm_ma)

    if not labels:
        print(f"  WARNING: nothing to plot for {cache} bar — skipping")
        return

    n = len(labels)
    x = np.arange(n)
    w = 0.5
    doa_arr = np.array(doa_vals)
    md_arr  = np.array(md_vals)
    ma_arr  = np.array(ma_vals)

    fig, ax = plt.subplots(figsize=(max(4, n * 1.4 + 2), 5))

    kw = dict(width=w, edgecolor="black", linewidth=0.7)
    ax.bar(x, doa_arr, bottom=np.zeros(n),     label="Dead-on-arrival (DoA)", color=COLOR_DOA, **kw)
    ax.bar(x, md_arr,  bottom=doa_arr,          label="Mostly-dead",           color=COLOR_MD,  **kw)
    ax.bar(x, ma_arr,  bottom=doa_arr + md_arr, label="Mostly-alive",          color=COLOR_MA,  **kw)

    for i in range(n):
        doa, md, ma = doa_arr[i], md_arr[i], ma_arr[i]
        if doa > 3: ax.text(i, doa / 2,           f"{doa:.1f}%", ha="center", va="center", fontsize=9, color="white", fontweight="bold")
        if md  > 3: ax.text(i, doa + md / 2,      f"{md:.1f}%",  ha="center", va="center", fontsize=9, color="black", fontweight="bold")
        if ma  > 3: ax.text(i, doa + md + ma / 2, f"{ma:.1f}%",  ha="center", va="center", fontsize=9, color="white", fontweight="bold")

    cache_name = CACHE_DISPLAY.get(cache, cache)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=12)
    ax.set_ylabel("Evictions (%)", fontsize=11)
    ax.set_ylim(0, 108)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.set_title(f"{cache_name} evictions by liveness class\n(geomean across workloads per suite)", fontsize=11)
    ax.legend(loc="upper right", fontsize=9, framealpha=0.85)
    ax.grid(axis="y", alpha=0.3, linewidth=0.5)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


# ── Figure 2: eviction-weighted Lorenz curves ─────────────────────────────────

def eviction_weighted_lorenz(rows, cache, field):
    """Return (x, y) eviction-weighted Lorenz curve for one suite.

    Workloads sorted ascending by dead-class rate.
    x = cumulative fraction of total evictions, y = cumulative fraction of dead evictions.
    """
    points = []
    for _, data in rows:
        d = data.get(cache, {})
        total = d.get("total", 0)
        dead  = d.get(field, 0)
        if total == 0:
            continue
        points.append((dead / total, total, dead))
    if not points:
        return np.array([0.0, 1.0]), np.array([0.0, 1.0])
    points.sort(key=lambda p: p[0])
    totals = np.array([p[1] for p in points], dtype=float)
    deads  = np.array([p[2] for p in points], dtype=float)
    cum_total = np.concatenate([[0.0], np.cumsum(totals)])
    cum_dead  = np.concatenate([[0.0], np.cumsum(deads)])
    x = cum_total / cum_total[-1]
    y = cum_dead  / cum_dead[-1] if cum_dead[-1] > 0 else np.zeros_like(cum_total)
    return x, y


def plot_lorenz(suites, cache, out_path: Path):
    """Eviction-weighted Lorenz curves: DoA (left) and mostly-dead (right), one curve per suite."""
    cache_name = CACHE_DISPLAY.get(cache, cache)
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))

    for ax, (field, title) in zip(axes, [("doa", "Dead-on-arrival (DoA)"),
                                          ("mostly_dead", "Mostly-dead")]):
        ax.plot([0, 1], [0, 1], color="gray", linewidth=1, linestyle="--",
                label="Uniform rate", zorder=1)
        for (lbl, rows), color in zip(suites, SUITE_COLORS):
            x, y = eviction_weighted_lorenz(rows, cache, field)
            total_evict = sum(d.get(cache, {}).get("total", 0) for _, d in rows)
            total_dead  = sum(d.get(cache, {}).get(field,   0) for _, d in rows)
            rate = total_dead / total_evict * 100 if total_evict > 0 else 0
            ax.plot(x, y, color=color, linewidth=2, label=f"{lbl}  (overall {rate:.1f}%)")
            ax.fill_between(x, x, y, alpha=0.08, color=color)
        ax.set_xlabel("Cumulative % of total evictions", fontsize=10)
        ax.set_ylabel(f"Cumulative % of {title.split()[0]} evictions", fontsize=10)
        ax.set_title(f"{cache_name} — {title}", fontsize=11)
        ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        ax.xaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
        ax.legend(fontsize=9, loc="upper left", framealpha=0.85)
        ax.grid(alpha=0.25, linewidth=0.5)

    fig.suptitle(f"{cache_name} — eviction-weighted Lorenz curves\n"
                 "(workloads sorted ascending by rate; diagonal = uniform rate)", fontsize=11)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


# ── Shared CDF helpers ────────────────────────────────────────────────────────

def _pooled_hist(rows, cache):
    """Sum raw hit_hist counts across all workloads."""
    hist = np.zeros(N_HIST_BINS, dtype=float)
    total = doa_total = md_total = 0
    for _, data in rows:
        d = data.get(cache, {})
        hist      += d.get("hit_hist", np.zeros(N_HIST_BINS))
        total     += d.get("total",       0)
        doa_total += d.get("doa",         0)
        md_total  += d.get("mostly_dead", 0)
    return hist, doa_total, md_total, total


def _cdf_axes(ax, cache_name, title_suffix=""):
    ax.set_xlabel("Hit count at eviction", fontsize=10)
    ax.set_ylabel("Cumulative % of evictions", fontsize=10)
    ax.set_xticks(np.arange(N_HIST_BINS))
    ax.set_xticklabels(HIST_LABELS, fontsize=9)
    ax.set_ylim(0, 103)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.grid(alpha=0.3, linewidth=0.5)
    if title_suffix:
        ax.set_title(f"{cache_name}{title_suffix}", fontsize=10)


# ── Figure 3a: pooled hit-count CDF ──────────────────────────────────────────

def plot_hit_cdf_pooled(suites, cache, out_path: Path):
    """CDF of hit count at eviction — raw counts pooled across all workloads per suite."""
    from matplotlib.lines import Line2D
    cache_name = CACHE_DISPLAY.get(cache, cache)
    fig, ax = plt.subplots(figsize=(7, 5))
    x_ticks = np.arange(N_HIST_BINS)

    for (lbl, rows), color in zip(suites, SUITE_COLORS):
        hist, doa_tot, md_tot, total = _pooled_hist(rows, cache)
        if total == 0:
            continue
        cdf = np.cumsum(hist / hist.sum()) * 100
        ax.step(x_ticks, cdf, where="post", color=color, linewidth=2, label=lbl)
        ax.plot(x_ticks, cdf, "o", color=color, markersize=5)
        ax.axhline(doa_tot / total * 100,              color=color, linewidth=0.8, linestyle=":",  alpha=0.7)
        ax.axhline((doa_tot + md_tot) / total * 100,  color=color, linewidth=0.8, linestyle="--", alpha=0.7)

    ax.legend(
        handles=ax.lines[:len(suites)] + [
            Line2D([0], [0], color="gray", linewidth=0.8, linestyle=":",  label="DoA rate"),
            Line2D([0], [0], color="gray", linewidth=0.8, linestyle="--", label="DoA + mostly-dead rate"),
        ],
        fontsize=9, framealpha=0.85,
    )
    _cdf_axes(ax, cache_name)
    ax.set_title(f"{cache_name} — hit-count CDF (pooled)\n"
                 "dotted = DoA rate · dashed = DoA + mostly-dead rate", fontsize=10)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


# ── Figure 3b: per-workload hit-count CDF ────────────────────────────────────

def plot_hit_cdf_per_workload(suites, cache, out_path: Path):
    """Per-workload CDF of hit count — one panel per suite, thin per-workload + bold pooled."""
    cache_name = CACHE_DISPLAY.get(cache, cache)
    n = len(suites)
    fig, axes = plt.subplots(1, n, figsize=(5 * n, 5), sharey=True)
    if n == 1:
        axes = [axes]
    x_ticks = np.arange(N_HIST_BINS)

    for ax, (lbl, rows), color in zip(axes, suites, SUITE_COLORS):
        for _, data in rows:
            d = data.get(cache, {})
            hist = d.get("hit_hist", np.zeros(N_HIST_BINS))
            if hist.sum() == 0:
                continue
            ax.step(x_ticks, np.cumsum(hist / hist.sum()) * 100,
                    where="post", color=color, linewidth=0.6, alpha=0.25)
        hist_pool, doa_tot, md_tot, total = _pooled_hist(rows, cache)
        if total > 0:
            cdf_pool = np.cumsum(hist_pool / hist_pool.sum()) * 100
            ax.step(x_ticks, cdf_pool, where="post", color=color, linewidth=2.5,
                    label=f"{lbl} (pooled)")
            ax.plot(x_ticks, cdf_pool, "o", color=color, markersize=5)
            dead_pct = (doa_tot + md_tot) / total * 100
            ax.axhline(dead_pct, color="black", linewidth=0.9, linestyle="--",
                       alpha=0.6, label=f"DoA+MD: {dead_pct:.1f}%")
        ax.legend(fontsize=8, framealpha=0.85)
        _cdf_axes(ax, cache_name, f" — {lbl}")

    axes[0].set_ylabel("Cumulative % of evictions", fontsize=10)
    fig.suptitle(f"{cache_name} — per-workload hit-count CDF\n"
                 "(thin = workloads · bold = pooled · dashed = DoA+mostly-dead)", fontsize=10)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--dpc3",   required=True, metavar="DIR")
    ap.add_argument("--google", required=True, metavar="DIR")
    ap.add_argument("--qmm",    required=True, metavar="DIR")
    ap.add_argument("--labels", nargs=3, default=["SPEC", "Google", "Qualcomm"],
                    metavar=("L1", "L2", "L3"))
    ap.add_argument("--out", default="plots/suite_liveness")
    args = ap.parse_args()

    dirs   = [Path(args.dpc3), Path(args.google), Path(args.qmm)]
    labels = args.labels

    for d in dirs:
        if not d.is_dir():
            sys.exit(f"ERROR: not a directory: {d}")

    suites = []
    for lbl, d in zip(labels, dirs):
        print(f"Loading '{lbl}' from {d} ...")
        rows = load_suite(d)
        print(f"  {len(rows)} workloads")
        suites.append((lbl, rows))

    out_stem = Path(args.out)

    for cache in ["LLC", "cpu0_STLB"]:
        tag = CACHE_DISPLAY[cache]
        plot_aggregate_bar(       suites, cache, out_stem.parent / f"{out_stem.name}_bar_{tag}.png")
        plot_lorenz(              suites, cache, out_stem.parent / f"{out_stem.name}_lorenz_{tag}.png")
        plot_hit_cdf_pooled(      suites, cache, out_stem.parent / f"{out_stem.name}_cdf_pooled_{tag}.png")
        plot_hit_cdf_per_workload(suites, cache, out_stem.parent / f"{out_stem.name}_cdf_per_wl_{tag}.png")


if __name__ == "__main__":
    main()
