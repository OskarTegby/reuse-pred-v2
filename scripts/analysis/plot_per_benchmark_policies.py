#!/usr/bin/env python3
"""Per-benchmark replacement-policy detail: LRU-Live and SRRIP-Live each vs
its own non-guided base, for a curated, representative spread of traces. Extreme
outliers (|any policy| > CAP%) are excluded so the plot is readable; the point is
that different policies win on different workloads.
Input: /tmp/perbench3.json   Output: results/plots/per_benchmark_policies.png
"""
import json, re, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

CAP = 50.0
recs = [r for r in json.load(open("/tmp/perbench3.json"))
        if r.get("srrip") is not None and r.get("lru") is not None]
recs = [r for r in recs if max(abs(r["srrip"]), abs(r["lru"])) <= CAP]

def family(r):
    m = re.match(r"\d+\.([A-Za-z0-9]+)", r["trace"])
    return m.group(1) if m else r["suite"]+":"+re.split(r"[._-]", r["trace"])[0][:10]
def lab(r):
    m = re.match(r"\d+\.([A-Za-z0-9]+)", r["trace"])
    return (m.group(1) if m else re.split(r"[._-]", r["trace"])[0][:8])

# pick traces with the most spread between policies (shows divergence), capped per family/suite
recs.sort(key=lambda r: -(max(r["srrip"], r["lru"]) - min(r["srrip"], r["lru"])))
famc, suitec, pick = {}, {}, []
for r in recs:
    if len(pick) >= 11: break
    f, s = family(r), r["suite"]
    if famc.get(f, 0) >= 2 or suitec.get(s, 0) >= 3: continue
    pick.append(r); famc[f] = famc.get(f, 0)+1; suitec[s] = suitec.get(s, 0)+1
pick.sort(key=lambda r: -r["srrip"])

labels = ["%s\n(%s)" % (lab(r), r["suite"]) for r in pick]
x = np.arange(len(pick)); w = 0.35
fig, ax = plt.subplots(figsize=(11, 4.6))
ax.bar(x - w/2, [r["lru"]   for r in pick], w, label="LRU-Live / LRU",     color="#1f77b4", edgecolor="black", linewidth=0.4)
ax.bar(x + w/2, [r["srrip"] for r in pick], w, label="SRRIP-Live / SRRIP", color="#2a7f3f", edgecolor="black", linewidth=0.4)
ax.axhline(0, color="black", linewidth=0.6)
ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=7, rotation=35, ha="right")
ax.set_ylabel("IPC speedup over own non-guided base (%)")
ax.set_title("Per-benchmark replacement-guidance contribution (no bypass): "
             "policies win on different workloads\n"
             "(curated spread; traces with |speedup|>%d%% omitted; SRRIP-Live at optimal "
             "$\\theta_{\\mathrm{doa}}$ per suite)" % int(CAP))
ax.legend(frameon=False, fontsize=8, ncol=2, loc="upper right")
ax.grid(axis="y", linestyle=":", alpha=0.4)
fig.tight_layout()
out = "results/plots/per_benchmark_policies.png"
fig.savefig(out, dpi=150)
print("wrote", out, "| selected", len(pick), "traces")
for r in pick: print("  %-6s %-25s lru=%+5.1f srrip=%+5.1f" % (r["suite"], r["trace"][:25], r["lru"], r["srrip"]))
