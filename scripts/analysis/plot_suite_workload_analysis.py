#!/usr/bin/env python3
"""plot_suite_workload_analysis.py — per-benchmark working-set / DoA / bypass narrative.

Tells the story from problem to solution for one benchmark suite.

Layout (2-column STLB | LLC for rows 0-2; full-width for rows 3-4):
  Row 0 | LLC working-set size (MB, log)   | STLB working-set size (MB, log)
  Row 1 | LLC eviction count (log)          | STLB eviction count (log)
  Row 2 | LLC DoA% + Mostly-dead%           | STLB DoA% + Mostly-dead%
  Row 3 | Bypass coverage vs DoA reduction  (full width)
  Row 4 | IPC speedup lru_pred + srrip_live (full width)

Benchmark grouping
------------------
  dpc3   : group SimPoint traces by benchmark name; weighted geomean speedup
  google : group traces by family (strip trailing _NNNN)
  qmm    : each trace is its own benchmark (no grouping)

Usage
-----
    python3 scripts/analysis/plot_suite_workload_analysis.py \\
        --suite  dpc3 \\
        --pol-dir results/cluster/dpc3_pol_20260511_1545 \\
        --out    results/plots/dpc3_workload_narrative.png
"""

import argparse
import math
import re
import sys
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
LLC_LINES    = 2 * 1024 * 1024 // 64   # lines in a 2 MB / 64 B LLC
CACHE_LINE_B = 64
STLB_ENTRIES = 1024
PAGE_SIZE_B  = 4096
LLC_SIZE_MB  = 2.0
STLB_SIZE_MB = STLB_ENTRIES * PAGE_SIZE_B / 1e6

# ── colours ───────────────────────────────────────────────────────────────────
PRED_POS  = "#4C72B0"
PRED_NEG  = "#C44E52"
PRED_ZERO = "#8DA0C2"
SRRIP_CLR = "#2E8B6A"
DOA_CLR   = "#4C72B0"
MD_CLR    = "#9DB8D9"
COV_CLR   = "#E07B39"   # bypass coverage bar
RED_CLR   = "#5BA85A"   # DoA reduction bar
DOT_CLR   = "#111111"
REF_CLR   = "#CC3333"
ZERO_THD  = 0.02
CLIP_SPD  = 5.5
BOTH_POS  = "#E07B39"
BOTH_NEG  = "#B05040"
BOTH_ZERO = "#E5A87A"


# ── benchmark naming / grouping ───────────────────────────────────────────────

def _bm_name(trace: str, suite: str) -> str:
    if suite == "dpc3":
        # 602.gcc_s-1850B → 602.gcc_s
        m = re.match(r"^(\d+\.\w+?)(?:-\d+[A-Z])?$", trace)
        return m.group(1) if m else trace
    if suite == "google":
        # arizona_0003 → arizona
        m = re.match(r"^(.+)_\d{4}$", trace)
        return m.group(1) if m else trace
    # qmm: treat each trace as its own benchmark
    return trace


def _short(bm: str, suite: str) -> str:
    if suite == "dpc3":
        m = re.match(r"^\d+\.(\w+?)(?:_s)?$", bm)
        return m.group(1) if m else bm
    return bm


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
                m = re.search(
                    r"cumulative IPC:\s+([0-9.]+)\s+instructions:\s+(\d+)", line)
                if m:
                    d["ipc"]    = float(m.group(1))
                    d["instrs"] = int(m.group(2))
            if not d["stlb_miss"] and re.match(r"cpu0_STLB TOTAL\s+ACCESS:", line):
                m = re.search(r"MISS:\s+(\d+)", line)
                if m:
                    d["stlb_miss"] = int(m.group(1))
            m = re.match(r"cpu0_STLB LIVENESS EVICTIONS:\s+(\d+)"
                         r".*?DOA:\s+(\d+).*?MOSTLY_DEAD:\s+(\d+)", line)
            if m:
                d["stlb_ev"]  = int(m.group(1))
                d["stlb_doa"] = int(m.group(2))
                d["stlb_md"]  = int(m.group(3))
            m = re.fullmatch(r"cpu0_STLB BYPASSES:\s+(\d+)", line.strip())
            if m:
                d["stlb_bypasses"] = int(m.group(1))
            if not d["llc_miss"] and re.match(r"LLC TOTAL\s+ACCESS:", line):
                m = re.search(r"MISS:\s+(\d+)", line)
                if m:
                    d["llc_miss"] = int(m.group(1))
            m = re.match(r"LLC LIVENESS EVICTIONS:\s+(\d+)"
                         r".*?DOA:\s+(\d+).*?MOSTLY_DEAD:\s+(\d+)", line)
            if m:
                d["llc_ev"]  = int(m.group(1))
                d["llc_doa"] = int(m.group(2))
                d["llc_md"]  = int(m.group(3))
            m = re.fullmatch(r"LLC BYPASSES:\s+(\d+)", line.strip())
            if m:
                d["llc_bypasses"] = int(m.group(1))
    except OSError:
        pass
    return d


# ── data loading ──────────────────────────────────────────────────────────────

def load_data(pol_dir: Path, suite: str) -> list:
    lru_dir     = pol_dir / "lru"
    pred_dir    = pol_dir / "lru_pred"
    dp_only_dir = pol_dir / "lru_dp_only"
    slv_dir     = pol_dir / "srrip_live"
    for d in (lru_dir, pred_dir):
        if not d.is_dir():
            sys.exit(f"ERROR: directory not found: {d}")

    weights = _load_weights(suite)
    rows = []
    for trace_dir in sorted(lru_dir.iterdir()):
        t = trace_dir.name
        lru_out     = trace_dir / "champsim.out"
        pred_out    = pred_dir    / t / "champsim.out"
        dp_only_out = dp_only_dir / t / "champsim.out"
        slv_out     = slv_dir     / t / "champsim.out"
        if not lru_out.exists() or not pred_out.exists():
            continue

        lru_s  = _parse(lru_out)
        pred_s = _parse(pred_out)
        if not lru_s["ipc"] or not pred_s["ipc"] or lru_s["ipc"] == 0:
            continue
        dp_only_ipc = parse_ipc(dp_only_out) if dp_only_out.exists() else None
        slv_ipc     = parse_ipc(slv_out)     if slv_out.exists()     else None

        lru_ki  = (lru_s["instrs"] or 0) / 1000 or float("nan")
        pred_ki = (pred_s["instrs"] or 0) / 1000 or float("nan")

        lru_stlb_ev  = lru_s["stlb_ev"]
        lru_llc_ev   = lru_s["llc_ev"]
        pred_stlb_ev = pred_s["stlb_ev"]
        pred_llc_ev  = pred_s["llc_ev"]

        rows.append({
            "trace":  t,
            "bm":     _bm_name(t, suite),
            "weight": weights.get(t),
            # working-set size: use LRU evictions (unaffected by bypass)
            "llc_ws_mb":  (lru_llc_ev  + LLC_LINES)    * CACHE_LINE_B / 1e6,
            "stlb_ws_mb": (lru_stlb_ev + STLB_ENTRIES) * PAGE_SIZE_B  / 1e6,
            # evictions before bypass (LRU run)
            "lru_llc_ev_abs":  max(lru_llc_ev,  1),
            "lru_stlb_ev_abs": max(lru_stlb_ev, 1),
            # evictions after bypass (pred run)
            "pred_llc_ev_abs":  max(pred_llc_ev,  1),
            "pred_stlb_ev_abs": max(pred_stlb_ev, 1),
            # dead-block fractions (LRU run = pre-bypass baseline)
            "llc_doa_pct":  100.0 * lru_s["llc_doa"] / lru_llc_ev   if lru_llc_ev  else 0.0,
            "llc_md_pct":   100.0 * lru_s["llc_md"]  / lru_llc_ev   if lru_llc_ev  else 0.0,
            "stlb_doa_pct": 100.0 * lru_s["stlb_doa"]/ lru_stlb_ev  if lru_stlb_ev else 0.0,
            "stlb_md_pct":  100.0 * lru_s["stlb_md"] / lru_stlb_ev  if lru_stlb_ev else 0.0,
            # eviction reduction after bypass (%)
            "llc_ev_red_pct":  max(0.0, (lru_llc_ev  - pred_llc_ev)  / lru_llc_ev  * 100) if lru_llc_ev  else 0.0,
            "stlb_ev_red_pct": max(0.0, (lru_stlb_ev - pred_stlb_ev) / lru_stlb_ev * 100) if lru_stlb_ev else 0.0,
            # MPKI before and after bypass
            "lru_llc_mpki":   lru_s["llc_miss"]  / lru_ki  if not math.isnan(lru_ki)  else float("nan"),
            "lru_stlb_mpki":  lru_s["stlb_miss"] / lru_ki  if not math.isnan(lru_ki)  else float("nan"),
            "pred_llc_mpki":  pred_s["llc_miss"]  / pred_ki if not math.isnan(pred_ki) else float("nan"),
            "pred_stlb_mpki": pred_s["stlb_miss"] / pred_ki if not math.isnan(pred_ki) else float("nan"),
            "llc_mpki_red_pct":  ((lru_s["llc_miss"]  - pred_s["llc_miss"])  / lru_s["llc_miss"]  * 100
                                  if lru_s["llc_miss"]  else 0.0),
            "stlb_mpki_red_pct": ((lru_s["stlb_miss"] - pred_s["stlb_miss"]) / lru_s["stlb_miss"] * 100
                                  if lru_s["stlb_miss"] else 0.0),
            # bypass counts
            "llc_bypasses_abs":  max(pred_s["llc_bypasses"],  1),
            "stlb_bypasses_abs": max(pred_s["stlb_bypasses"], 1),
            # absolute DoA counts (LRU baseline) for precision row
            "llc_doa_abs":  max(lru_s["llc_doa"],  1),
            "stlb_doa_abs": max(lru_s["stlb_doa"], 1),
            # raw counts kept for aggregate bypass-coverage computation
            "lru_llc_doa":  max(lru_s["llc_doa"], 1),
            "pred_llc_doa": pred_s["llc_doa"],
            "llc_bypasses": pred_s["llc_bypasses"],
            # bypass precision metrics (per trace, averaged in aggregate)
            "llc_bypass_rate_pct":  (pred_s["llc_bypasses"]  / lru_s["llc_doa"]  * 100
                                     if lru_s["llc_doa"]  else 0.0),
            "stlb_bypass_rate_pct": (pred_s["stlb_bypasses"] / lru_s["stlb_doa"] * 100
                                     if lru_s["stlb_doa"] else 0.0),
            "llc_accuracy_pct":     (max(0.0, (lru_s["llc_doa"]  - pred_s["llc_doa"])
                                         / pred_s["llc_bypasses"]  * 100)
                                     if pred_s["llc_bypasses"]  else 0.0),
            "stlb_accuracy_pct":    (max(0.0, (lru_s["stlb_doa"] - pred_s["stlb_doa"])
                                         / pred_s["stlb_bypasses"] * 100)
                                     if pred_s["stlb_bypasses"] else 0.0),
            "llc_coverage_pct":     (max(0.0, (lru_s["llc_doa"]  - pred_s["llc_doa"])  / lru_s["llc_doa"]  * 100)
                                     if lru_s["llc_doa"]  else 0.0),
            "stlb_coverage_pct":    (max(0.0, (lru_s["stlb_doa"] - pred_s["stlb_doa"]) / lru_s["stlb_doa"] * 100)
                                     if lru_s["stlb_doa"] else 0.0),
            # speedup
            "speedup_dp_only": ((dp_only_ipc / lru_s["ipc"] - 1) * 100
                                if dp_only_ipc else float("nan")),
            "speedup_pred": (pred_s["ipc"] / lru_s["ipc"] - 1) * 100,
            "speedup_slv":  ((slv_ipc / lru_s["ipc"] - 1) * 100
                             if slv_ipc else float("nan")),
        })
    return rows


# ── aggregation ───────────────────────────────────────────────────────────────

def _wgeomean(traces, key):
    """SimPoint-weighted geomean speedup if weights available, else plain geomean."""
    pairs = [(1 + r[key] / 100, r["weight"])
             for r in traces if not math.isnan(r[key])]
    w_valid = [(v, w) for v, w in pairs if w is not None and v > 0]
    if w_valid and any(w for _, w in w_valid):
        tw = sum(w for _, w in w_valid)
        return (math.exp(sum((w / tw) * math.log(v) for v, w in w_valid)) - 1) * 100
    vals = [v for v, _ in pairs if v > 0]
    return ((math.exp(sum(math.log(v) for v in vals) / len(vals)) - 1) * 100
            if vals else 0.0)


def _mean(traces, key):
    vals = [r[key] for r in traces
            if not (isinstance(r[key], float) and math.isnan(r[key]))]
    return float(np.mean(vals)) if vals else 0.0


def _gm(traces, key):
    vals = [r[key] for r in traces
            if not (isinstance(r[key], float) and math.isnan(r[key])) and r[key] > 0]
    return math.exp(sum(math.log(v) for v in vals) / len(vals)) if vals else 1.0


def aggregate(rows: list, suite: str) -> list:
    by_bm: dict = defaultdict(list)
    for r in rows:
        by_bm[r["bm"]].append(r)

    agg = []
    for bm, traces in by_bm.items():
        sp_pred = _wgeomean(traces, "speedup_pred")
        dp_tr   = [r for r in traces if not math.isnan(r["speedup_dp_only"])]
        sp_dp   = _wgeomean(dp_tr, "speedup_dp_only") if dp_tr else float("nan")
        slv_tr  = [r for r in traces if not math.isnan(r["speedup_slv"])]
        sp_slv  = _wgeomean(slv_tr, "speedup_slv") if slv_tr else float("nan")

        # absolute counts summed across traces for bypass analysis
        lru_doa_total  = sum(r["lru_llc_doa"]  for r in traces)
        pred_doa_total = sum(r["pred_llc_doa"]  for r in traces)
        bypasses_total = sum(r["llc_bypasses"]  for r in traces)

        # bypass coverage: how much of the DoA problem did we address?
        bypass_coverage = (bypasses_total / lru_doa_total
                           if lru_doa_total else 0.0)
        # DoA reduction: fraction of DoA evictions eliminated
        doa_reduction   = ((lru_doa_total - pred_doa_total) / lru_doa_total
                           if lru_doa_total else 0.0)

        agg.append({
            "bm":              bm,
            "n":               len(traces),
            "speedup_dp_only": sp_dp,
            "speedup_pred":    sp_pred,
            "speedup_slv":     sp_slv,
            "llc_ws_mb":      _mean(traces, "llc_ws_mb"),
            "stlb_ws_mb":     _mean(traces, "stlb_ws_mb"),
            "lru_llc_ev_abs":   _gm(traces, "lru_llc_ev_abs"),
            "lru_stlb_ev_abs":  _gm(traces, "lru_stlb_ev_abs"),
            "pred_llc_ev_abs":  _gm(traces, "pred_llc_ev_abs"),
            "pred_stlb_ev_abs": _gm(traces, "pred_stlb_ev_abs"),
            "llc_ev_red_pct":    _mean(traces, "llc_ev_red_pct"),
            "stlb_ev_red_pct":   _mean(traces, "stlb_ev_red_pct"),
            "llc_bypasses_abs":  _gm(traces, "llc_bypasses_abs"),
            "stlb_bypasses_abs": _gm(traces, "stlb_bypasses_abs"),
            "llc_doa_abs":       _gm(traces, "llc_doa_abs"),
            "stlb_doa_abs":      _gm(traces, "stlb_doa_abs"),
            "llc_doa_pct":    _mean(traces, "llc_doa_pct"),
            "llc_md_pct":     _mean(traces, "llc_md_pct"),
            "stlb_doa_pct":   _mean(traces, "stlb_doa_pct"),
            "stlb_md_pct":    _mean(traces, "stlb_md_pct"),
            "lru_llc_mpki":   _gm(traces, "lru_llc_mpki"),
            "lru_stlb_mpki":  _gm(traces, "lru_stlb_mpki"),
            "pred_llc_mpki":  _gm(traces, "pred_llc_mpki"),
            "pred_stlb_mpki": _gm(traces, "pred_stlb_mpki"),
            "llc_mpki_red_pct":  _mean(traces, "llc_mpki_red_pct"),
            "stlb_mpki_red_pct": _mean(traces, "stlb_mpki_red_pct"),
            "bypass_coverage": bypass_coverage,
            "doa_reduction":   doa_reduction,
            "llc_bypass_rate_pct":  _mean(traces, "llc_bypass_rate_pct"),
            "stlb_bypass_rate_pct": _mean(traces, "stlb_bypass_rate_pct"),
            "llc_accuracy_pct":     _mean(traces, "llc_accuracy_pct"),
            "stlb_accuracy_pct":    _mean(traces, "stlb_accuracy_pct"),
            "llc_coverage_pct":     _mean(traces, "llc_coverage_pct"),
            "stlb_coverage_pct":    _mean(traces, "stlb_coverage_pct"),
            "traces":          traces,
        })

    return sorted(agg, key=lambda d: -d["speedup_pred"])


# ── plot helpers ──────────────────────────────────────────────────────────────

def _style(ax, ylabel: str, ylim_bottom: "float | None" = 0.0, fontsize: int = 8):
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


def _dots(ax, x, agg, key, offset=0.0, seed=0):
    for i, d in enumerate(agg):
        pts = [r[key] for r in d["traces"]
               if not (isinstance(r[key], float) and math.isnan(r[key]))]
        pts = [max(p, 1) for p in pts]   # clamp for log scale
        if len(pts) > 1:
            jitter = np.random.default_rng(seed + i).uniform(-0.18, 0.18, len(pts))
            ax.scatter(x[i] + offset + jitter, pts, s=11,
                       color=DOT_CLR, alpha=0.5, zorder=4, linewidths=0)


def _bar_log(ax, x, agg, agg_key, trace_key, ref_mb, ref_label, seed=0, color=DOA_CLR):
    vals = np.array([max(d[agg_key], 1e-3) for d in agg])
    ax.bar(x, vals, color=color, width=0.65,
           linewidth=0.4, edgecolor="white", zorder=2)
    ax.axhline(ref_mb, color=REF_CLR, linewidth=1.1, linestyle="--",
               zorder=5, label=ref_label)
    ax.legend(fontsize=6.5, loc="upper right", framealpha=0.85)
    ax.set_yscale("log")
    _log_fmt(ax)


def _stacked_doa_md(ax, x, agg, doa_key, md_key, trace_key, seed=0):
    doa = np.array([d[doa_key] for d in agg])
    md  = np.array([d[md_key]  for d in agg])
    ax.bar(x, doa, color=DOA_CLR, width=0.65, linewidth=0.4,
           edgecolor="white", zorder=2)
    ax.bar(x, md, bottom=doa, color=MD_CLR, width=0.65, linewidth=0.4,
           edgecolor="white", zorder=2)


def _bar_log_grouped(ax, x, agg, before_agg, after_agg,
                     before_trace, after_trace,
                     ref=None, ref_label="", seed=0,
                     color_before=DOA_CLR, color_after="#7EB5D5"):
    """Side-by-side before/after bars on log scale with optional capacity reference."""
    bw = 0.32
    before = np.array([max(d[before_agg], 1) for d in agg])
    after  = np.array([max(d[after_agg],  1) for d in agg])
    ax.bar(x - bw / 2, before, bw, color=color_before,
           linewidth=0.4, edgecolor="white", zorder=2, label="Before (LRU)")
    ax.bar(x + bw / 2, after,  bw, color=color_after,
           linewidth=0.4, edgecolor="white", zorder=2, label="After (pred)")
    if ref is not None:
        ax.axhline(ref, color=REF_CLR, linewidth=1.1, linestyle="--",
                   zorder=5, label=ref_label)
    for i, d in enumerate(agg):
        for key, off, s in [(before_trace, -bw/2, seed),
                             (after_trace,  +bw/2, seed+50)]:
            pts = [max(r[key], 1) for r in d["traces"]]
            if len(pts) > 1:
                jitter = np.random.default_rng(s + i).uniform(-0.12, 0.12, len(pts))
                ax.scatter(x[i] + off + jitter, pts, s=11,
                           color=DOT_CLR, alpha=0.5, zorder=4, linewidths=0)
    ax.legend(fontsize=6.5, loc="upper right", framealpha=0.85, ncol=3)
    ax.set_yscale("log")
    _log_fmt(ax)


def _stacked_dead_abs_log(ax, x, agg, doa_key, md_key, trace_doa,
                          ref, ref_label, seed=0):
    """Stacked absolute DoA + mostly-dead count, log scale, with capacity line."""
    doa = np.array([max(d[doa_key], 1) for d in agg])
    md  = np.array([max(d[md_key],  1) for d in agg])
    ax.bar(x, doa, color=DOA_CLR, width=0.65, linewidth=0.4,
           edgecolor="white", zorder=2, label="DoA")
    ax.bar(x, md, bottom=doa, color=MD_CLR, width=0.65, linewidth=0.4,
           edgecolor="white", zorder=2, label="Mostly-dead")
    ax.axhline(ref, color=REF_CLR, linewidth=1.1, linestyle="--",
               zorder=5, label=ref_label)
    _dots(ax, x, agg, trace_doa, seed=seed)
    ax.set_yscale("log")
    _log_fmt(ax)


def pred_color(v):
    if v > ZERO_THD:  return PRED_POS
    if v < -ZERO_THD: return PRED_NEG
    return PRED_ZERO


def both_color(v):
    if v > ZERO_THD:  return BOTH_POS
    if v < -ZERO_THD: return BOTH_NEG
    return BOTH_ZERO


# ── per-cache diagnostic plot ─────────────────────────────────────────────────

def plot_cache(agg: list, suite: str, cache: str, out: Path):
    """3-row problem characterisation; filters to benchmarks with cache pressure."""
    assert cache in ("llc", "stlb")
    p = cache

    if cache == "llc":
        cap     = LLC_LINES
        cap_lab = f"{LLC_LINES:,} lines (= 2 MB)"
        ws_ref  = LLC_SIZE_MB
        ws_lab  = "2 MB LLC"
        c_pri   = DOA_CLR
        title   = "LLC"
        agg = [d for d in agg if d["lru_llc_ev_abs"] > LLC_LINES * 5]
    else:
        cap     = STLB_ENTRIES
        cap_lab = f"{STLB_ENTRIES} entries (STLB cap.)"
        ws_ref  = STLB_SIZE_MB
        ws_lab  = f"STLB cap. ({STLB_SIZE_MB:.1f} MB)"
        c_pri   = "#4A7FC1"
        title   = "STLB"
        agg = [d for d in agg if d["lru_stlb_ev_abs"] > STLB_ENTRIES * 5]

    if not agg:
        print(f"WARNING: no {title} pressure benchmarks; skipping {out}")
        return

    n      = len(agg)
    x      = np.arange(n)
    labels = [_short(d["bm"], suite) for d in agg]
    FS     = 12

    fig = plt.figure(figsize=(max(6.5, n * 0.70 + 1.5), 11))
    gs  = gridspec.GridSpec(3, 1, figure=fig,
                            hspace=0.10,
                            left=0.10, right=0.97, top=0.93, bottom=0.22,
                            height_ratios=[1.1, 1.1, 1])

    ax_ws  = fig.add_subplot(gs[0])
    ax_ev  = fig.add_subplot(gs[1], sharex=ax_ws)
    ax_doa = fig.add_subplot(gs[2], sharex=ax_ws)

    # row 0: working-set size (MB, log)
    _bar_log(ax_ws, x, agg, f"{p}_ws_mb", f"{p}_ws_mb", ws_ref, ws_lab,
             seed=0, color=c_pri)
    for xi, d in zip(x, agg):
        v = max(d[f"{p}_ws_mb"], 1e-3)
        ax_ws.text(xi, v * 1.15, f"{v:.1f}", ha='center', va='bottom',
                   fontsize=FS-3, clip_on=True)
    ax_ws.legend(fontsize=FS, loc="upper right", framealpha=0.85)
    _style(ax_ws, f"{title} working-set\nsize (MB, log)", ylim_bottom=None, fontsize=FS)
    ax_ws.set_ylim(1, max(max(d[f"{p}_ws_mb"] for d in agg) * 1.5, 300))

    # row 1: evictions before bypass (LRU run, log)
    _bar_log(ax_ev, x, agg, f"lru_{p}_ev_abs", f"lru_{p}_ev_abs",
             cap, cap_lab, seed=200, color=c_pri)
    for xi, d in zip(x, agg):
        v = max(d[f"lru_{p}_ev_abs"], 1)
        ax_ev.text(xi, v * 1.15, _fmt_count(v), ha='center', va='bottom',
                   fontsize=FS-3, clip_on=True)
    ax_ev.set_ylim(top=max(d[f"lru_{p}_ev_abs"] for d in agg) * 1.6)
    ax_ev.legend(fontsize=FS, loc="upper right", framealpha=0.85)
    _style(ax_ev, f"{title} evictions\nbefore bypass (log)", ylim_bottom=None, fontsize=FS)

    # row 2: DoA% + Mostly-dead% stacked
    _stacked_doa_md(ax_doa, x, agg, f"{p}_doa_pct", f"{p}_md_pct",
                    f"{p}_doa_pct", seed=400)
    for xi, d in zip(x, agg):
        dv = d[f"{p}_doa_pct"]
        mv = d[f"{p}_md_pct"]
        if dv > 5:
            ax_doa.text(xi, dv / 2, f"{dv:.0f}%", ha='center', va='center',
                        fontsize=FS-3, color='white', fontweight='bold')
        if mv > 5:
            ax_doa.text(xi, dv + mv / 2, f"{mv:.0f}%", ha='center', va='center',
                        fontsize=FS-3, color='#2a2a2a', fontweight='bold')
    _style(ax_doa, f"{title} dead evictions\n(%;  DoA + Mostly-dead)", fontsize=FS)
    ax_doa.set_ylim(0, 105)
    ax_doa.legend(fontsize=FS, loc="upper right", framealpha=0.85,
                  handles=[mpatches.Patch(color=DOA_CLR, label="DoA"),
                           mpatches.Patch(color=MD_CLR,  label="Mostly-dead")])

    ax_doa.set_xticks(x)
    ax_doa.set_xticklabels(labels, rotation=55, ha="right",
                            fontsize=FS + 1, fontstyle="italic")
    ax_doa.set_xlim(-0.7, n - 0.3)
    ax_doa.tick_params(labelbottom=True)

    suite_label = {"dpc3": "SPEC CPU2006 DPC3",
                   "google": "Google",
                   "qmm": "Qualcomm Mobile"}.get(suite, suite)
    fig.suptitle(
        f"{suite_label} — {title} per-benchmark analysis  (lru_pred bypass \xb7 2 MB LLC)\n"
        "Sorted by lru_pred IPC speedup (descending)",
        fontsize=12, fontweight="bold")

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out}")


# ── per-cache effect plot (bypass impact) ────────────────────────────────────

def plot_cache_effect(agg: list, suite: str, cache: str, out: Path):
    """4-row bypass-effect plot (reductions + rate/coverage); filters to pressure benchmarks."""
    assert cache in ("llc", "stlb")
    p = cache
    RED_GRN  = "#5BA85A"
    RATE_CLR = "#E07B39"
    COV2_CLR = "#4C72B0"

    if cache == "llc":
        title = "LLC"
        agg = [d for d in agg if d["lru_llc_ev_abs"] > LLC_LINES * 5]
    else:
        title = "STLB"
        agg = [d for d in agg if d["lru_stlb_ev_abs"] > STLB_ENTRIES * 5]

    if not agg:
        print(f"WARNING: no {title} pressure benchmarks; skipping {out}")
        return

    n      = len(agg)
    x      = np.arange(n)
    labels = [_short(d["bm"], suite) for d in agg]
    FS     = 12

    fig = plt.figure(figsize=(max(6.5, n * 0.70 + 1.5), 12))
    gs  = gridspec.GridSpec(4, 1, figure=fig,
                            hspace=0.10,
                            left=0.10, right=0.97, top=0.93, bottom=0.22,
                            height_ratios=[1, 1, 1, 1])

    ax_ev_red = fig.add_subplot(gs[0])
    ax_mpki_r = fig.add_subplot(gs[1], sharex=ax_ev_red)
    ax_rate   = fig.add_subplot(gs[2], sharex=ax_ev_red)
    ax_cov    = fig.add_subplot(gs[3], sharex=ax_ev_red)

    # row 0: eviction reduction %
    vals = np.array([d[f"{p}_ev_red_pct"] for d in agg])
    ax_ev_red.bar(x, vals, color=RED_GRN, width=0.65,
                  linewidth=0.4, edgecolor="white", zorder=2)
    ax_ev_red.axhline(0, color="black", linewidth=0.5, zorder=3)
    for xi, v in zip(x, vals):
        va = 'bottom' if v >= 0 else 'top'
        y  = v + 0.5  if v >= 0 else v - 0.5
        ax_ev_red.text(xi, y, f"{v:.1f}%", ha='center', va=va, fontsize=FS-3)
    _style(ax_ev_red, f"{title} eviction\nreduction (%)", fontsize=FS)
    top_ev = max(max(d[f"{p}_ev_red_pct"] for d in agg), 1)
    bot_ev = min(min(d[f"{p}_ev_red_pct"] for d in agg), 0)
    ax_ev_red.set_ylim(bot_ev - 6, min(top_ev * 1.25 + 4, 108))

    # row 1: MPKI reduction %
    vals = np.array([d[f"{p}_mpki_red_pct"] for d in agg])
    ax_mpki_r.bar(x, vals, color=RED_GRN, width=0.65,
                  linewidth=0.4, edgecolor="white", zorder=2)
    ax_mpki_r.axhline(0, color="black", linewidth=0.5, zorder=3)
    for xi, v in zip(x, vals):
        va = 'bottom' if v >= 0 else 'top'
        y  = v + 0.5  if v >= 0 else v - 0.5
        ax_mpki_r.text(xi, y, f"{v:.1f}%", ha='center', va=va, fontsize=FS-3)
    _style(ax_mpki_r, f"{title} MPKI\nreduction (%)", fontsize=FS)
    top_mpki = max(max(d[f"{p}_mpki_red_pct"] for d in agg), 1)
    bot_mpki = min(min(d[f"{p}_mpki_red_pct"] for d in agg), 0)
    ax_mpki_r.set_ylim(bot_mpki - 6, min(top_mpki * 1.25 + 4, 108))

    # row 2: bypass rate (bypasses / lru_doa × 100%)
    # Measures how aggressively the predictor fires relative to the DoA pool size.
    # 100% = one bypass issued per DoA entry in the LRU baseline.
    # >100% means more bypasses than DoA entries (potential over-triggering).
    vals = np.array([d[f"{p}_bypass_rate_pct"] for d in agg])
    ax_rate.bar(x, vals, color=RATE_CLR, width=0.65,
                linewidth=0.4, edgecolor="white", zorder=2)
    ax_rate.axhline(100, color=REF_CLR, linewidth=1.1, linestyle="--",
                    zorder=5, label="100% = 1 bypass per DoA entry")
    for xi, v in zip(x, vals):
        ax_rate.text(xi, v + 0.5, f"{v:.1f}%", ha='center', va='bottom', fontsize=FS-3)
    ax_rate.legend(fontsize=FS-2, loc="upper right", framealpha=0.85)
    _style(ax_rate, f"{title} bypass rate\n(bypasses / DoA, %)", fontsize=FS)
    ax_rate.set_ylim(0, max(max(vals), 110) * 1.15)

    # row 3: bypass coverage (DoA eliminated / lru_doa × 100%)
    # Measures what fraction of the DoA problem the predictor addressed.
    # DoA eliminated = lru_doa − pred_doa (fewer dead evictions in pred run).
    # Note: per-decision accuracy requires shadow-table data (bypass_correct /
    # (bypass_correct + bypass_incorrect)) from a rerun with the updated build.
    vals = np.array([d[f"{p}_coverage_pct"] for d in agg])
    ax_cov.bar(x, vals, color=COV2_CLR, width=0.65,
               linewidth=0.4, edgecolor="white", zorder=2)
    ax_cov.axhline(100, color=REF_CLR, linewidth=1.1, linestyle="--",
                   zorder=5, label="100% = all DoA entries addressed")
    for xi, v in zip(x, vals):
        ax_cov.text(xi, v + 0.5, f"{v:.1f}%", ha='center', va='bottom', fontsize=FS-3)
    ax_cov.legend(fontsize=FS-2, loc="upper right", framealpha=0.85)
    _style(ax_cov, f"{title} bypass coverage\n(DoA elim. / lru DoA, %)", fontsize=FS)
    ax_cov.set_ylim(0, 105)

    ax_cov.set_xticks(x)
    ax_cov.set_xticklabels(labels, rotation=55, ha="right",
                            fontsize=FS + 1, fontstyle="italic")
    ax_cov.set_xlim(-0.7, n - 0.3)
    ax_cov.tick_params(labelbottom=True)

    suite_label = {"dpc3": "SPEC CPU2006 DPC3",
                   "google": "Google",
                   "qmm": "Qualcomm Mobile"}.get(suite, suite)
    fig.suptitle(
        f"{suite_label} — {title} bypass effect  (lru_pred bypass \xb7 2 MB LLC)\n"
        "Sorted by lru_pred IPC speedup (descending)",
        fontsize=12, fontweight="bold")

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out}")


# ── IPC speedup plot ──────────────────────────────────────────────────────────

def plot_ipc(agg: list, suite: str, out: Path):
    """Grouped bar: dpPred-only vs dpPred+cbPred; LLC-pressure benchmarks only."""
    agg = [d for d in agg if d["lru_llc_ev_abs"] > LLC_LINES * 5]
    if not agg:
        print(f"WARNING: no LLC pressure benchmarks for IPC plot; skipping {out}")
        return

    n      = len(agg)
    x      = np.arange(n)
    bw     = 0.35
    labels = [_short(d["bm"], suite) for d in agg]
    FS     = 12

    fig, ax = plt.subplots(figsize=(max(6.5, n * 0.70 + 1.5), 6))
    fig.subplots_adjust(left=0.10, right=0.97, top=0.88, bottom=0.22)

    dp_vals   = np.array([d["speedup_dp_only"] for d in agg])
    both_vals = np.array([d["speedup_pred"]    for d in agg])

    dp_colors   = [pred_color(v) if not math.isnan(v) else PRED_ZERO for v in dp_vals]
    both_colors = [both_color(v) if not math.isnan(v) else BOTH_ZERO for v in both_vals]

    ax.bar(x - bw / 2, np.nan_to_num(dp_vals), bw, color=dp_colors,
           linewidth=0.4, edgecolor="white", zorder=2)
    ax.bar(x + bw / 2, both_vals, bw, color=both_colors,
           linewidth=0.4, edgecolor="white", zorder=2)
    ax.axhline(0, color="black", linewidth=0.7, zorder=3)

    for i, (dp_v, both_v) in enumerate(zip(dp_vals, both_vals)):
        for val, off in [(dp_v, -bw / 2), (both_v, +bw / 2)]:
            if math.isnan(val):
                continue
            if val > CLIP_SPD:
                ax.annotate(
                    f"+{val:.0f}%",
                    xy=(x[i] + off, CLIP_SPD),
                    xytext=(x[i] + off, CLIP_SPD - 0.6),
                    ha="center", va="top", fontsize=FS - 3,
                    color="#1a5a38", fontweight="bold",
                    arrowprops=dict(arrowstyle="-", color="#1a5a38", lw=0.6))
            elif abs(val) >= 0.05:
                va = 'bottom' if val >= 0 else 'top'
                y  = val + 0.08 if val >= 0 else val - 0.08
                ax.text(x[i] + off, y, f"{val:+.2f}%", ha='center', va=va,
                        fontsize=FS-4, clip_on=True)

    _style(ax, "IPC speedup\nvs LRU (%)", ylim_bottom=None, fontsize=FS)
    dp_valid = [v for v in dp_vals if not math.isnan(v)]
    min_bar  = min(min(dp_valid) if dp_valid else 0, float(np.min(both_vals)), 0)
    ax.set_ylim(min(min_bar - 0.5, -2.5), CLIP_SPD)
    ax.tick_params(labelbottom=True)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=55, ha="right",
                        fontsize=FS + 1, fontstyle="italic")
    ax.set_xlim(-0.7, n - 0.3)

    spd_legend = [
        mpatches.Patch(color=PRED_POS,  label="dpPred only > 0"),
        mpatches.Patch(color=PRED_ZERO, label="dpPred only ≈ 0"),
        mpatches.Patch(color=PRED_NEG,  label="dpPred only < 0"),
        mpatches.Patch(color=BOTH_POS,  label="dpPred+cbPred > 0"),
        mpatches.Patch(color=BOTH_ZERO, label="dpPred+cbPred ≈ 0"),
        mpatches.Patch(color=BOTH_NEG,  label="dpPred+cbPred < 0"),
    ]
    ax.legend(handles=spd_legend, fontsize=FS - 2, loc="upper right",
              framealpha=0.88, ncol=3)

    suite_label = {"dpc3": "SPEC CPU2006 DPC3",
                   "google": "Google",
                   "qmm": "Qualcomm Mobile"}.get(suite, suite)
    fig.suptitle(
        f"{suite_label} — IPC speedup vs LRU baseline  (LLC-pressure benchmarks)\n"
        "Left: dpPred only \xb7 Right: dpPred + cbPred \xb7 2 MB LLC",
        fontsize=FS, fontweight="bold")

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out}")


# ── DEAD: old combined plot (replaced by plot_cache + plot_ipc) ───────────────

def _old_plot(agg: list, suite: str, out: Path):
    n      = len(agg)
    x      = np.arange(n)
    bw     = 0.38
    labels = [_short(d["bm"], suite) for d in agg]

    fig = plt.figure(figsize=(max(20, n * 1.05 + 2), 30))
    gs  = gridspec.GridSpec(9, 2, figure=fig,
                            hspace=0.12, wspace=0.28,
                            left=0.07, right=0.99, top=0.97, bottom=0.07,
                            height_ratios=[1.1, 1.1, 1, 1.1, 1, 1.1, 1, 1.1, 1.2])

    ax_llc_ws         = fig.add_subplot(gs[0, 0])
    ax_stlb_ws        = fig.add_subplot(gs[0, 1], sharex=ax_llc_ws)
    ax_llc_ev         = fig.add_subplot(gs[1, 0], sharex=ax_llc_ws)
    ax_stlb_ev        = fig.add_subplot(gs[1, 1], sharex=ax_llc_ws)
    ax_llc_doa        = fig.add_subplot(gs[2, 0], sharex=ax_llc_ws)
    ax_stlb_doa       = fig.add_subplot(gs[2, 1], sharex=ax_llc_ws)
    ax_llc_ev_after   = fig.add_subplot(gs[3, 0], sharex=ax_llc_ws)
    ax_stlb_ev_after  = fig.add_subplot(gs[3, 1], sharex=ax_llc_ws)
    ax_llc_ev_red     = fig.add_subplot(gs[4, 0], sharex=ax_llc_ws)
    ax_stlb_ev_red    = fig.add_subplot(gs[4, 1], sharex=ax_llc_ws)
    ax_llc_mpki       = fig.add_subplot(gs[5, 0], sharex=ax_llc_ws)
    ax_stlb_mpki      = fig.add_subplot(gs[5, 1], sharex=ax_llc_ws)
    ax_llc_mpki_red   = fig.add_subplot(gs[6, 0], sharex=ax_llc_ws)
    ax_stlb_mpki_red  = fig.add_subplot(gs[6, 1], sharex=ax_llc_ws)
    ax_llc_bp         = fig.add_subplot(gs[7, 0], sharex=ax_llc_ws)
    ax_stlb_bp        = fig.add_subplot(gs[7, 1], sharex=ax_llc_ws)
    ax_spd            = fig.add_subplot(gs[8, :], sharex=ax_llc_ws)

    CLIP_SPD = 5.5

    # ── row 0: working-set size (MB, log) ─────────────────────────────────────
    _bar_log(ax_llc_ws,  x, agg, "llc_ws_mb",  "llc_ws_mb",
             LLC_SIZE_MB,  "2 MB LLC", seed=0)
    _bar_log(ax_stlb_ws, x, agg, "stlb_ws_mb", "stlb_ws_mb",
             STLB_SIZE_MB, f"STLB cap. ({STLB_SIZE_MB:.1f} MB)", seed=100,
             color="#6A9CC9")
    _style(ax_llc_ws,  "LLC working-set\nsize (MB, log)", ylim_bottom=None)
    _style(ax_stlb_ws, "STLB working-set\nsize (MB, log)", ylim_bottom=None)
    ax_llc_ws.set_ylim(1, 500)
    ax_stlb_ws.set_ylim(1, 500)

    # ── row 1: evictions before bypass (LRU run, log) ─────────────────────────
    _bar_log(ax_llc_ev,  x, agg, "lru_llc_ev_abs",  "lru_llc_ev_abs",
             LLC_LINES,   f"{LLC_LINES:,} lines (= 2 MB)", seed=200)
    _bar_log(ax_stlb_ev, x, agg, "lru_stlb_ev_abs", "lru_stlb_ev_abs",
             STLB_ENTRIES, f"{STLB_ENTRIES} entries (STLB cap.)", seed=300,
             color="#6A9CC9")
    _style(ax_llc_ev,  "LLC evictions\nbefore bypass (log)", ylim_bottom=None)
    _style(ax_stlb_ev, "STLB evictions\nbefore bypass (log)", ylim_bottom=None)

    # ── row 2: DoA% + Mostly-dead% stacked ───────────────────────────────────
    _stacked_doa_md(ax_llc_doa,  x, agg,
                    "llc_doa_pct", "llc_md_pct",  "llc_doa_pct",  seed=400)
    _stacked_doa_md(ax_stlb_doa, x, agg,
                    "stlb_doa_pct", "stlb_md_pct", "stlb_doa_pct", seed=500)
    _style(ax_llc_doa,  "LLC dead evictions\n(%;  DoA + Mostly-dead)")
    _style(ax_stlb_doa, "STLB dead evictions\n(%;  DoA + Mostly-dead)")
    ax_llc_doa.set_ylim(0, 105)
    ax_stlb_doa.set_ylim(0, 105)
    ax_llc_doa.legend(fontsize=6.5, loc="upper right", framealpha=0.85,
                      handles=[mpatches.Patch(color=DOA_CLR, label="DoA"),
                                mpatches.Patch(color=MD_CLR,  label="Mostly-dead")])

    # ── row 3: evictions before vs after bypass (grouped, log) ───────────────
    _bar_log_grouped(ax_llc_ev_after,  x, agg,
                     "lru_llc_ev_abs",  "pred_llc_ev_abs",
                     "lru_llc_ev_abs",  "pred_llc_ev_abs",
                     LLC_LINES,   f"{LLC_LINES:,} lines (= 2 MB)", seed=800)
    _bar_log_grouped(ax_stlb_ev_after, x, agg,
                     "lru_stlb_ev_abs", "pred_stlb_ev_abs",
                     "lru_stlb_ev_abs", "pred_stlb_ev_abs",
                     STLB_ENTRIES, f"{STLB_ENTRIES} entries (STLB cap.)", seed=900,
                     color_before="#4A7FC1", color_after="#7EB5D5")
    _style(ax_llc_ev_after,  "LLC evictions\nbefore vs after (log)", ylim_bottom=None)
    _style(ax_stlb_ev_after, "STLB evictions\nbefore vs after (log)", ylim_bottom=None)

    # ── row 4: eviction reduction % ──────────────────────────────────────────
    RED_GRN = "#5BA85A"
    for ax, key in [(ax_llc_ev_red,  "llc_ev_red_pct"),
                    (ax_stlb_ev_red, "stlb_ev_red_pct")]:
        vals = np.array([d[key] for d in agg])
        ax.bar(x, vals, color=RED_GRN, width=0.65,
               linewidth=0.4, edgecolor="white", zorder=2)
        ax.axhline(0, color="black", linewidth=0.5, zorder=3)
        _dots(ax, x, agg, key, seed=1200)
    _style(ax_llc_ev_red,  "LLC eviction\nreduction (%)")
    _style(ax_stlb_ev_red, "STLB eviction\nreduction (%)")
    top_ev = max(max(d["llc_ev_red_pct"]  for d in agg),
                 max(d["stlb_ev_red_pct"] for d in agg), 1)
    ax_llc_ev_red.set_ylim(-3, min(top_ev * 1.15 + 2, 105))
    ax_stlb_ev_red.set_ylim(-3, min(top_ev * 1.15 + 2, 105))

    # ── row 5: MPKI before vs after bypass (grouped, log) ────────────────────
    _bar_log_grouped(ax_llc_mpki,  x, agg,
                     "lru_llc_mpki",  "pred_llc_mpki",
                     "lru_llc_mpki",  "pred_llc_mpki",
                     ref=None, seed=1300)
    _bar_log_grouped(ax_stlb_mpki, x, agg,
                     "lru_stlb_mpki", "pred_stlb_mpki",
                     "lru_stlb_mpki", "pred_stlb_mpki",
                     ref=None, seed=1400,
                     color_before="#4A7FC1", color_after="#7EB5D5")
    _style(ax_llc_mpki,  "LLC MPKI\nbefore vs after (log)", ylim_bottom=None)
    _style(ax_stlb_mpki, "STLB MPKI\nbefore vs after (log)", ylim_bottom=None)

    # ── row 6: MPKI reduction % ───────────────────────────────────────────────
    for ax, key in [(ax_llc_mpki_red,  "llc_mpki_red_pct"),
                    (ax_stlb_mpki_red, "stlb_mpki_red_pct")]:
        vals = np.array([d[key] for d in agg])
        ax.bar(x, vals, color=RED_GRN, width=0.65,
               linewidth=0.4, edgecolor="white", zorder=2)
        ax.axhline(0, color="black", linewidth=0.5, zorder=3)
        _dots(ax, x, agg, key, seed=1500)
    _style(ax_llc_mpki_red,  "LLC MPKI\nreduction (%)")
    _style(ax_stlb_mpki_red, "STLB MPKI\nreduction (%)")
    top_mpki = max(max(d["llc_mpki_red_pct"]  for d in agg),
                   max(d["stlb_mpki_red_pct"] for d in agg), 1)
    ax_llc_mpki_red.set_ylim(-3, min(top_mpki * 1.15 + 2, 105))
    ax_stlb_mpki_red.set_ylim(-3, min(top_mpki * 1.15 + 2, 105))

    # ── row 7: bypass count (pred run, log) ───────────────────────────────────
    _bar_log(ax_llc_bp,  x, agg, "llc_bypasses_abs",  "llc_bypasses_abs",
             LLC_LINES,   f"{LLC_LINES:,} lines (= 2 MB)", seed=1600,
             color=COV_CLR)
    _bar_log(ax_stlb_bp, x, agg, "stlb_bypasses_abs", "stlb_bypasses_abs",
             STLB_ENTRIES, f"{STLB_ENTRIES} entries (STLB cap.)", seed=1700,
             color=COV_CLR)
    _style(ax_llc_bp,  "LLC bypasses\n(absolute, log)", ylim_bottom=None)
    _style(ax_stlb_bp, "STLB bypasses\n(absolute, log)", ylim_bottom=None)

    # ── row 8: IPC speedup ────────────────────────────────────────────────────
    pred_vals = np.array([d["speedup_pred"] for d in agg])
    slv_vals  = np.array([d["speedup_slv"]  for d in agg])

    pred_colors = [pred_color(v) for v in pred_vals]
    slv_colors  = []
    for v in slv_vals:
        if math.isnan(v) or v > ZERO_THD: slv_colors.append(SRRIP_CLR)
        elif v < -ZERO_THD:               slv_colors.append("#B05040")
        else:                             slv_colors.append("#7ABF9A")

    ax_spd.bar(x - bw / 2, pred_vals, bw, color=pred_colors,
               linewidth=0.4, edgecolor="white", zorder=2)
    ax_spd.bar(x + bw / 2, slv_vals,  bw, color=slv_colors,
               linewidth=0.4, edgecolor="white", zorder=2)
    ax_spd.axhline(0, color="black", linewidth=0.7, zorder=3)

    for i, d in enumerate(agg):
        pts_p = [r["speedup_pred"] for r in d["traces"]]
        if len(pts_p) > 1:
            jitter = np.random.default_rng(i * 2).uniform(-0.12, 0.12, len(pts_p))
            ax_spd.scatter(x[i] - bw / 2 + jitter, pts_p, s=11,
                           color=DOT_CLR, alpha=0.5, zorder=5, linewidths=0)
        pts_s = [r["speedup_slv"] for r in d["traces"]
                 if not math.isnan(r["speedup_slv"])]
        if len(pts_s) > 1:
            jitter = np.random.default_rng(i * 2 + 1).uniform(-0.12, 0.12, len(pts_s))
            ax_spd.scatter(x[i] + bw / 2 + jitter, pts_s, s=11,
                           color=DOT_CLR, alpha=0.5, zorder=5, linewidths=0)

    for i, d in enumerate(agg):
        for r in d["traces"]:
            for val, off in [(r["speedup_pred"], -bw / 2),
                             (r["speedup_slv"],  +bw / 2)]:
                if not math.isnan(val) and val > CLIP_SPD:
                    ax_spd.annotate(
                        f"+{val:.0f}%",
                        xy=(x[i] + off, CLIP_SPD),
                        xytext=(x[i] + off, CLIP_SPD - 0.6),
                        ha="center", va="top", fontsize=5.5,
                        color="#1a5a38", fontweight="bold",
                        arrowprops=dict(arrowstyle="-", color="#1a5a38", lw=0.6))

    _style(ax_spd, "IPC speedup\nvs LRU (%)", ylim_bottom=-2.5)
    ax_spd.set_ylim(-2.5, CLIP_SPD)
    ax_spd.tick_params(labelbottom=True)

    spd_legend = [
        mpatches.Patch(color=PRED_POS,  label="lru_pred > 0"),
        mpatches.Patch(color=PRED_ZERO, label="lru_pred ≈ 0"),
        mpatches.Patch(color=PRED_NEG,  label="lru_pred < 0"),
        mpatches.Patch(color=SRRIP_CLR, label="srrip_live"),
        plt.scatter([], [], s=11, color=DOT_CLR, alpha=0.6, label="SimPoint"),
    ]
    ax_spd.legend(handles=spd_legend, fontsize=7, loc="upper right",
                  framealpha=0.88, ncol=5)

    # ── x-axis ────────────────────────────────────────────────────────────────
    ax_spd.set_xticks(x)
    ax_spd.set_xticklabels(labels, rotation=55, ha="right",
                            fontsize=7.5, fontstyle="italic")
    ax_spd.set_xlim(-0.7, n - 0.3)

    # ── column headers ────────────────────────────────────────────────────────
    ax_llc_ws.set_title("LLC", fontsize=10, fontweight="bold", pad=5)
    ax_stlb_ws.set_title("STLB", fontsize=10, fontweight="bold", pad=5)

    suite_label = {"dpc3": "SPEC CPU2006 DPC3",
                   "google": "Google",
                   "qmm": "Qualcomm Mobile"}.get(suite, suite)
    fig.suptitle(
        f"{suite_label} — per-benchmark working-set, eviction, and bypass analysis"
        f"  (2 MB LLC)\n"
        "Sorted by lru_pred IPC speedup (descending)",
        fontsize=9.5, fontweight="bold", y=1.007)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out}")


# ── entry point ───────────────────────────────────────────────────────────────

SUITE_DEFAULTS = {
    "dpc3":   ("results/cluster/dpc3_pol_20260511_1545",
                "results/plots/dpc3_workload_narrative.png"),
    "google": ("results/cluster/google_pol_20260511_1545",
                "results/plots/google_workload_narrative.png"),
    "qmm":    ("results/cluster/qmm_pol_20260511_1545",
                "results/plots/qmm_workload_narrative.png"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite",   required=True, choices=["dpc3", "google", "qmm"])
    ap.add_argument("--pol-dir", default=None)
    ap.add_argument("--out",     default=None)
    args = ap.parse_args()

    default_dir, default_out = SUITE_DEFAULTS[args.suite]
    pol_dir = Path(args.pol_dir or default_dir)
    out     = Path(args.out     or default_out)

    rows = load_data(pol_dir, args.suite)
    if not rows:
        sys.exit("ERROR: no traces loaded — check --pol-dir")
    agg = aggregate(rows, args.suite)
    print(f"Loaded {len(rows)} traces → {len(agg)} benchmarks")
    stem, suf, par = out.stem, out.suffix, out.parent
    plot_cache(agg, args.suite, "llc",              par / f"{stem}_llc{suf}")
    plot_cache(agg, args.suite, "stlb",             par / f"{stem}_stlb{suf}")
    plot_cache_effect(agg, args.suite, "llc",        par / f"{stem}_llc_effect{suf}")
    plot_cache_effect(agg, args.suite, "stlb",       par / f"{stem}_stlb_effect{suf}")
    plot_ipc(agg, args.suite,                        par / f"{stem}_ipc{suf}")


if __name__ == "__main__":
    main()
