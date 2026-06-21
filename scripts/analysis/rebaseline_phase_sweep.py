#!/usr/bin/env python3
"""Adjusted-baseline table for the THD_DOA sweep finished Jun 17-18 (phase2+phase3).

Baseline: allsuites_thd_phase1/srrip/{suite}/{trace}
Sweep:    phase2 doa{2,4,6,8,16}, phase3 doa{20,25,30}  (scoring_mode=5, thd_dead=8)
Speedup = geomean(ipc_thd / ipc_srrip) over trace intersection, per suite.
DPC3 SimPoint-weighted; others flat geomean.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "analysis"))
from spec_weights import benchmark_weighted_geomean_pct, geomean_pct  # noqa: E402

TSV = ROOT / "results" / "thd_phase_ipc.tsv"
P1 = "allsuites_thd_phase1_20260617_0020"
P2 = "allsuites_thd_phase2_20260617_1651"
P3 = "allsuites_thd_phase3_20260618_1245"
SUITES = ["dpc3", "gap", "gms", "google", "ligra", "ml", "qmm"]
WEIGHTED = {"dpc3"}
# threshold -> path prefix
THD = {2: f"{P2}/llc/srrip_live/doa2", 4: f"{P2}/llc/srrip_live/doa4",
       6: f"{P2}/llc/srrip_live/doa6", 8: f"{P2}/llc/srrip_live/doa8",
       16: f"{P2}/llc/srrip_live/doa16",
       20: f"{P3}/llc/srrip_live/doa20", 25: f"{P3}/llc/srrip_live/doa25",
       30: f"{P3}/llc/srrip_live/doa30"}
THRESHOLDS = sorted(THD)


def load():
    """path -> ipc."""
    d = {}
    for line in TSV.read_text().splitlines():
        path, ipc = line.split("\t")
        d[path] = float(ipc)
    return d


def by_trace(data, prefix, suite):
    """trace -> ipc for entries under prefix/suite/."""
    pre = f"{prefix}/{suite}/"
    out = {}
    for path, ipc in data.items():
        if path.startswith(pre):
            trace = path[len(pre):].split("/")[0]
            out[trace] = ipc
    return out


def main():
    data = load()
    rows = []
    for suite in SUITES:
        base = by_trace(data, f"{P1}/srrip", suite)
        cells = []
        ns = []
        for thd in THRESHOLDS:
            run = by_trace(data, THD[thd], suite)
            common = sorted(set(run) & set(base))
            if not common:
                cells.append("--")
                continue
            ratios = {t: run[t] / base[t] for t in common if base[t] > 0}
            ns.append(len(common))
            if suite in WEIGHTED:
                spd = benchmark_weighted_geomean_pct(ratios)
            else:
                spd = geomean_pct([(r - 1) * 100 for r in ratios.values()])
            cells.append(f"{spd:+.2f}%")
        n = max(ns) if ns else 0
        rows.append((suite, n, cells))

    hdr = "Suite     n    " + "  ".join(f"doa{t:<3}" for t in THRESHOLDS)
    print(hdr)
    print("-" * len(hdr))
    for suite, n, cells in rows:
        print(f"{suite:<8} {n:<4} " + "  ".join(f"{c:>8}" for c in cells))


if __name__ == "__main__":
    main()
