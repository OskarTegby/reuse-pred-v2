#!/usr/bin/env python3
"""Recompute the OLD threshold sweep against the proper SRRIP baseline.

For each suite, computes geomean speedup of each mid_thd point vs the SRRIP
baseline in bypass_allsuites_20260610_2312/{suite}/srrip, over the intersection
of traces. DPC3 uses SimPoint weighting; other suites flat geomean.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "analysis"))
from spec_weights import benchmark_weighted_geomean_pct, geomean_pct  # noqa: E402

RESULTS = ROOT / "results"
SRRIP_BASE = RESULTS / "bypass_allsuites_20260610_2312"

# suite -> threshold-sweep dir
THD_DIR = {
    "dpc3":  "dpc3_srrip_live_thd_pc_20260513_0055",
    "gap":   "gap_srrip_live_thd_pc_20260520_0059",
    "gms":   "gms_srrip_live_thd_pc_20260520_0128",
    "ligra": "ligra_srrip_live_thd_pc_20260520_0059",
    "ml":    "ml_srrip_live_thd_pc_20260520_0059",
    "qmm":   "qmm_srrip_live_thd_pc_20260513_0056",
}
THRESHOLDS = [1, 2, 4, 8, 16]
WEIGHTED = {"dpc3"}


def read_ipc(champsim_out: Path):
    if not champsim_out.exists():
        return None
    for line in champsim_out.read_text(errors="ignore").splitlines():
        if line.startswith("CPU 0 cumulative IPC:"):
            try:
                return float(line.split()[4])
            except (ValueError, IndexError):
                return None
    return None


def norm(name: str) -> str:
    """Strip trailing .champsim[s]trace suffix so sweep/baseline names match."""
    for suf in (".champsimtrace", ".champsimstrace"):
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


def collect(run_dir: Path):
    """trace -> IPC for every trace subdir holding a champsim.out."""
    out = {}
    if not run_dir.exists():
        return out
    for d in sorted(run_dir.iterdir()):
        if d.is_dir():
            ipc = read_ipc(d / "champsim.out")
            if ipc is not None:
                out[norm(d.name)] = ipc
    return out


def geomean_speedup(suite, ratios_by_wl):
    if suite in WEIGHTED:
        return benchmark_weighted_geomean_pct(ratios_by_wl)
    return geomean_pct([(r - 1) * 100 for r in ratios_by_wl.values()])


def main():
    rows = []
    for suite, thd_dirname in THD_DIR.items():
        base = collect(SRRIP_BASE / suite / "srrip")
        if not base:
            rows.append((suite, 0, ["no SRRIP baseline"]))
            continue
        cells = []
        n_used = None
        for thd in THRESHOLDS:
            run = collect(RESULTS / thd_dirname / f"srrip_live_thd{thd}")
            common = sorted(set(run) & set(base))
            if not common:
                cells.append("    --")
                continue
            ratios = {t: run[t] / base[t] for t in common if base[t] > 0}
            n_used = len(common)
            spd = geomean_speedup(suite, ratios)
            cells.append(f"{spd:+6.2f}%")
        rows.append((suite, n_used or 0, cells))

    hdr = "Suite     n    " + "  ".join(f"thd{t:<3}" for t in THRESHOLDS)
    print(hdr)
    print("-" * len(hdr))
    for suite, n, cells in rows:
        print(f"{suite:<8} {n:<4} " + "  ".join(f"{c:>7}" for c in cells))


if __name__ == "__main__":
    main()
