#!/usr/bin/env python3
"""
Plot LLC liveness breakdown (DoA / Alive) for LRU, SRRIP, and IPV baseline
policies, grouped by benchmark suite.

Pools the "LLC DOA: <n> / <evictions>" line across all traces in a suite
(rc_sweep_20260720_1620, `base` condition, Redwood Cove config), then plots
fractions as grouped stacked bars.

RAW below was extracted on the cluster via a small remote parser (regex over
`LLC DOA: (\\d+) / (\\d+)`, summed per suite/policy before dividing) -- see
results/paper/FIGURE_PROVENANCE.md for the equivalent pre-Redwood-Cove
methodology this supersedes.

Output: results/plots/liveness_per_policy.png
"""

import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
OUT = os.path.join(ROOT, "results", "plots", "liveness_per_policy.png")

# Extracted from results/rc_sweep_20260720_1620/{policy}/base/{suite}/*/champsim.out
RAW = {
    "LRU": {
        "GAP": {"doa": 14818896, "evictions": 18343811},
        "GMS": {"doa": 5697924, "evictions": 6157774},
        "Ligra": {"doa": 32480441, "evictions": 33900180},
        "ML": {"doa": 105129607, "evictions": 105449283},
        "Google": {"doa": 46979824, "evictions": 52047269},
        "QMM": {"doa": 5149507, "evictions": 5616536},
        "SPEC": {"doa": 88477994, "evictions": 91457644},
    },
    "SRRIP": {
        "GAP": {"doa": 15463467, "evictions": 17110534},
        "GMS": {"doa": 5621745, "evictions": 5819441},
        "Ligra": {"doa": 32834794, "evictions": 33697004},
        "ML": {"doa": 105172380, "evictions": 105467350},
        "Google": {"doa": 46968677, "evictions": 49938590},
        "QMM": {"doa": 5178182, "evictions": 5284974},
        "SPEC": {"doa": 88787301, "evictions": 90182401},
    },
    "IPV": {
        "GAP": {"doa": 16905674, "evictions": 19679489},
        "GMS": {"doa": 5741242, "evictions": 6079238},
        "Ligra": {"doa": 45741129, "evictions": 46836607},
        "ML": {"doa": 104588202, "evictions": 105261467},
        "Google": {"doa": 54728835, "evictions": 57280479},
        "QMM": {"doa": 5359041, "evictions": 6057460},
        "SPEC": {"doa": 114590070, "evictions": 116958779},
    },
}

SUITES = ["SPEC", "GAP", "GMS", "Google", "Ligra", "ML", "QMM"]
POLICIES = ["LRU", "SRRIP", "IPV"]


def pct(raw, suite):
    r = raw.get(suite)
    if r is None or r["evictions"] == 0:
        return None
    d = 100.0 * r["doa"] / r["evictions"]
    return d, 100.0 - d


data = {}
for pol in POLICIES:
    data[pol] = {"doa": [], "alive": []}
    for suite in SUITES:
        p = pct(RAW[pol], suite)
        if p is None:
            data[pol]["doa"].append(0.0)
            data[pol]["alive"].append(0.0)
        else:
            data[pol]["doa"].append(p[0])
            data[pol]["alive"].append(p[1])

print("\n{:<8} {:<7} {:>6} {:>6}".format("Suite", "Policy", "DoA", "Alive"))
print("-" * 30)
for suite in SUITES:
    i = SUITES.index(suite)
    for pol in POLICIES:
        if RAW[pol].get(suite) is None:
            print("{:<8} {:<7} {:>6}".format(suite, pol, "--"))
            continue
        print("{:<8} {:<7} {:>5.1f}% {:>5.1f}%".format(
            suite, pol, data[pol]["doa"][i], data[pol]["alive"][i]))
    print()

C_DOA = "#4C6A8A"    # slate blue
C_ALIVE = "#C9A84C"  # warm gold

N = len(SUITES)
NP = len(POLICIES)
slot = 0.23
w = 0.19
gap = 0.06
group_w = NP * slot + gap
x = np.arange(N) * (group_w + 0.2)

EDGE = dict(edgecolor="white", linewidth=0.6)
MIN_LABEL_PCT = 4.0

fig, ax = plt.subplots(figsize=(13, 4.5))

for pi, pol_name in enumerate(POLICIES):
    offsets = x + pi * slot - (NP - 1) * slot / 2
    doa_a = np.array(data[pol_name]["doa"])
    alive_a = np.array(data[pol_name]["alive"])

    ax.bar(offsets, doa_a, width=w, color=C_DOA, label="DoA" if pi == 0 else "_", **EDGE)
    ax.bar(offsets, alive_a, width=w, color=C_ALIVE, label="Alive" if pi == 0 else "_",
           bottom=doa_a, **EDGE)

    for i, off in enumerate(offsets):
        ax.text(off, -2.5, pol_name, ha="center", va="top", fontsize=6.5, color="black")

    for i, off in enumerate(offsets):
        if RAW[pol_name].get(SUITES[i]) is None:
            ax.text(off, 2, "n/a", ha="center", va="bottom", fontsize=7, color="gray", rotation=90)
            continue
        if doa_a[i] >= MIN_LABEL_PCT:
            ax.text(off, doa_a[i] / 2, "{:.0f}%".format(doa_a[i]),
                    ha="center", va="center", fontsize=7.5, color="white", fontweight="bold")
        if alive_a[i] >= MIN_LABEL_PCT:
            ax.text(off, doa_a[i] + alive_a[i] / 2, "{:.0f}%".format(alive_a[i]),
                    ha="center", va="center", fontsize=7.5, color="white", fontweight="bold")

ax.set_xticks(x)
ax.set_xticklabels(SUITES, fontsize=9)
ax.tick_params(axis="x", length=0, pad=18)

ax.set_ylabel("Fraction of LLC evictions (%)")
ax.set_ylim(-7, 105)
ax.yaxis.grid(True, linestyle="--", alpha=0.4)
ax.set_axisbelow(True)
ax.legend(loc="lower left", bbox_to_anchor=(0, 0.09), fontsize=9)
ax.set_title(
    "LLC liveness breakdown by replacement policy\n"
    "(DoA = 0 hits during residency; alive = at least 1 hit)",
    fontsize=9,
)

fig.tight_layout()
fig.savefig(OUT, dpi=150, bbox_inches="tight")
print("\nSaved {}".format(OUT))
