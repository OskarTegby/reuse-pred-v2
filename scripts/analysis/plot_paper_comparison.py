#!/usr/bin/env python3
"""LRU-Live replacement guidance alone (no bypass): per-PC vs per-address
history-table indexing, per-address shown at unbounded and 4,096-entry (4K)
bounded capacity. Geomean IPC speedup vs LRU, per suite.
Output: results/plots/paper_comparison.png

Values are reconstructed via pixel calibration from the only surviving copy
of this figure (a git stash that predates this script) -- the run that
produced them was never committed, so there is no raw data to recompute
from. Suites with no visible 4K bar in that image are recorded as 0.0.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SUITES   = ["GAP", "Ligra", "ML", "QMM", "Google", "SPEC", "GMS"]
PERPC    = [6.12, 4.95, 2.83, 2.53, 2.34, 0.40, -0.63]        # per-PC, unbounded
PADDR    = [1.41, -0.03, 0.80, 0.76, -0.37, 0.73, -0.19]      # per-address, unbounded
PADDR_4K = [-0.07, 0.0, 0.0, 0.17, 0.0, 0.0, -0.02]           # per-address, 4096-entry cap

x = np.arange(len(SUITES)); w = 0.27
fig, ax = plt.subplots(figsize=(9, 4.6))
ax.bar(x - w, PERPC, w, label="per-PC (unbounded)", color="#1f77b4", edgecolor="black", linewidth=0.4)
ax.bar(x,     PADDR, w, label="per-address (unbounded)", color="#ff7f0e", edgecolor="black", linewidth=0.4)
ax.bar(x + w, PADDR_4K, w, label="per-address (4K)", color="#e47273", edgecolor="black", linewidth=0.4)
ax.axhline(0, color="black", linewidth=0.6)
ax.set_xticks(x); ax.set_xticklabels(SUITES)
ax.set_ylabel("Geomean speedup vs LRU (%)")
ax.set_title("Per-PC vs. per-address indexing (LRU-Live, replacement only): unbounded vs. 4K")
ax.legend(frameon=False, fontsize=9, loc="upper right")
ax.grid(axis="y", linestyle=":", alpha=0.4)
fig.tight_layout()
out = "results/plots/paper_comparison.png"
fig.savefig(out, dpi=150)
print("wrote", out)
