#!/usr/bin/env python3
"""How concentrated DoA evictions are across PCs (per suite).

For each trace, PCs are ranked by DoA-eviction count; the curve is the cumulative
share of DoA evictions covered by the top-N PCs, averaged over the suite's traces.
A curve that reaches ~1 at small N means almost all dead-on-arrival traffic comes
from a few PCs -> a tiny per-PC table captures the signal.

Input:  /tmp/pc_conc.json   Output: results/plots/doa_concentration.png
"""
import json, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

d = json.load(open("/tmp/pc_conc.json"))
order = [s for s in ["gap","gms","ml","ligra","dpc3","qmm"] if s in d]
fig, ax = plt.subplots(figsize=(8, 4.6))
for s in order:
    e = d[s]
    ax.plot(e["ranks"], e["mean"], marker="o", ms=3, linewidth=1.6,
            label="%s  (90%% at %d PCs)" % (s.upper(), e["pcs90_median"]))
ax.axhline(0.9, color="grey", linestyle="--", linewidth=0.8)
ax.text(1.1, 0.91, "90% of DoA evictions", fontsize=7, color="grey")
ax.set_xscale("log")
ax.set_xlabel("number of PCs (ranked by DoA-eviction count, log scale)")
ax.set_ylabel("cumulative share of DoA evictions")
ax.set_title("DoA evictions are concentrated in a few PCs\n"
             "(per-trace curves averaged within each suite, LLC)")
ax.set_ylim(0, 1.02); ax.set_xlim(1, 11000)
ax.legend(frameon=False, fontsize=8, loc="lower right")
ax.grid(True, which="both", linestyle=":", alpha=0.4)
fig.tight_layout()
out = "results/plots/doa_concentration.png"
fig.savefig(out, dpi=150)
print("wrote", out)
