#!/usr/bin/env python3
"""Paper comparison with prior work: per-PC (ours) vs per-address (same algorithm)
vs Mazumdar et al., geomean IPC speedup vs SRRIP at theta_bypass=16, per suite.
Output: results/plots/paper_comparison.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SUITES = ["QMM", "DPC3", "GAP", "GMS", "Ligra", "ML"]
# SimPoint-weighted geomeans (DPC3=SPEC weighted; other suites equal-weight)
PERPC  = [1.62, 17.27, 4.94, 1.63, 34.88, 11.70]
PADDR  = [-0.74, 3.04, -2.94, 0.36, 5.46, 5.58]
MAZ    = [2.03, 0.28, 0.13, 0.32, None, None]   # Ligra/ML pending

x = np.arange(len(SUITES)); w = 0.27
fig, ax = plt.subplots(figsize=(9, 4.6))
ax.bar(x - w, PERPC, w, label="per-PC (ours)", color="#08519c", edgecolor="black", linewidth=0.4)
ax.bar(x,     PADDR, w, label="per-address", color="#fdae6b", edgecolor="black", linewidth=0.4)
maz_vals = [v if v is not None else 0 for v in MAZ]
ax.bar(x + w, maz_vals, w, label="Mazumdar et al.", color="#969696", edgecolor="black", linewidth=0.4)
for xi, v in zip(x, MAZ):
    if v is None:
        ax.annotate("n/a", (xi + w, 0.3), ha="center", va="bottom", fontsize=6, color="grey", rotation=90)
ax.axhline(0, color="black", linewidth=0.6)
ax.set_xticks(x); ax.set_xticklabels(SUITES)
ax.set_ylabel("Geomean IPC speedup vs.\\ SRRIP (%)")
ax.set_title("Comparison with prior work ($\\theta$=16): per-PC vs.\\ per-address vs.\\ Mazumdar et al.")
ax.legend(frameon=False, fontsize=9, loc="upper left")
ax.grid(axis="y", linestyle=":", alpha=0.4)
fig.tight_layout()
out = "results/plots/paper_comparison.png"
fig.savefig(out, dpi=150)
print("wrote", out)
