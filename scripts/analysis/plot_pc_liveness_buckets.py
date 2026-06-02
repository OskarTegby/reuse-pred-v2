#!/usr/bin/env python3
"""
plot_pc_liveness_buckets.py — per-PC liveness signal clarity.

For each suite and cache level, classifies every PC by whether its evictions
are dominated by one liveness class (DoA / mostly-dead / mostly-alive) or mixed.

A PC is considered "clearly X" if >= DOMINANCE_THD % of its evictions fall in
class X.  All other PCs are "mixed".

Each bar's height = fraction of TOTAL evictions that come from PCs in that group.

This answers: "Does each PC give a clear signal about the liveness of its blocks,
and does that cover enough cache traffic to be worth exploiting?"

Input:  results/<liveness_char_dir>/<suite>/*/champsim.out
        (produced by LIVENESS_CHAR=1 runs)

Usage:
    python3 scripts/analysis/plot_pc_liveness_buckets.py <liveness_char_dir>

Output: results/plots/pc_liveness_buckets.png
"""

import re
import sys
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from collections import defaultdict

ROOT     = Path(__file__).resolve().parents[2]
RESULTS  = ROOT / "results"
PLOTS    = RESULTS / "plots"

DOMINANCE_THD = 0.80   # fraction needed to be "clearly" one class

if len(sys.argv) < 2:
    print(f"Usage: {Path(__file__).name} <liveness_char_dir>", file=sys.stderr)
    sys.exit(1)

CHAR_DIR = RESULTS / sys.argv[1]

SUITES = ["DPC3", "GAP", "GMS", "Google", "Ligra", "ML", "QMM"]

CHAR_BEGIN = re.compile(r"^(\S+) LIVENESS_CHAR BEGIN$")
CHAR_END   = re.compile(r"^(\S+) LIVENESS_CHAR END$")
PC_LINE    = re.compile(
    r"PC=0x([0-9a-f]+)\s+total=(\d+)\s+doa=(\d+)\s+"
    r"mostly_dead=(\d+)\s+mostly_alive=(\d+)"
)


def parse_char_file(path: Path) -> dict:
    """Return {cache_name: {pc: {total,doa,dead,alive}}}."""
    result = {}
    current = None
    try:
        for line in path.read_text(errors="replace").splitlines():
            m = CHAR_BEGIN.match(line)
            if m:
                current = m.group(1)
                result[current] = {}
                continue
            if CHAR_END.match(line):
                current = None
                continue
            if current is not None:
                m = PC_LINE.search(line)
                if m:
                    result[current][int(m.group(1), 16)] = {
                        "total": int(m.group(2)), "doa":   int(m.group(3)),
                        "dead":  int(m.group(4)), "alive": int(m.group(5)),
                    }
    except OSError:
        pass
    return result


def classify_pc(e: dict) -> str:
    """Return dominant class label or 'mixed'."""
    t = e["total"]
    if t == 0:
        return "mixed"
    if e["doa"]   / t >= DOMINANCE_THD: return "doa"
    if e["dead"]  / t >= DOMINANCE_THD: return "mostly-dead"
    if e["alive"] / t >= DOMINANCE_THD: return "mostly-alive"
    return "mixed"


GROUPS = ["doa", "mostly-dead", "mostly-alive", "mixed"]


def aggregate_suite(suite_lower: str) -> dict:
    """
    Returns {cache_name: {group: fraction_of_total_evictions}}.
    """
    suite_dir = CHAR_DIR / suite_lower
    if not suite_dir.exists():
        return {}

    # cache → group → total evictions from PCs in that group
    cache_group_evictions: dict = defaultdict(lambda: defaultdict(int))
    cache_total:           dict = defaultdict(int)

    for trace_dir in sorted(suite_dir.iterdir()):
        out = trace_dir / "champsim.out"
        if not out.is_file():
            continue
        per_cache = parse_char_file(out)
        for cache, pcs in per_cache.items():
            for pc_data in pcs.values():
                t = pc_data["total"]
                if t == 0:
                    continue
                group = classify_pc(pc_data)
                cache_group_evictions[cache][group] += t
                cache_total[cache]                  += t

    result = {}
    for cache, groups in cache_group_evictions.items():
        t = cache_total[cache]
        result[cache] = {g: groups.get(g, 0) / t * 100 if t > 0 else 0
                         for g in GROUPS}
    return result


# ── Collect ────────────────────────────────────────────────────────────────────

llc_data  = {}
stlb_data = {}

for suite in SUITES:
    agg = aggregate_suite(suite.lower())
    if not agg:
        print(f"  WARNING: no data for {suite}", file=sys.stderr)
        llc_data[suite]  = {g: 0 for g in GROUPS}
        stlb_data[suite] = {g: 0 for g in GROUPS}
        continue
    for k, v in agg.items():
        if "LLC" in k.upper():
            llc_data[suite] = v
        elif "STLB" in k.upper():
            stlb_data[suite] = v
    if suite not in llc_data:
        llc_data[suite]  = {g: 0 for g in GROUPS}
    if suite not in stlb_data:
        stlb_data[suite] = {g: 0 for g in GROUPS}

# ── Plot ───────────────────────────────────────────────────────────────────────

# Stacked bars: one bar per suite, stacked by group
C = {"doa": "#c0392b", "mostly-dead": "#e67e22",
     "mostly-alive": "#2980b9", "mixed": "#bdc3c7"}
LABELS = {"doa": "Clearly DoA", "mostly-dead": "Clearly mostly-dead",
          "mostly-alive": "Clearly mostly-alive", "mixed": "Mixed / unclear"}

x  = np.arange(len(SUITES))
w  = 0.35

fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)

for ax, data, title in [(axes[0], llc_data, "LLC"),
                        (axes[1], stlb_data, "STLB")]:
    bottoms = np.zeros(len(SUITES))
    for group in GROUPS:
        vals = np.array([data[s][group] for s in SUITES])
        bars = ax.bar(x, vals, width=w, bottom=bottoms,
                      label=LABELS[group], color=C[group])
        # Label segments that are wide enough to read
        for i, (v, b) in enumerate(zip(vals, bottoms)):
            if v >= 5:
                ax.text(x[i], b + v / 2, f"{v:.0f}%",
                        ha="center", va="center",
                        fontsize=7, color="white", fontweight="bold")
        bottoms += vals

    ax.set_title(title, fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(SUITES)
    ax.set_ylim(0, 105)
    ax.yaxis.grid(True, linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)
    if ax is axes[0]:
        ax.set_ylabel("Fraction of total evictions (%)")

axes[0].legend(loc="lower left", fontsize=9)
fig.suptitle(
    f"Per-PC liveness signal clarity (dominance threshold = {DOMINANCE_THD*100:.0f}%)\n"
    "A PC is 'clearly X' if ≥80% of its evictions fall in class X — "
    "these are the PCs the replacement policy can reliably act on.",
    fontsize=10,
)
fig.tight_layout()

OUT = PLOTS / "pc_liveness_buckets.png"
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"Saved {OUT}")

# ── Summary table ──────────────────────────────────────────────────────────────
print(f"\n{'Suite':<8}  {'DoA':>8}  {'Mostly-dead':>12}  "
      f"{'Mostly-alive':>13}  {'Mixed':>8}   (LLC)")
print("-" * 60)
for s in SUITES:
    d = llc_data[s]
    print(f"{s:<8}  {d['doa']:>7.1f}%  {d['mostly-dead']:>11.1f}%  "
          f"{d['mostly-alive']:>12.1f}%  {d['mixed']:>7.1f}%")
