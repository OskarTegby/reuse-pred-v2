#!/usr/bin/env python3
"""
Plot per-suite geomean liveness breakdown (DoA / mostly-dead / mostly-alive)
at the LLC and STLB from lru_baseline runs.

Output: results/plots/liveness_rates.png
"""

import os
import re
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
RESULTS = os.path.join(ROOT, "results")
OUT = os.path.join(RESULTS, "plots", "liveness_rates.png")

SUITES = {
    "DPC3":   ("dpc3_thd_rebaseline_20260605_2316",  "lru"),
    "GAP":    ("gap_thd_rebaseline_20260605_2316",   "lru"),
    "GMS":    ("gms_thd_rebaseline_20260605_2316",   "lru"),
    "Google": ("google_repl_pol_20260522_0722",       "lru_baseline"),
    "Ligra":  ("ligra_thd_rebaseline_20260605_2316", "lru"),
    "ML":     ("ml_thd_rebaseline_20260605_2316",    "lru"),
    "QMM":    ("qmm_thd_rebaseline_20260604_2307",   "lru"),
}

LLC_PAT = re.compile(
    r"LLC LIVENESS EVICTIONS:\s+(\d+)\s+"
    r"DOA:\s+(\d+)\s+\([^)]+\)\s+"
    r"MOSTLY_DEAD:\s+(\d+)\s+\([^)]+\)\s+"
    r"MOSTLY_ALIVE:\s+(\d+)"
)
STLB_PAT = re.compile(
    r"cpu0_STLB LIVENESS EVICTIONS:\s+(\d+)\s+"
    r"DOA:\s+(\d+)\s+\([^)]+\)\s+"
    r"MOSTLY_DEAD:\s+(\d+)\s+\([^)]+\)\s+"
    r"MOSTLY_ALIVE:\s+(\d+)"
)


def fractions(total, doa, dead, alive):
    """Return percentages from raw counts; all four values from one trace."""
    if total == 0:
        return 0.0, 0.0, 0.0
    return 100.0 * doa / total, 100.0 * dead / total, 100.0 * alive / total


def collect(suite_dir, lru_subdir="lru_baseline"):
    """Sum raw counts across all traces, then compute fractions from totals."""
    llc  = {"total": 0, "doa": 0, "dead": 0, "alive": 0}
    stlb = {"total": 0, "doa": 0, "dead": 0, "alive": 0}
    base = os.path.join(RESULTS, suite_dir, lru_subdir)
    for trace_dir in sorted(os.listdir(base)):
        out = os.path.join(base, trace_dir, "champsim.out")
        if not os.path.isfile(out):
            continue
        text = open(out).read()
        m = LLC_PAT.search(text)
        if m:
            llc["total"] += int(m.group(1))
            llc["doa"]   += int(m.group(2))
            llc["dead"]  += int(m.group(3))
            llc["alive"] += int(m.group(4))
        m = STLB_PAT.search(text)
        if m:
            stlb["total"] += int(m.group(1))
            stlb["doa"]   += int(m.group(2))
            stlb["dead"]  += int(m.group(3))
            stlb["alive"] += int(m.group(4))
    llc_f  = fractions(llc["total"],  llc["doa"],  llc["dead"],  llc["alive"])
    stlb_f = fractions(stlb["total"], stlb["doa"], stlb["dead"], stlb["alive"])
    return (
        {"doa": llc_f[0],  "dead": llc_f[1],  "alive": llc_f[2]},
        {"doa": stlb_f[0], "dead": stlb_f[1], "alive": stlb_f[2]},
    )


labels = list(SUITES.keys())
llc_data  = {"doa": [], "dead": [], "alive": []}
stlb_data = {"doa": [], "dead": [], "alive": []}

for name, (dirname, subdir) in SUITES.items():
    llc, stlb = collect(dirname, subdir)
    for k in ("doa", "dead", "alive"):
        llc_data[k].append(llc[k])
        stlb_data[k].append(stlb[k])

x = np.arange(len(labels))
w = 0.35

# Colors: DoA=dark red, mostly-dead=orange, mostly-alive=steel blue
C_DOA   = "#c0392b"
C_DEAD  = "#e67e22"
C_ALIVE = "#2980b9"

MIN_LABEL_PCT = 3.5   # don't annotate segments narrower than this

fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)

for ax, data, title in [
    (axes[0], llc_data,  "LLC"),
    (axes[1], stlb_data, "STLB"),
]:
    doa_arr   = np.array(data["doa"])
    dead_arr  = np.array(data["dead"])
    alive_arr = np.array(data["alive"])

    bars_doa   = ax.bar(x, doa_arr,  width=w, label="DoA",         color=C_DOA)
    bars_dead  = ax.bar(x, dead_arr,  width=w, bottom=doa_arr,
                        label="Mostly-dead",  color=C_DEAD)
    bars_alive = ax.bar(x, alive_arr, width=w, bottom=doa_arr + dead_arr,
                        label="Mostly-alive", color=C_ALIVE)

    # Percentage labels centred in each segment
    for i in range(len(x)):
        # DoA segment
        if doa_arr[i] >= MIN_LABEL_PCT:
            ax.text(x[i], doa_arr[i] / 2,
                    f"{doa_arr[i]:.0f}%", ha="center", va="center",
                    fontsize=7, color="white", fontweight="bold")
        # Mostly-dead segment
        if dead_arr[i] >= MIN_LABEL_PCT:
            ax.text(x[i], doa_arr[i] + dead_arr[i] / 2,
                    f"{dead_arr[i]:.0f}%", ha="center", va="center",
                    fontsize=7, color="white", fontweight="bold")
        # Mostly-alive segment
        if alive_arr[i] >= MIN_LABEL_PCT:
            ax.text(x[i], doa_arr[i] + dead_arr[i] + alive_arr[i] / 2,
                    f"{alive_arr[i]:.0f}%", ha="center", va="center",
                    fontsize=7, color="white", fontweight="bold")

    ax.set_title(title)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.yaxis.grid(True, linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)
    if ax is axes[0]:
        ax.set_ylabel("Fraction of evictions (%)")

axes[0].legend(loc="lower left", fontsize=9)
fig.suptitle(
    "Per-block liveness breakdown — aggregated over traces, LRU baseline\n"
    "(DoA = 0 hits; mostly-dead = last hit in first half of residency; "
    "mostly-alive = last hit in second half)",
    fontsize=10,
)
fig.tight_layout()
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"Saved {OUT}")

print(f"\n{'Suite':<10} {'LLC DoA':>8} {'LLC Dead':>10} {'LLC Alive':>11}"
      f" {'STLB DoA':>10} {'STLB Dead':>11} {'STLB Alive':>12}")
print("-" * 74)
for i, name in enumerate(labels):
    print(f"{name:<10} {llc_data['doa'][i]:>7.1f}% {llc_data['dead'][i]:>9.1f}%"
          f" {llc_data['alive'][i]:>10.1f}%"
          f" {stlb_data['doa'][i]:>9.1f}% {stlb_data['dead'][i]:>10.1f}%"
          f" {stlb_data['alive'][i]:>11.1f}%")
