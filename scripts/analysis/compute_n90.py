#!/usr/bin/env python3
"""Compute n90 (number of PCs covering 90% of LLC DoA evictions) per trace,
then min/mean/max per suite -- backs results/paper/main.tex Table 1
(\\label{tab:concentration}).

For each trace's champsim.out, takes the LAST "LLC LIVENESS_CHAR BEGIN/END"
block (LIVENESS_CHAR=1 must have been set for the run), ranks PCs by their
doa= count descending, and finds the smallest prefix whose cumulative DoA
count reaches 90% of the trace's total. A trace with zero LLC DoA evictions
counts as n90=0 and is still included in the suite's min/mean/max.

Requires LIVENESS_CHAR=1 runs (unlike Figure 1, which only needs the
unconditional "LLC LIVENESS EVICTIONS" summary line). See
results/paper/FIGURE_PROVENANCE.md for the suites/directories this points at
and how they were produced.
"""

import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
RESULTS = os.path.join(ROOT, "results")

# Same canonical directories as scripts/analysis/plot_liveness_rates.py,
# minus Google (Table 1 does not include it). See FIGURE_PROVENANCE.md.
SUITES = {
    "GAP":   "livchar_unified_20260616_1249/gap",
    "GMS":   "livchar_unified_20260616_1249/gms",
    "ML":    "livchar_unified_20260616_1249/ml",
    "Ligra": "livchar_unified_20260616_1249/ligra",
    "DPC3":  "livchar_dpc3full_20260616_1251/dpc3",
    "QMM":   "livchar_unified_20260616_1249/qmm",
}

DOA_PAT = re.compile(r"doa=(\d+)")


def n90_for_file(path):
    with open(path, "r", errors="ignore") as f:
        lines = f.readlines()
    begins = [i for i, l in enumerate(lines) if l.startswith("LLC LIVENESS_CHAR BEGIN")]
    ends = [i for i, l in enumerate(lines) if l.startswith("LLC LIVENESS_CHAR END")]
    if not begins or not ends:
        return None
    b, e = begins[-1], ends[-1]
    doas = []
    for l in lines[b + 1:e]:
        m = DOA_PAT.search(l)
        if m:
            v = int(m.group(1))
            if v > 0:
                doas.append(v)
    if not doas:
        return 0
    doas.sort(reverse=True)
    total = sum(doas)
    target = total * 0.9
    cum = 0
    for i, v in enumerate(doas):
        cum += v
        if cum >= target:
            return i + 1
    return len(doas)


def aggregate(suite_dir):
    base = os.path.join(RESULTS, suite_dir)
    vals = []
    for trace_dir in sorted(os.listdir(base)):
        out = os.path.join(base, trace_dir, "champsim.out")
        if not os.path.isfile(out):
            continue
        n = n90_for_file(out)
        if n is not None:
            vals.append(n)
    if not vals:
        return None
    return min(vals), sum(vals) / len(vals), max(vals), len(vals)


if __name__ == "__main__":
    print("%-8s %4s %8s %10s %10s" % ("Suite", "n", "min", "mean", "max"))
    print("-" * 44)
    for name in ["GAP", "GMS", "ML", "Ligra", "DPC3", "QMM"]:
        dirname = SUITES[name]
        agg = aggregate(dirname)
        if agg is None:
            print("%-8s no data (%s)" % (name, dirname))
            continue
        lo, mean, hi, n = agg
        print("%-8s %4d %8d %10.1f %10d" % (name, n, lo, mean, hi))
