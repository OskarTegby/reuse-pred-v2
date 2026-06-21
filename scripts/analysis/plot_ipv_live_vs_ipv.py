#!/usr/bin/env python3
"""IPV-Live vs plain IPV (the IPV liveness contribution), per suite, current config,
mode-5, theta=6. Positive = liveness helps IPV; negative = it hurts.
Data: ipv_live_vs_base_* (ipv_live / ipv_base). Output: results/plots/ipv_live_vs_ipv.png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SUITES = ["DPC3", "GAP", "GMS", "Ligra", "ML", "QMM"]
IPV    = [-0.55, 6.26, -1.29, -3.02, -9.77, 1.75]   # IPV-Live / IPV (%)

colors = ["#2ca02c" if v >= 0 else "#d62728" for v in IPV]
fig, ax = plt.subplots(figsize=(7.5, 4.2))
bars = ax.bar(SUITES, IPV, color=colors, edgecolor="black", linewidth=0.5)
for b, v in zip(bars, IPV):
    ax.annotate("%+.2f%%" % v,
                (b.get_x() + b.get_width()/2, v),
                ha="center", va="bottom" if v >= 0 else "top", fontsize=8)
ax.axhline(0, color="black", linewidth=0.8)
ax.set_ylabel("IPC speedup of IPV-Live over plain IPV (%)")
ax.set_title("IPV-Live vs. its own base (IPV): liveness guidance is fragile for IPV\n"
             "(current config, mode-5, $\\theta$=6, LLC-only)")
ax.grid(axis="y", linestyle=":", alpha=0.4)
ax.margins(y=0.18)
fig.tight_layout()
out = "results/plots/ipv_live_vs_ipv.png"
fig.savefig(out, dpi=150)
print("wrote", out)
