#!/usr/bin/env python3
"""Mazumdar -> ours morph ladder: each rung is one change; the gain appears at the
indexing+scoring step (R3->R4). Data: maz_morph_2026061* (vs SRRIP)."""
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

RUNGS = ["R0\nfaithful\nMaz", "R1\n-hash", "R2\nunbounded", "R3\nungated",
         "R4\nper-PC\n+mode5", "R5\nours"]
DATA = {  # vs SRRIP, %
    "DPC3":  [1.3, 1.3, -0.2, 0.2, 22.4, 21.3],
    "Ligra": [2.0, 2.0, -0.2, -1.4, 34.5, 32.5],
    "ML":    [0.0, 0.0, 0.1, 4.5, 11.9, 11.9],
    "GAP":   [1.4, 1.4, 0.1, -3.2, 5.5, 4.2],
    "GMS":   [0.7, 0.7, 0.1, -0.7, 2.1, 2.1],
    "QMM":   [1.8, 1.8, 3.9, -0.3, 1.8, 1.1],
}
x = list(range(len(RUNGS)))
fig, ax = plt.subplots(figsize=(9, 5))
for suite, ys in DATA.items():
    ax.plot(x, ys, marker="o", linewidth=1.8, label=suite)
ax.axhline(0, color="black", linewidth=0.6)
ax.axvspan(3, 4, color="orange", alpha=0.10)
ax.text(3.5, ax.get_ylim()[1]*0.5, "indexing + scoring\n(the jump)",
        ha="center", va="center", fontsize=8, color="darkorange")
ax.set_xticks(x); ax.set_xticklabels(RUNGS, fontsize=8)
ax.set_ylabel("Geomean IPC speedup vs SRRIP (%)")
ax.set_title("Morph ladder: Mazumdar's predictor -> ours, one change per rung")
ax.legend(frameon=False, ncol=3, fontsize=9)
ax.grid(axis="y", linestyle=":", alpha=0.4)
fig.tight_layout()
out = "results/plots/morph_ladder.png"
fig.savefig(out, dpi=150)
print("wrote", out)
