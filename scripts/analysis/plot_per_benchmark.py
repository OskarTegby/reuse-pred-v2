#!/usr/bin/env python3
"""Per-benchmark diversity: a curated, representative spread of individual traces
showing SRRIP-Live replacement guidance and +LLC bypass (theta=16) vs SRRIP. Each
bar is one benchmark: SPEC (DPC3) simpoints are SimPoint-weighted into a single
per-benchmark value; other suites carry one trace per benchmark. Picks benchmarks
across the full effect range (big-win -> flat -> slight-loss), capped per
benchmark family and per suite so no single category dominates.
Input: /tmp/perbench.json   Output: results/plots/per_benchmark.png
"""
import json, re, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

recs = [r for r in json.load(open("/tmp/perbench.json")) if "byp" in r and "repl" in r]

def family(r):
    t = r["trace"]
    m = re.match(r"\d+\.([A-Za-z0-9]+)", t)          # SPEC: 605.mcf_s-.. -> mcf
    if m: return m.group(1)
    return r["suite"] + ":" + re.split(r"[._-]", t)[0][:12]

def shortlabel(r):
    t = r["trace"]
    m = re.match(r"\d+\.([A-Za-z0-9]+)", t)
    if m: return m.group(1)
    return re.split(r"[._.]", t)[0][:10]

recs.sort(key=lambda r: -r["byp"])
# stratified pick across the sorted (by bypass) range, capped per family/suite
N_TARGET = 15
fam_cap, suite_cap = 2, 3
famc, suitec, picked = {}, {}, []
# walk the sorted list at ~even strides to span the range
idxs = sorted(set(int(round(i)) for i in np.linspace(0, len(recs)-1, N_TARGET*3)))
for i in idxs:
    if len(picked) >= N_TARGET: break
    r = recs[i]; f = family(r); s = r["suite"]
    if famc.get(f,0) >= fam_cap or suitec.get(s,0) >= suite_cap: continue
    if r in picked: continue
    picked.append(r); famc[f]=famc.get(f,0)+1; suitec[s]=suitec.get(s,0)+1
picked.sort(key=lambda r: -r["byp"])

labels = ["%s\n(%s)" % (shortlabel(r), r["suite"]) for r in picked]
repl = [r["repl"] for r in picked]; byp = [r["byp"] for r in picked]
x = np.arange(len(picked)); w = 0.4
fig, ax = plt.subplots(figsize=(12, 4.8))
ax.bar(x - w/2, repl, w, label="replacement guidance", color="#9ecae1", edgecolor="black", linewidth=0.4)
ax.bar(x + w/2, byp,  w, label="+ LLC bypass ($\\theta$=16)", color="#08519c", edgecolor="black", linewidth=0.4)
ax.axhline(0, color="black", linewidth=0.6)
ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=7, rotation=40, ha="right")
ax.set_ylabel("IPC speedup vs.\\ SRRIP (%)")
ax.set_title("Per-benchmark spread (SimPoint-weighted; curated, $\\leq$2/family, "
             "$\\leq$3/suite): liveness gains concentrate in specific workloads")
ax.legend(frameon=False, fontsize=9)
ax.grid(axis="y", linestyle=":", alpha=0.4)
fig.tight_layout()
out = "results/plots/per_benchmark.png"
fig.savefig(out, dpi=150)
print("wrote", out)
print("selected:")
for r in picked: print("  %-7s %-22s repl=%+5.1f  byp=%+6.1f" % (r["suite"], r["trace"][:22], r["repl"], r["byp"]))
