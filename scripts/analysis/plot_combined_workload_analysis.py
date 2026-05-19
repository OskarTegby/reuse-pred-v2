#!/usr/bin/env python3
"""plot_combined_workload_analysis.py — combined per-benchmark analysis across SPEC, Google, QMM.

Selects the top-N pressure benchmarks from each suite (by lru_pred speedup) and
shows them side-by-side in one set of figures with suite-coloured bars and group
separators.  Produces five files (output prefix P):

    P_llc.png          — LLC working-set / evictions / DoA fraction
    P_stlb.png         — STLB working-set / evictions / DoA fraction
    P_llc_effect.png   — LLC bypass effect (ev-red / MPKI-red / bypass-rate / coverage)
    P_stlb_effect.png  — STLB bypass effect
    P_ipc.png          — IPC speedup vs LRU (dpPred-only left  |  dpPred+cbPred right)

Usage
-----
    python3 scripts/analysis/plot_combined_workload_analysis.py \\
        [--dpc3-dir   results/cluster/dpc3_pol_20260511_1545] \\
        [--google-dir results/cluster/google_pol_20260511_1545] \\
        [--qmm-dir    results/cluster/qmm_pol_20260511_1545] \\
        [--top-n      6] \\
        [--out-prefix results/plots/combined_workload]
"""

import argparse, math, re, sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from champsim_utils import parse_ipc

# ── cache geometry ─────────────────────────────────────────────────────────────
LLC_LINES    = 2 * 1024 * 1024 // 64   # 32 768 lines in a 2 MB / 64 B LLC
CACHE_LINE_B = 64
STLB_ENTRIES = 1024
PAGE_SIZE_B  = 4096
LLC_SIZE_MB  = 2.0
STLB_SIZE_MB = STLB_ENTRIES * PAGE_SIZE_B / 1e6   # ~4.2 MB virtual coverage

# ── suite colours & display labels ────────────────────────────────────────────
SUITE_COLORS = {
    "dpc3":   "#4C72B0",   # blue
    "google": "#E07B39",   # orange
    "qmm":    "#2E8B6A",   # green
}
SUITE_LABELS = {
    "dpc3":   "SPEC",
    "google": "Google",
    "qmm":    "QMM",
}
SUITE_ORDER = ["dpc3", "google", "qmm"]

# ── shared palette ─────────────────────────────────────────────────────────────
MD_CLR   = "#9DB8D9"   # mostly-dead stacked segment
DOT_CLR  = "#111111"
REF_CLR  = "#CC3333"
RED_GRN  = "#5BA85A"   # eviction / MPKI reduction bars
RATE_CLR = "#E07B39"   # bypass-rate bars
COV_CLR  = "#4C72B0"   # coverage bars
ZERO_THD = 0.02
CLIP_SPD = 5.5


# ── benchmark naming ──────────────────────────────────────────────────────────

def _bm_name(trace: str, suite: str) -> str:
    if suite == "dpc3":
        m = re.match(r"^(\d+\.\w+?)(?:-\d+[A-Z])?$", trace)
        return m.group(1) if m else trace
    if suite == "google":
        m = re.match(r"^(.+)_\d{4}$", trace)
        return m.group(1) if m else trace
    return trace   # qmm: one trace = one benchmark


def _short(bm: str, suite: str) -> str:
    if suite == "dpc3":
        m = re.match(r"^\d+\.(\w+?)(?:_s)?$", bm)
        return m.group(1) if m else bm
    return bm[:14]   # cap Google / QMM names to 14 chars


# ── SimPoint weights (DPC3 only) ──────────────────────────────────────────────

def _load_weights(suite: str) -> dict:
    if suite != "dpc3":
        return {}
    try:
        from spec_weights import SPEC_WEIGHTS
        return SPEC_WEIGHTS
    except ImportError:
        return {}


# ── parsing ───────────────────────────────────────────────────────────────────

def _parse(path: Path) -> dict:
    d = dict(ipc=None, instrs=None,
             stlb_miss=0, stlb_ev=0, stlb_doa=0, stlb_md=0,
             llc_miss=0,  llc_ev=0,  llc_doa=0,  llc_md=0,
             stlb_bypasses=0, llc_bypasses=0)
    try:
        in_roi = False
        for line in path.read_text(errors="replace").splitlines():
            if "Region of Interest Statistics" in line:
                in_roi = True
            if not in_roi:
                continue
            if d["ipc"] is None and "cumulative IPC:" in line:
                m = re.search(r"cumulative IPC:\s+([0-9.]+)\s+instructions:\s+(\d+)", line)
                if m:
                    d["ipc"] = float(m.group(1)); d["instrs"] = int(m.group(2))
            if not d["stlb_miss"] and re.match(r"cpu0_STLB TOTAL\s+ACCESS:", line):
                m = re.search(r"MISS:\s+(\d+)", line)
                if m: d["stlb_miss"] = int(m.group(1))
            m = re.match(r"cpu0_STLB LIVENESS EVICTIONS:\s+(\d+)"
                         r".*?DOA:\s+(\d+).*?MOSTLY_DEAD:\s+(\d+)", line)
            if m: d["stlb_ev"], d["stlb_doa"], d["stlb_md"] = int(m.group(1)), int(m.group(2)), int(m.group(3))
            m = re.fullmatch(r"cpu0_STLB BYPASSES:\s+(\d+)", line.strip())
            if m: d["stlb_bypasses"] = int(m.group(1))
            if not d["llc_miss"] and re.match(r"LLC TOTAL\s+ACCESS:", line):
                m = re.search(r"MISS:\s+(\d+)", line)
                if m: d["llc_miss"] = int(m.group(1))
            m = re.match(r"LLC LIVENESS EVICTIONS:\s+(\d+)"
                         r".*?DOA:\s+(\d+).*?MOSTLY_DEAD:\s+(\d+)", line)
            if m: d["llc_ev"], d["llc_doa"], d["llc_md"] = int(m.group(1)), int(m.group(2)), int(m.group(3))
            m = re.fullmatch(r"LLC BYPASSES:\s+(\d+)", line.strip())
            if m: d["llc_bypasses"] = int(m.group(1))
    except OSError:
        pass
    return d


# ── aggregation helpers ───────────────────────────────────────────────────────

def _mean(traces, key):
    vals = [r[key] for r in traces
            if not (isinstance(r[key], float) and math.isnan(r[key]))]
    return float(np.mean(vals)) if vals else 0.0


def _gm(traces, key):
    vals = [r[key] for r in traces
            if not (isinstance(r[key], float) and math.isnan(r[key])) and r[key] > 0]
    return math.exp(sum(math.log(v) for v in vals) / len(vals)) if vals else 1.0


def _wgeomean(traces, key, weights: dict) -> float:
    pairs = [(1 + r[key] / 100, weights.get(r["trace"]))
             for r in traces if not math.isnan(r[key])]
    w_valid = [(v, w) for v, w in pairs if w is not None and v > 0]
    if w_valid and any(w for _, w in w_valid):
        tw = sum(w for _, w in w_valid)
        return (math.exp(sum((w / tw) * math.log(v) for v, w in w_valid)) - 1) * 100
    vals = [v for v, _ in pairs if v > 0]
    return ((math.exp(sum(math.log(v) for v in vals) / len(vals)) - 1) * 100
            if vals else 0.0)


# ── data loading + aggregation for one suite ──────────────────────────────────

def load_suite(pol_dir: Path, suite: str, n_top: int, cache: str) -> list:
    """Load, aggregate, filter by cache pressure, return top-n_top by lru_pred speedup."""
    lru_dir     = pol_dir / "lru"
    pred_dir    = pol_dir / "lru_pred"
    dp_only_dir = pol_dir / "lru_dp_only"
    if not lru_dir.is_dir() or not pred_dir.is_dir():
        print(f"WARNING: missing lru or lru_pred under {pol_dir}; skipping {suite}",
              file=sys.stderr)
        return []

    weights = _load_weights(suite)
    rows = []
    for trace_dir in sorted(lru_dir.iterdir()):
        t = trace_dir.name
        lru_out     = trace_dir / "champsim.out"
        pred_out    = pred_dir    / t / "champsim.out"
        dp_only_out = dp_only_dir / t / "champsim.out"
        if not lru_out.exists() or not pred_out.exists():
            continue
        lru_s  = _parse(lru_out)
        pred_s = _parse(pred_out)
        if not lru_s["ipc"] or not pred_s["ipc"] or lru_s["ipc"] == 0:
            continue
        dp_only_ipc = parse_ipc(dp_only_out) if dp_only_out.exists() else None

        lru_llc_ev  = lru_s["llc_ev"]
        lru_stlb_ev = lru_s["stlb_ev"]
        pred_llc_ev  = pred_s["llc_ev"]
        pred_stlb_ev = pred_s["stlb_ev"]
        lru_ki  = (lru_s["instrs"] or 0) / 1000 or float("nan")
        pred_ki = (pred_s["instrs"] or 0) / 1000 or float("nan")

        rows.append({
            "trace": t,
            "bm":    _bm_name(t, suite),
            "suite": suite,
            "weight": weights.get(t),
            "llc_ws_mb":  (lru_llc_ev  + LLC_LINES)    * CACHE_LINE_B / 1e6,
            "stlb_ws_mb": (lru_stlb_ev + STLB_ENTRIES) * PAGE_SIZE_B  / 1e6,
            "lru_llc_ev_abs":   max(lru_llc_ev,  1),
            "lru_stlb_ev_abs":  max(lru_stlb_ev, 1),
            "pred_llc_ev_abs":  max(pred_llc_ev,  1),
            "pred_stlb_ev_abs": max(pred_stlb_ev, 1),
            "llc_doa_pct":  100.0 * lru_s["llc_doa"] / lru_llc_ev  if lru_llc_ev  else 0.0,
            "llc_md_pct":   100.0 * lru_s["llc_md"]  / lru_llc_ev  if lru_llc_ev  else 0.0,
            "stlb_doa_pct": 100.0 * lru_s["stlb_doa"]/ lru_stlb_ev if lru_stlb_ev else 0.0,
            "stlb_md_pct":  100.0 * lru_s["stlb_md"] / lru_stlb_ev if lru_stlb_ev else 0.0,
            "llc_ev_red_pct":  max(0.0, (lru_llc_ev  - pred_llc_ev)  / lru_llc_ev  * 100) if lru_llc_ev  else 0.0,
            "stlb_ev_red_pct": max(0.0, (lru_stlb_ev - pred_stlb_ev) / lru_stlb_ev * 100) if lru_stlb_ev else 0.0,
            "lru_llc_mpki":   lru_s["llc_ev"]   / lru_ki  if not math.isnan(lru_ki)  else float("nan"),
            "lru_stlb_mpki":  lru_s["stlb_ev"]  / lru_ki  if not math.isnan(lru_ki)  else float("nan"),
            "pred_llc_mpki":  pred_s["llc_ev"]  / pred_ki if not math.isnan(pred_ki) else float("nan"),
            "pred_stlb_mpki": pred_s["stlb_ev"] / pred_ki if not math.isnan(pred_ki) else float("nan"),
            "llc_mpki_red_pct":  ((lru_s["llc_miss"]  - pred_s["llc_miss"])  / lru_s["llc_miss"]  * 100
                                  if lru_s["llc_miss"]  else 0.0),
            "stlb_mpki_red_pct": ((lru_s["stlb_miss"] - pred_s["stlb_miss"]) / lru_s["stlb_miss"] * 100
                                  if lru_s["stlb_miss"] else 0.0),
            "llc_bypass_rate_pct":  (pred_s["llc_bypasses"]  / lru_s["llc_doa"]  * 100 if lru_s["llc_doa"]  else 0.0),
            "stlb_bypass_rate_pct": (pred_s["stlb_bypasses"] / lru_s["stlb_doa"] * 100 if lru_s["stlb_doa"] else 0.0),
            "llc_coverage_pct":  (max(0.0, (lru_s["llc_doa"]  - pred_s["llc_doa"])  / lru_s["llc_doa"]  * 100)
                                  if lru_s["llc_doa"]  else 0.0),
            "stlb_coverage_pct": (max(0.0, (lru_s["stlb_doa"] - pred_s["stlb_doa"]) / lru_s["stlb_doa"] * 100)
                                  if lru_s["stlb_doa"] else 0.0),
            "speedup_dp_only": ((dp_only_ipc / lru_s["ipc"] - 1) * 100 if dp_only_ipc else float("nan")),
            "speedup_pred":    (pred_s["ipc"] / lru_s["ipc"] - 1) * 100,
        })

    # aggregate traces → benchmarks
    by_bm: dict = defaultdict(list)
    for r in rows:
        by_bm[r["bm"]].append(r)

    agg = []
    for bm, traces in by_bm.items():
        dp_tr = [r for r in traces if not math.isnan(r["speedup_dp_only"])]
        agg.append({
            "bm":    bm,
            "suite": suite,
            "n":     len(traces),
            "traces": traces,
            "speedup_pred":    _wgeomean(traces, "speedup_pred",    weights),
            "speedup_dp_only": _wgeomean(dp_tr,  "speedup_dp_only", weights) if dp_tr else float("nan"),
            "llc_ws_mb":      _mean(traces, "llc_ws_mb"),
            "stlb_ws_mb":     _mean(traces, "stlb_ws_mb"),
            "lru_llc_ev_abs":   _gm(traces, "lru_llc_ev_abs"),
            "lru_stlb_ev_abs":  _gm(traces, "lru_stlb_ev_abs"),
            "lru_llc_mpki":     _gm(traces, "lru_llc_mpki"),
            "lru_stlb_mpki":    _gm(traces, "lru_stlb_mpki"),
            "llc_doa_pct":    _mean(traces, "llc_doa_pct"),
            "llc_md_pct":     _mean(traces, "llc_md_pct"),
            "stlb_doa_pct":   _mean(traces, "stlb_doa_pct"),
            "stlb_md_pct":    _mean(traces, "stlb_md_pct"),
            "llc_ev_red_pct":    _mean(traces, "llc_ev_red_pct"),
            "stlb_ev_red_pct":   _mean(traces, "stlb_ev_red_pct"),
            "llc_mpki_red_pct":  _mean(traces, "llc_mpki_red_pct"),
            "stlb_mpki_red_pct": _mean(traces, "stlb_mpki_red_pct"),
            "llc_bypass_rate_pct":  _mean(traces, "llc_bypass_rate_pct"),
            "stlb_bypass_rate_pct": _mean(traces, "stlb_bypass_rate_pct"),
            "llc_coverage_pct":  _mean(traces, "llc_coverage_pct"),
            "stlb_coverage_pct": _mean(traces, "stlb_coverage_pct"),
        })

    # apply pressure filter then take top n_top by speedup
    if cache == "llc":
        agg = [d for d in agg if d["lru_llc_ev_abs"] > LLC_LINES * 5]
    else:
        agg = [d for d in agg if d["lru_stlb_ev_abs"] > STLB_ENTRIES * 5]

    return sorted(agg, key=lambda d: -d["speedup_pred"])[:n_top]


# ── plot helpers ──────────────────────────────────────────────────────────────

def _style(ax, ylabel: str, ylim_bottom: "float | None" = 0.0, fontsize: int = 9):
    if ylim_bottom is not None:
        ax.set_ylim(bottom=ylim_bottom)
    ax.set_ylabel(ylabel, fontsize=fontsize, labelpad=3)
    ax.yaxis.set_tick_params(labelsize=max(6, fontsize - 1))
    ax.tick_params(labelbottom=False)
    ax.grid(axis="y", linewidth=0.35, alpha=0.5, zorder=0)
    ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)


def _log_fmt(ax):
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
        lambda v, _: f"{v:,.0f}" if v >= 10 else f"{v:.1f}"))


def _fmt_count(v: float) -> str:
    if v >= 1e6: return f"{v/1e6:.1f}M"
    if v >= 1e3: return f"{v/1e3:.0f}K"
    return f"{v:.0f}"


def _add_separators(axes, groups, top_ax_idx: int = 0):
    """Draw dotted vertical separators and bold suite labels between groups."""
    cumulative = 0
    for i, (suite, items) in enumerate(groups):
        n = len(items)
        if n == 0:
            continue
        if i > 0 and cumulative > 0:
            for ax in axes:
                ax.axvline(cumulative - 0.5, color="#777", linewidth=0.9,
                           linestyle=":", zorder=5)
        mid = cumulative + n / 2 - 0.5
        ylo, yhi = axes[top_ax_idx].get_ylim()
        ypos = ylo + (yhi - ylo) * 0.91
        axes[top_ax_idx].text(
            mid, ypos, SUITE_LABELS[suite],
            ha="center", fontsize=8, color=SUITE_COLORS[suite],
            fontweight="bold", zorder=6,
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.7, pad=1))
        cumulative += n


# ── cache characterisation plot ───────────────────────────────────────────────

def plot_cache(groups: list, cache: str, out: Path):
    """3-row characterisation: working-set / evictions / DoA+MD; suite-coloured bars."""
    assert cache in ("llc", "stlb")
    p = cache
    if cache == "llc":
        ws_ref  = LLC_SIZE_MB
        cap     = LLC_LINES
        ws_lab  = "2 MB LLC"
        cap_lab = f"{LLC_LINES:,} lines (= 2 MB)"
        title   = "LLC"
    else:
        ws_ref  = STLB_SIZE_MB
        cap     = STLB_ENTRIES
        ws_lab  = f"STLB cap. ({STLB_SIZE_MB:.1f} MB)"
        cap_lab = f"{STLB_ENTRIES} entries (STLB cap.)"
        title   = "STLB"

    # flatten groups into one ordered list
    all_d = [(s, d) for s, items in groups for d in items]
    if not all_d:
        print(f"WARNING: no {title} pressure benchmarks across suites; skipping {out}")
        return

    n = len(all_d)
    x = np.arange(n)
    colors = [SUITE_COLORS[s] for s, _ in all_d]
    labels = [_short(d["bm"], s) for s, d in all_d]
    FS     = 11

    fig = plt.figure(figsize=(max(8, n * 0.68 + 2), 11))
    gs  = gridspec.GridSpec(3, 1, figure=fig, hspace=0.10,
                            left=0.10, right=0.97, top=0.93, bottom=0.22,
                            height_ratios=[1.1, 1.1, 1])
    ax_ws  = fig.add_subplot(gs[0])
    ax_ev  = fig.add_subplot(gs[1], sharex=ax_ws)
    ax_doa = fig.add_subplot(gs[2], sharex=ax_ws)

    # row 0: working-set size (MB, log)
    vals_ws = np.array([d[f"{p}_ws_mb"] for _, d in all_d])
    ax_ws.bar(x, vals_ws, color=colors, width=0.65, linewidth=0.4, edgecolor="white", zorder=2)
    ax_ws.axhline(ws_ref, color=REF_CLR, linewidth=1.1, linestyle="--", zorder=5, label=ws_lab)
    for xi, v in zip(x, vals_ws):
        ax_ws.text(xi, v * 1.15, f"{v:.1f}", ha="center", va="bottom", fontsize=FS-4, clip_on=True)
    ax_ws.legend(fontsize=FS-1, loc="upper right", framealpha=0.85)
    ax_ws.set_yscale("log")
    ax_ws.set_ylim(1, max(max(vals_ws) * 1.5, 300))
    ax_ws.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(
        lambda v, _: f"{v:.0f}" if v >= 1 else f"{v:.1f}"))
    _style(ax_ws, f"{title} working-set\nsize (MB)", ylim_bottom=None, fontsize=FS)

    # row 1: LLC/STLB eviction MPKI = evictions per 1 K instructions (log)
    # Normalised by instruction count; avoids simulation-length bias across suites.
    mpki_key = f"lru_{p}_mpki"
    vals_mpki = np.array([max(d[mpki_key], 1e-3) for _, d in all_d])
    ax_ev.set_yscale("log")
    ax_ev.bar(x, vals_mpki, color=colors, width=0.65, linewidth=0.4, edgecolor="white", zorder=2)
    bot_mpki = max(min(vals_mpki) * 0.5, 0.1)
    top_mpki = max(vals_mpki) * 2.5
    ax_ev.set_ylim(bottom=bot_mpki, top=top_mpki)
    for xi, v in zip(x, vals_mpki):
        ax_ev.text(xi, v * 1.5, f"{v:.1f}", ha="center", va="bottom", fontsize=FS-4, clip_on=True)
    _log_fmt(ax_ev)
    _style(ax_ev, f"{title} eviction rate\n(evictions / K instr., log)", ylim_bottom=None, fontsize=FS)

    # row 2: DoA% + Mostly-dead% stacked
    doa = np.array([d[f"{p}_doa_pct"] for _, d in all_d])
    md  = np.array([d[f"{p}_md_pct"]  for _, d in all_d])
    ax_doa.bar(x, doa, color=[SUITE_COLORS[s] for s, _ in all_d], width=0.65,
               linewidth=0.4, edgecolor="white", zorder=2)
    ax_doa.bar(x, md, bottom=doa, color=MD_CLR, width=0.65,
               linewidth=0.4, edgecolor="white", zorder=2)
    for xi, (dv, mv) in enumerate(zip(doa, md)):
        if dv > 5:
            ax_doa.text(xi, dv / 2, f"{dv:.0f}%", ha="center", va="center",
                        fontsize=FS-4, color="white", fontweight="bold")
        if mv > 5:
            ax_doa.text(xi, dv + mv / 2, f"{mv:.0f}%", ha="center", va="center",
                        fontsize=FS-4, color="#2a2a2a", fontweight="bold")
    _style(ax_doa, f"{title} dead evictions\n(%; DoA + Mostly-dead)", fontsize=FS)
    ax_doa.set_ylim(0, 105)

    suite_patches = [mpatches.Patch(color=SUITE_COLORS[s], label=SUITE_LABELS[s])
                     for s in SUITE_ORDER]
    doa_md_patches = [mpatches.Patch(color=MD_CLR, label="Mostly-dead")]
    ax_doa.legend(handles=suite_patches + doa_md_patches, fontsize=FS-2,
                  loc="upper right", framealpha=0.85, ncol=2)

    ax_doa.set_xticks(x)
    ax_doa.set_xticklabels(labels, rotation=55, ha="right", fontsize=FS, fontstyle="italic")
    ax_doa.set_xlim(-0.7, n - 0.3)
    ax_doa.tick_params(labelbottom=True)

    _add_separators([ax_ws, ax_ev, ax_doa], groups, top_ax_idx=0)

    fig.suptitle(
        f"SPEC / Google / QMM — {title} per-benchmark characterisation  (lru_pred · 2 MB LLC)\n"
        "Top-N pressure benchmarks per suite, sorted by lru_pred IPC speedup (descending)",
        fontsize=11, fontweight="bold")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out}")


# ── bypass-effect plot ─────────────────────────────────────────────────────────

def plot_effect(groups: list, cache: str, out: Path):
    """4-row bypass effect: ev-red / MPKI-red / bypass-rate / coverage; suite-coloured."""
    assert cache in ("llc", "stlb")
    p = cache
    title = "LLC" if cache == "llc" else "STLB"

    all_d = [(s, d) for s, items in groups for d in items]
    if not all_d:
        print(f"WARNING: no {title} pressure benchmarks across suites; skipping {out}")
        return

    n = len(all_d)
    x = np.arange(n)
    colors = [SUITE_COLORS[s] for s, _ in all_d]
    labels = [_short(d["bm"], s) for s, d in all_d]
    FS     = 11

    fig = plt.figure(figsize=(max(8, n * 0.68 + 2), 12))
    gs  = gridspec.GridSpec(4, 1, figure=fig, hspace=0.10,
                            left=0.10, right=0.97, top=0.93, bottom=0.22,
                            height_ratios=[1, 1, 1, 1])
    ax_ev_red = fig.add_subplot(gs[0])
    ax_mpki_r = fig.add_subplot(gs[1], sharex=ax_ev_red)
    ax_rate   = fig.add_subplot(gs[2], sharex=ax_ev_red)
    ax_cov    = fig.add_subplot(gs[3], sharex=ax_ev_red)

    def _bar_pct(ax, key, clr, label_offset=0.5):
        vals = np.array([d[key] for _, d in all_d])
        ax.bar(x, vals, color=clr if isinstance(clr, str) else colors,
               width=0.65, linewidth=0.4, edgecolor="white", zorder=2)
        ax.axhline(0, color="black", linewidth=0.5, zorder=3)
        for xi, v in zip(x, vals):
            va = "bottom" if v >= 0 else "top"
            yo = v + label_offset if v >= 0 else v - label_offset
            ax.text(xi, yo, f"{v:.1f}%", ha="center", va=va, fontsize=FS-4)
        return vals

    # row 0: eviction reduction %
    vals = _bar_pct(ax_ev_red, f"{p}_ev_red_pct", colors)
    _style(ax_ev_red, f"{title} eviction\nreduction (%)", fontsize=FS)
    top_ev  = max(max(vals), 1);  bot_ev  = min(min(vals), 0)
    ax_ev_red.set_ylim(bot_ev - 6, min(top_ev * 1.25 + 4, 108))

    # row 1: MPKI reduction %
    vals = _bar_pct(ax_mpki_r, f"{p}_mpki_red_pct", colors)
    _style(ax_mpki_r, f"{title} MPKI\nreduction (%)", fontsize=FS)
    top_mpki = max(max(vals), 1); bot_mpki = min(min(vals), 0)
    ax_mpki_r.set_ylim(bot_mpki - 6, min(top_mpki * 1.25 + 4, 108))

    # row 2: bypass rate (bypasses / lru_doa × 100%)
    vals = np.array([d[f"{p}_bypass_rate_pct"] for _, d in all_d])
    ax_rate.bar(x, vals, color=RATE_CLR, width=0.65, linewidth=0.4, edgecolor="white", zorder=2)
    ax_rate.axhline(100, color=REF_CLR, linewidth=1.1, linestyle="--",
                    zorder=5, label="100% = 1 bypass per DoA entry")
    for xi, v in zip(x, vals):
        ax_rate.text(xi, v + 0.5, f"{v:.1f}%", ha="center", va="bottom", fontsize=FS-4)
    ax_rate.legend(fontsize=FS-3, loc="upper right", framealpha=0.85)
    _style(ax_rate, f"{title} bypass rate\n(bypasses / DoA, %)", fontsize=FS)
    ax_rate.set_ylim(0, max(max(vals), 110) * 1.15)

    # row 3: bypass coverage ((DoA_lru − DoA_pred) / DoA_lru × 100%)
    vals = np.array([d[f"{p}_coverage_pct"] for _, d in all_d])
    ax_cov.bar(x, vals, color=COV_CLR, width=0.65, linewidth=0.4, edgecolor="white", zorder=2)
    ax_cov.axhline(100, color=REF_CLR, linewidth=1.1, linestyle="--",
                   zorder=5, label="100% = all DoA addressed")
    for xi, v in zip(x, vals):
        ax_cov.text(xi, v + 0.5, f"{v:.1f}%", ha="center", va="bottom", fontsize=FS-4)
    ax_cov.legend(fontsize=FS-3, loc="upper right", framealpha=0.85)
    _style(ax_cov, f"{title} bypass coverage\n(DoA elim. / lru DoA, %)", fontsize=FS)
    ax_cov.set_ylim(0, 105)

    ax_cov.set_xticks(x)
    ax_cov.set_xticklabels(labels, rotation=55, ha="right", fontsize=FS, fontstyle="italic")
    ax_cov.set_xlim(-0.7, n - 0.3)
    ax_cov.tick_params(labelbottom=True)

    _add_separators([ax_ev_red, ax_mpki_r, ax_rate, ax_cov], groups, top_ax_idx=0)

    suite_patches = [mpatches.Patch(color=SUITE_COLORS[s], label=SUITE_LABELS[s])
                     for s in SUITE_ORDER]
    ax_ev_red.legend(handles=suite_patches, fontsize=FS-2, loc="upper right",
                     framealpha=0.85, ncol=3)

    fig.suptitle(
        f"SPEC / Google / QMM — {title} bypass effect  (lru_pred · 2 MB LLC)\n"
        "Rows 3–4: bypass rate = bypasses/DoA×100; coverage = DoA eliminated/DoA_LRU×100",
        fontsize=11, fontweight="bold")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out}")


# ── IPC speedup plot ──────────────────────────────────────────────────────────

def plot_ipc(groups: list, out: Path):
    """Grouped bars: dpPred-only (left) + dpPred+cbPred (right); coloured by suite."""
    all_d = [(s, d) for s, items in groups for d in items]
    if not all_d:
        print(f"WARNING: no LLC pressure benchmarks for IPC plot; skipping {out}")
        return

    n  = len(all_d)
    x  = np.arange(n)
    bw = 0.35
    labels = [_short(d["bm"], s) for s, d in all_d]
    FS = 11

    fig, ax = plt.subplots(figsize=(max(8, n * 0.68 + 2), 6))
    fig.subplots_adjust(left=0.10, right=0.97, top=0.88, bottom=0.22)

    dp_vals   = np.array([d["speedup_dp_only"] for _, d in all_d])
    both_vals = np.array([d["speedup_pred"]    for _, d in all_d])

    # bars: left = dpPred-only, right = dpPred+cbPred
    # colour = suite, with lighter alpha for dpPred-only
    suite_cols = [SUITE_COLORS[s] for s, _ in all_d]
    ax.bar(x - bw / 2, np.nan_to_num(dp_vals), bw,
           color=suite_cols, alpha=0.45, linewidth=0.4, edgecolor="white", zorder=2)
    ax.bar(x + bw / 2, both_vals, bw,
           color=suite_cols, alpha=0.90, linewidth=0.4, edgecolor="white", zorder=2)
    ax.axhline(0, color="black", linewidth=0.7, zorder=3)

    for i, (dp_v, both_v) in enumerate(zip(dp_vals, both_vals)):
        for val, off in [(dp_v, -bw / 2), (both_v, +bw / 2)]:
            if math.isnan(val):
                continue
            if val > CLIP_SPD:
                ax.annotate(f"+{val:.0f}%",
                            xy=(x[i] + off, CLIP_SPD),
                            xytext=(x[i] + off, CLIP_SPD - 0.6),
                            ha="center", va="top", fontsize=FS - 4,
                            arrowprops=dict(arrowstyle="-", lw=0.6))
            elif abs(val) >= 0.20:
                va = "bottom" if val >= 0 else "top"
                yo = val + 0.08 if val >= 0 else val - 0.08
                ax.text(x[i] + off, yo, f"{val:+.2f}%", ha="center", va=va,
                        fontsize=FS-5, clip_on=True)

    _style(ax, "IPC speedup\nvs LRU (%)", ylim_bottom=None, fontsize=FS)
    dp_valid = [v for v in dp_vals if not math.isnan(v)]
    min_bar  = min(min(dp_valid) if dp_valid else 0, float(np.min(both_vals)), 0)
    ax.set_ylim(min(min_bar - 0.5, -2.5), CLIP_SPD)
    ax.tick_params(labelbottom=True)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=55, ha="right", fontsize=FS, fontstyle="italic")
    ax.set_xlim(-0.7, n - 0.3)

    # group legend by suite: dpPred-only | dpPred+cbPred per row
    suite_patches = []
    for s in SUITE_ORDER:
        suite_patches.append(mpatches.Patch(color=SUITE_COLORS[s], alpha=0.45,
                                            label=f"{SUITE_LABELS[s]} dpPred-only"))
        suite_patches.append(mpatches.Patch(color=SUITE_COLORS[s], alpha=0.90,
                                            label=f"{SUITE_LABELS[s]} dpPred+cbPred"))
    ax.legend(handles=suite_patches, fontsize=FS - 3, loc="upper right",
              framealpha=0.88, ncol=2)

    _add_separators([ax], groups, top_ax_idx=0)

    fig.suptitle(
        "SPEC / Google / QMM — IPC speedup vs LRU baseline  (LLC-pressure benchmarks · 2 MB LLC)\n"
        "Light bars: dpPred only (STLB bypass)  ·  Dark bars: dpPred + cbPred (STLB + LLC bypass)",
        fontsize=FS, fontweight="bold")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _find_pol_dir(root: Path, suite: str) -> Path:
    """Auto-detect the most recent pol dir for a suite under root."""
    candidates = sorted(root.glob(f"{suite}_pol_*"), reverse=True)
    if candidates:
        return candidates[0]
    return root / f"{suite}_pol_20260511_1545"


def main():
    ROOT = Path(__file__).parents[2]
    CLUSTER = ROOT / "results" / "cluster"
    OUT_DEFAULT = ROOT / "results" / "plots" / "combined_workload"

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dpc3-dir",   type=Path, default=_find_pol_dir(CLUSTER, "dpc3"),
                    help="DPC3 pol directory (default: auto-detect most recent)")
    ap.add_argument("--google-dir", type=Path, default=_find_pol_dir(CLUSTER, "google"),
                    help="Google pol directory")
    ap.add_argument("--qmm-dir",    type=Path, default=_find_pol_dir(CLUSTER, "qmm"),
                    help="QMM pol directory")
    ap.add_argument("--top-n",      type=int, default=6,
                    help="Max benchmarks per suite (default: 6)")
    ap.add_argument("--out-prefix", type=Path, default=OUT_DEFAULT,
                    help="Output path prefix (default: results/plots/combined_workload)")
    args = ap.parse_args()

    suite_dirs = {
        "dpc3":   args.dpc3_dir,
        "google": args.google_dir,
        "qmm":    args.qmm_dir,
    }
    print(f"DPC3   pol dir : {args.dpc3_dir}")
    print(f"Google pol dir : {args.google_dir}")
    print(f"QMM    pol dir : {args.qmm_dir}")
    print(f"Top-N per suite: {args.top_n}")
    print()

    for cache in ("llc", "stlb"):
        groups = []
        for suite in SUITE_ORDER:
            d = suite_dirs[suite]
            if not d.is_dir():
                print(f"WARNING: {suite} pol dir not found: {d}", file=sys.stderr)
                items = []
            else:
                items = load_suite(d, suite, args.top_n, cache)
            groups.append((suite, items))
            n = len(items)
            print(f"  {suite:6s} {cache} pressure: {n} benchmarks selected")

        print()
        plot_cache(groups, cache, Path(f"{args.out_prefix}_{cache}.png"))
        plot_effect(groups, cache, Path(f"{args.out_prefix}_{cache}_effect.png"))

    # IPC uses LLC-pressure filter regardless
    ipc_groups = []
    for suite in SUITE_ORDER:
        d = suite_dirs[suite]
        if not d.is_dir():
            ipc_groups.append((suite, []))
        else:
            ipc_groups.append((suite, load_suite(d, suite, args.top_n, "llc")))
    plot_ipc(ipc_groups, Path(f"{args.out_prefix}_ipc.png"))


if __name__ == "__main__":
    main()
