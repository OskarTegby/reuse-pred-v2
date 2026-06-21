#!/usr/bin/env python3
"""Paper results: SRRIP-Live replacement guidance, and +LLC bypass at the best
overall threshold (theta_bypass=16), geomean IPC speedup vs SRRIP, per suite.
Output: results/plots/paper_performance.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SUITES = ["DPC3", "GAP", "GMS", "Ligra", "ML", "QMM", "All"]
# SimPoint-weighted geomeans (DPC3=SPEC weighted; other suites equal-weight)
REPL   = [2.27, 2.05, 1.28, 1.53, 8.80, 0.99, 3.17]    # repl guidance only
BYP    = [17.27, 4.94, 1.63, 34.88, 11.70, 1.62, 9.78] # + bypass, theta=16

x = np.arange(len(SUITES)); w = 0.4
fig, ax = plt.subplots(figsize=(8.5, 4.4))
b1 = ax.bar(x - w/2, REPL, w, label="replacement guidance", color="#9ecae1", edgecolor="black", linewidth=0.5)
b2 = ax.bar(x + w/2, BYP,  w, label="+ LLC bypass ($\\theta$=16)", color="#08519c", edgecolor="black", linewidth=0.5)
for bars in (b1, b2):
    for b in bars:
        ax.annotate("%.1f" % b.get_height(), (b.get_x()+b.get_width()/2, b.get_height()),
                    ha="center", va="bottom", fontsize=7)
ax.axhline(0, color="black", linewidth=0.6)
ax.axvline(len(SUITES)-1.5, color="grey", linestyle=":", linewidth=0.8)  # separate "All"
ax.set_xticks(x); ax.set_xticklabels(SUITES)
ax.set_ylabel("Geomean IPC speedup vs.\\ SRRIP (%)")
ax.set_title("SRRIP-Live: replacement guidance and +LLC bypass ($\\theta$=16)")
ax.legend(frameon=False, fontsize=9, loc="upper center")
ax.grid(axis="y", linestyle=":", alpha=0.4)
fig.tight_layout()
out = "results/plots/paper_performance.png"
fig.savefig(out, dpi=150)
print("wrote", out)
