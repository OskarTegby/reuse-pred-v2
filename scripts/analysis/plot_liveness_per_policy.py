#!/usr/bin/env python3
"""
Plot LLC liveness breakdown (DoA / mostly-dead / mostly-alive) for LRU, SRRIP,
and IPV baseline policies, grouped by benchmark suite.

Sums the per-suite "LLC LIVENESS EVICTIONS: <total> DOA: <n> ... MOSTLY_DEAD:
<n> ... MOSTLY_ALIVE: <n>" line (roi_stats-derived, properly reset every
phase) across all traces in a suite, then plots fractions as grouped stacked
bars.

Output: results/plots/liveness_per_policy.png
"""

import os
import re
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import json

ROOT    = os.path.join(os.path.dirname(__file__), "..", "..")
RESULTS = os.path.join(ROOT, "results")
OUT     = os.path.join(RESULTS, "plots", "liveness_per_policy.png")

# Re-extracted 2026-07-02 from the same source directories (see
# FIGURE_PROVENANCE.md). The original RAW here (see git history) summed the
# per-PC "LLC LIVENESS_CHAR BEGIN...END" dump instead of this line -- that
# dump was warmup+ROI cumulative (pc_liveness_char had no phase reset, fixed
# in fix-pc-liveness-phase-reset / commit b0d1c047391e), inflating LRU and
# SRRIP counts by ~2x. IPV's original numbers matched this re-extraction
# exactly (verified byte-for-byte) and are unchanged.
RAW = {"SRRIP": {"QMM": {"alive": 523648, "dead": 1309086, "doa": 6405421, "total": 8238155}, "Google": {"alive": 2801205, "dead": 8442057, "doa": 46382134, "total": 57625396}, "Ligra": {"alive": 502087, "dead": 958339, "doa": 34011916, "total": 35472342}, "GAP": {"alive": 1373678, "dead": 1951856, "doa": 18503939, "total": 21829473}, "DPC3": {"alive": 1015601, "dead": 10282550, "doa": 96264282, "total": 107562433}, "ML": {"alive": 110256, "dead": 1903896, "doa": 104506072, "total": 106520224}, "GMS": {"alive": 176645, "dead": 448012, "doa": 5966229, "total": 6590886}}, "LRU": {"QMM": {"alive": 1207365, "dead": 1749802, "doa": 6297828, "total": 9254995}, "Google": {"alive": 5175141, "dead": 10723120, "doa": 44766468, "total": 60664729}, "Ligra": {"alive": 995839, "dead": 1459344, "doa": 33809284, "total": 36264467}, "GAP": {"alive": 2807130, "dead": 3458943, "doa": 17918181, "total": 24184254}, "DPC3": {"alive": 2040753, "dead": 11394670, "doa": 96889207, "total": 110324630}, "ML": {"alive": 219559, "dead": 1906611, "doa": 104171423, "total": 106297593}, "GMS": {"alive": 272688, "dead": 613624, "doa": 5988136, "total": 6874448}}, "IPV": {"QMM": {"alive": 534750, "dead": 2850628, "doa": 4857472, "total": 8242850}, "Google": {"alive": 2951306, "dead": 16629414, "doa": 38059767, "total": 57640487}, "Ligra": {"alive": 510751, "dead": 14413884, "doa": 20547707, "total": 35472342}, "GAP": {"alive": 1415119, "dead": 6268235, "doa": 14146119, "total": 21829473}, "DPC3": {"alive": 1103132, "dead": 33231526, "doa": 73215338, "total": 107549996}, "ML": {"alive": 136913, "dead": 2975735, "doa": 103407558, "total": 106520206}, "GMS": {"alive": 182778, "dead": 538147, "doa": 5869961, "total": 6590886}}}

SUITES   = ["DPC3", "GAP", "GMS", "Google", "Ligra", "ML", "QMM"]
POLICIES = ["LRU", "SRRIP", "IPV"]

def pct(raw, suite):
    r = raw[suite]
    t = r["total"]
    if t == 0:
        return 0.0, 0.0, 0.0
    return 100.0 * r["doa"] / t, 100.0 * r["dead"] / t, 100.0 * r["alive"] / t

data = {}
for pol in POLICIES:
    data[pol] = {"doa": [], "dead": [], "alive": []}
    for suite in SUITES:
        d, md, ma = pct(RAW[pol], suite)
        data[pol]["doa"].append(d)
        data[pol]["dead"].append(md)
        data[pol]["alive"].append(ma)

# Print table
print("\n{:<8} {:<7} {:>6} {:>6} {:>6}".format("Suite", "Policy", "DoA", "MD", "MA"))
print("-" * 38)
for suite in SUITES:
    for pol in POLICIES:
        i = SUITES.index(suite)
        print("{:<8} {:<7} {:>5.1f}% {:>5.1f}% {:>5.1f}%".format(
            suite, pol,
            data[pol]["doa"][i], data[pol]["dead"][i], data[pol]["alive"][i]))
    print()

# Colors
C_DOA   = "#4C6A8A"  # slate blue
C_DEAD  = "#6A9E8A"  # muted teal
C_ALIVE = "#C9A84C"  # warm gold

N   = len(SUITES)
NP  = len(POLICIES)
slot = 0.23         # spacing allocated per bar (controls group width)
w    = 0.19         # drawn bar width — narrower than slot gives inter-bar gap
gap  = 0.06         # extra gap between suite groups
group_w = NP * slot + gap
x   = np.arange(N) * (group_w + 0.2)

EDGE = dict(edgecolor="white", linewidth=0.6)  # thin white border between segments

MIN_LABEL_PCT = 4.0

fig, ax = plt.subplots(figsize=(13, 4.5))

handles = {}
for pi, pol_name in enumerate(POLICIES):
    offsets = x + pi * slot - (NP - 1) * slot / 2
    doa_a   = np.array(data[pol_name]["doa"])
    dead_a  = np.array(data[pol_name]["dead"])
    alive_a = np.array(data[pol_name]["alive"])

    b_doa   = ax.bar(offsets, doa_a,   width=w, color=C_DOA,   label="DoA"         if pi == 0 else "_", **EDGE)
    b_dead  = ax.bar(offsets, dead_a,  width=w, color=C_DEAD,  label="Mostly-dead" if pi == 0 else "_", bottom=doa_a,            **EDGE)
    b_alive = ax.bar(offsets, alive_a, width=w, color=C_ALIVE, label="Mostly-alive" if pi == 0 else "_", bottom=doa_a + dead_a,  **EDGE)

    if pi == 0:
        handles["DoA"]          = b_doa
        handles["Mostly-dead"]  = b_dead
        handles["Mostly-alive"] = b_alive

    # Policy label below each group of bars
    for i, off in enumerate(offsets):
        ax.text(off, -2.5, pol_name, ha="center", va="top", fontsize=6.5,
                color="black", rotation=0)

    # Percentage labels inside segments
    for i, off in enumerate(offsets):
        if doa_a[i] >= MIN_LABEL_PCT:
            ax.text(off, doa_a[i] / 2, f"{doa_a[i]:.0f}%",
                    ha="center", va="center", fontsize=7.5, color="white", fontweight="bold")
        if dead_a[i] >= MIN_LABEL_PCT:
            ax.text(off, doa_a[i] + dead_a[i] / 2, f"{dead_a[i]:.0f}%",
                    ha="center", va="center", fontsize=7.5, color="white", fontweight="bold")
        if alive_a[i] >= MIN_LABEL_PCT:
            ax.text(off, doa_a[i] + dead_a[i] + alive_a[i] / 2, f"{alive_a[i]:.0f}%",
                    ha="center", va="center", fontsize=7.5, color="white", fontweight="bold")

# Suite labels centred on the group of 3 bars
group_centres = x
ax.set_xticks(group_centres)
ax.set_xticklabels(SUITES, fontsize=9)
ax.tick_params(axis="x", length=0, pad=18)

ax.set_ylabel("Fraction of LLC evictions (%)")
ax.set_ylim(-7, 105)
ax.yaxis.grid(True, linestyle="--", alpha=0.4)
ax.set_axisbelow(True)
ax.legend(loc="lower left", bbox_to_anchor=(0, 0.09), fontsize=9)
ax.set_title(
    "LLC liveness breakdown by replacement policy\n"
    "(DoA = 0 hits; mostly-dead = last hit in first half of residency; "
    "mostly-alive = last hit in second half)",
    fontsize=9,
)

fig.tight_layout()
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print(f"\nSaved {OUT}")
