"""
champsim_utils.py — shared utilities for parsing ChampSim output files.

Exports
-------
parse_ipc(path) -> float | None
    Extract cumulative IPC from a champsim.out file.

parse_stats(path) -> (ipc, stlb_mpki, llc_mpki)
    Extract IPC and MPKI metrics from a champsim.out file.

geomean_speedup(exp_dir, baseline_dir) -> float
    Simpoint-weighted geomean IPC speedup (%) vs a baseline directory.

find_test_dir(suite, study) -> str
    Return the most recent results/{suite}_{study}_*_test directory.
"""

import glob
import os
import re
import sys
from pathlib import Path

from spec_weights import benchmark_weighted_geomean_pct


def parse_ipc(path) -> "float | None":
    """Extract cumulative IPC from a champsim.out file."""
    try:
        in_roi = False
        for line in Path(path).read_text(errors="replace").splitlines():
            if "Region of Interest Statistics" in line:
                in_roi = True
            if in_roi and "cumulative IPC:" in line:
                m = re.search(r"cumulative IPC:\s+([0-9.]+)", line)
                if m:
                    return float(m.group(1))
    except OSError:
        pass
    return None


def parse_stats(path) -> "tuple[float | None, float | None, float | None]":
    """Return (ipc, stlb_mpki, llc_mpki) from a champsim.out file."""
    in_roi = False
    ipc = stlb_miss = llc_miss = instrs = None
    try:
        for line in Path(path).read_text(errors="replace").splitlines():
            if "Region of Interest Statistics" in line:
                in_roi = True
            if not in_roi:
                continue
            if ipc is None and "cumulative IPC:" in line:
                m = re.search(r"cumulative IPC:\s+([0-9.]+)\s+instructions:\s+(\d+)", line)
                if m:
                    ipc    = float(m.group(1))
                    instrs = int(m.group(2))
            if stlb_miss is None and re.match(r"cpu0_STLB TOTAL\s+ACCESS:", line):
                m = re.search(r"MISS:\s+(\d+)", line)
                if m:
                    stlb_miss = int(m.group(1))
            if llc_miss is None and re.match(r"LLC TOTAL\s+ACCESS:", line):
                m = re.search(r"MISS:\s+(\d+)", line)
                if m:
                    llc_miss = int(m.group(1))
    except OSError:
        pass
    stlb_mpki = stlb_miss / (instrs / 1000) if (stlb_miss is not None and instrs) else None
    llc_mpki  = llc_miss  / (instrs / 1000) if (llc_miss  is not None and instrs) else None
    return ipc, stlb_mpki, llc_mpki


def geomean_speedup(exp_dir, baseline_dir) -> float:
    """Simpoint-weighted geomean IPC speedup (%) vs a baseline directory."""
    ratios: dict = {}
    for trace in os.listdir(exp_dir):
        ipc_exp  = parse_ipc(os.path.join(exp_dir,      trace, "champsim.out"))
        ipc_base = parse_ipc(os.path.join(baseline_dir, trace, "champsim.out"))
        if ipc_exp is not None and ipc_base is not None and ipc_base > 0:
            ratios[trace] = ipc_exp / ipc_base
    if not ratios:
        return float("nan")
    return benchmark_weighted_geomean_pct(ratios)


def find_test_dir(suite: str, study: str) -> str:
    """Return the most recent results/{suite}_{study}_*_test directory."""
    pattern = os.path.join("results", f"{suite}_{study}_*_test")
    matches = sorted(glob.glob(pattern))
    if not matches:
        print(f"No _test results found matching {pattern}", file=sys.stderr)
        sys.exit(1)
    return matches[-1]
