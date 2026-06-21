#!/usr/bin/env python3
"""Per-suite justification that PCs carry a strong per-PC liveness signal.

For each suite (LLC, all traces pooled), PCs are sorted by their DoA fraction and
the x-axis is weighted by eviction count (cumulative share of LLC evictions). The
stacked area shows each region's DoA/MD/MA composition. A wide DoA-dominated band
on the left = a large share of evictions comes from PCs that are almost always
dead-on-arrival, i.e. per-PC prediction is meaningful.

Input:  /tmp/pc_aggr.json  (produced on the cluster from liveness_char_20260608_0006)
Output: results/plots/pc_liveness_profile.png
"""
import json, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

data = json.load(open("/tmp/pc_aggr.json"))
area, buckets = data["area"], data["buckets"]
SUITES = [s for s in ["DPC3","GAP","GMS","Ligra","ML","QMM"] if s.lower() in area]

fig, axes = plt.subplots(2, 3, figsize=(12, 6), sharex=True, sharey=True)
C = {"doa": "#d62728", "md": "#ff7f0e", "ma": "#2ca02c"}
for ax, suite in zip(axes.flat, SUITES):
    s = suite.lower()
    a = np.array(area[s])              # (NBIN, 3) -> doa, md, ma
    n = a.shape[0]
    x = (np.arange(n) + 0.5) / n       # cumulative eviction share
    doa, md, ma = a[:, 0], a[:, 1], a[:, 2]
    ax.fill_between(x, 0, doa, color=C["doa"], label="DoA")
    ax.fill_between(x, doa, doa + md, color=C["md"], label="mostly-dead")
    ax.fill_between(x, doa + md, doa + md + ma, color=C["ma"], label="mostly-alive")
    b = buckets[s]
    ax.set_title("%s  (%.0f%% of evicts from $\\geq$80%%-DoA PCs)" % (suite, 100*b["doa"]),
                 fontsize=9)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.grid(False)
for ax in axes[1, :]:
    ax.set_xlabel("cumulative share of LLC evictions\n(PCs sorted by DoA fraction)", fontsize=8)
for ax in axes[:, 0]:
    ax.set_ylabel("eviction composition", fontsize=9)
axes[0, 0].legend(loc="lower left", fontsize=7, framealpha=0.9)
fig.suptitle("Per-PC liveness signal: a large share of LLC evictions comes from "
             "PCs that are almost entirely DoA", fontsize=11)
fig.tight_layout(rect=[0, 0, 1, 0.96])
out = "results/plots/pc_liveness_profile.png"
fig.savefig(out, dpi=150)
print("wrote", out)
