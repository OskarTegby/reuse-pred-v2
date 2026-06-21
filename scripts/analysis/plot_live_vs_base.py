#!/usr/bin/env python3
"""Liveness contribution: each guided policy vs its OWN non-guided base
(LRU-Live/LRU, SRRIP-Live/SRRIP) — optimal theta_doa per suite, no bypass.

Sources:
  SRRIP-Live: canonical phase sweep (allsuites_thd_phase{2,3}) at optimal
    theta_doa per suite vs phase1/srrip baseline (champsim_srrip).
    DPC3: theta=25 (95 traces, SimPoint-weighted); GAP: theta=6; GMS: theta=30;
    Ligra: theta=25; ML: theta=16; QMM: theta=16.
  LRU-Live: lru_live_vs_base_20260615_0855 vs baselines/lru at theta=6
    (no threshold sweep available for LRU-Live).
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SUITES = ["DPC3", "GAP", "GMS", "Ligra", "ML", "QMM"]

# vs own non-guided base, % (DPC3 SimPoint-weighted; other suites flat geomean)
# SRRIP-Live at optimal theta_doa per suite from canonical phase sweep (2026-06-20)
SRRIP_LIVE = [1.11, 6.10, 0.27, 0.28, 1.73, 1.70]
# LRU-Live at theta=6 (no sweep; never contaminated)
LRU_LIVE   = [2.99, 3.82, 0.38, 2.95, 2.37, 1.40]

SERIES = [("LRU-Live / LRU",     LRU_LIVE,   "#1f77b4"),
          ("SRRIP-Live / SRRIP", SRRIP_LIVE, "#2a7f3f")]

x = list(range(len(SUITES)))
w = 0.32
fig, ax = plt.subplots(figsize=(9, 4.4))
for i, (label, vals, color) in enumerate(SERIES):
    off = (i - 0.5) * w
    ax.bar([xi + off for xi in x], vals, w,
           label=label, color=color, edgecolor="black", linewidth=0.4)

ax.axhline(0, color="black", linewidth=0.6)
ax.set_xticks(x); ax.set_xticklabels(SUITES)
ax.set_ylabel("Geomean IPC speedup over non-guided base (%)")
ax.set_title("Replacement guidance only: each guided policy vs. its own non-guided base\n"
             "(SRRIP-Live at optimal $\\theta_{\\mathrm{doa}}$ per suite; LRU-Live at $\\theta=6$; no bypass)")
ax.legend(frameon=False, fontsize=8)
ax.grid(axis="y", linestyle=":", alpha=0.4)
fig.tight_layout()
out = "results/plots/live_vs_base.png"
fig.savefig(out, dpi=150)
print("wrote", out)
