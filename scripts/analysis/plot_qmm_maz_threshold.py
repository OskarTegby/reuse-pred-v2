#!/usr/bin/env python3
"""
plot_qmm_maz_threshold.py — threshold sensitivity for QMM (Mazumdar) 3-class runs.

Directory layout expected:
    results/<run_dir>/lru/<trace>/champsim.out
    results/<run_dir>/llc_srrip_live/thd{N}/<trace>/champsim.out
    results/<run_dir>/llc_ipv_live/thd{N}/<trace>/champsim.out
    results/<run_dir>/stlb_srrip_live/thd{N}/<trace>/champsim.out
    results/<run_dir>/stlb_ipv_live/thd{N}/<trace>/champsim.out

Usage:
    python3 scripts/analysis/plot_qmm_maz_threshold.py qmm_maz_thd_20260601_1537
"""

import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from champsim_utils import parse_ipc

ROOT    = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"
PLOTS   = ROOT / "results" / "plots"

THD_VALUES = [1, 2, 4, 8, 16]

POLICIES = [
    ("llc_srrip_live",  "LLC SRRIP-Live",  "#2E8B6A"),
    ("llc_ipv_live",    "LLC IPV-Live",     "#1A6FA0"),
    ("stlb_srrip_live", "STLB SRRIP-Live",  "#C0392B"),
    ("stlb_ipv_live",   "STLB IPV-Live",    "#8E44AD"),
]


def geomean(vals):
    pos = [v for v in vals if v is not None and v > 0]
    if not pos:
        return None
    return math.exp(sum(math.log(v) for v in pos) / len(pos))


def load_ipc_dir(d: Path) -> dict:
    """Return {trace_name: ipc} for all traces in directory d."""
    out = {}
    if not d.is_dir():
        return out
    for trace_dir in sorted(d.iterdir()):
        f = trace_dir / "champsim.out"
        if f.is_file():
            ipc = parse_ipc(f)
            if ipc is not None:
                out[trace_dir.name] = ipc
    return out


def speedup_pct(policy_ipc: dict, lru_ipc: dict) -> list:
    ratios = [policy_ipc[t] / lru_ipc[t]
              for t in policy_ipc if t in lru_ipc and lru_ipc[t] > 0]
    return ratios


if len(sys.argv) < 2:
    print(f"Usage: {Path(__file__).name} <run_dir>", file=sys.stderr)
    sys.exit(1)

run_dir = RESULTS / sys.argv[1]
lru_ipc = load_ipc_dir(run_dir / "lru")

if not lru_ipc:
    sys.exit(f"ERROR: no LRU results found in {run_dir / 'lru'}")

print(f"LRU baseline: {len(lru_ipc)} traces")
print()

# ── Collect geomean speedups ────────────────────────────────────────────────

results = {}   # policy_key -> {thd: geomean_speedup_pct}

for pol_dir, label, _ in POLICIES:
    thd_gm = {}
    for thd in THD_VALUES:
        ipc = load_ipc_dir(run_dir / pol_dir / f"thd{thd}")
        if not ipc:
            continue
        ratios = speedup_pct(ipc, lru_ipc)
        gm = geomean(ratios)
        if gm is not None:
            thd_gm[thd] = (gm - 1) * 100
    results[pol_dir] = thd_gm

# ── Print table ─────────────────────────────────────────────────────────────

print(f"{'Policy':<20}  " + "  ".join(f"thd={t:>2}" for t in THD_VALUES) + "  Best")
print("-" * 80)
for pol_dir, label, _ in POLICIES:
    d = results[pol_dir]
    vals = [f"{d[t]:+.3f}%" if t in d else "   N/A " for t in THD_VALUES]
    best_thd = max(d, key=d.get) if d else None
    best_str = f"thd={best_thd} ({d[best_thd]:+.3f}%)" if best_thd else "N/A"
    print(f"{label:<20}  {'  '.join(vals)}  {best_str}")

# ── Plot ────────────────────────────────────────────────────────────────────

fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))

for ax, (pol_keys, title) in zip(axes, [
    (["llc_srrip_live", "llc_ipv_live"],    "LLC"),
    (["stlb_srrip_live", "stlb_ipv_live"],  "STLB"),
]):
    x = np.arange(len(THD_VALUES))
    width = 0.38
    offsets = [-width / 2, width / 2]

    for offset, pol_dir in zip(offsets, pol_keys):
        label = next(l for k, l, _ in POLICIES if k == pol_dir)
        color = next(c for k, _, c in POLICIES if k == pol_dir)
        d = results[pol_dir]
        vals = [d.get(t, float("nan")) for t in THD_VALUES]
        bars = ax.bar(x + offset, vals, width * 0.92,
                      label=label, color=color, edgecolor="black", linewidth=0.4)
        for bar, v in zip(bars, vals):
            if not math.isnan(v):
                ypos = v + 0.04 if v >= 0 else v - 0.04
                va = "bottom" if v >= 0 else "top"
                ax.text(bar.get_x() + bar.get_width() / 2, ypos,
                        f"{v:+.2f}%", ha="center", va=va,
                        fontsize=6.5, rotation=90)

    ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
    ax.set_xticks(x)
    ax.set_xticklabels([f"thd={t}" for t in THD_VALUES])
    ax.set_ylabel("Geomean IPC speedup vs LRU (%)")
    ax.set_title(title, fontsize=12)
    ax.legend(fontsize=8)
    ax.yaxis.grid(True, linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)

fig.suptitle(
    f"QMM (Mazumdar) — 3-class threshold sensitivity\n"
    f"({len(lru_ipc)} traces, thresholds = MID_THD, LOW_THD=0)",
    fontsize=10,
)
fig.tight_layout()

out = PLOTS / "qmm_maz_threshold_sensitivity.png"
PLOTS.mkdir(parents=True, exist_ok=True)
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"\nSaved: {out}")
