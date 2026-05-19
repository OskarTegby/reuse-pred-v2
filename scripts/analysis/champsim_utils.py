"""
champsim_utils.py — shared utilities for parsing ChampSim output files.

Exports
-------
parse_ipc(path) -> float | None
    Extract cumulative IPC from a champsim.out file.

parse_stats(path) -> (ipc, stlb_mpki, llc_mpki)
    Extract IPC and MPKI metrics from a champsim.out file.

geomean(vals) -> float | None
    Flat geometric mean; ignores None and non-positive values.

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

import numpy as np

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


def parse_bypass_stats(path) -> dict:
    """Parse bypass and queue stats from a champsim.out file.

    Returns a dict with keys:
      stlb_bypasses, llc_bypasses,
      st_lookups, st_hits,
      pfq_probes, pfq_hits,
      stlb_miss, llc_miss, instrs
    Missing values are None.
    """
    result = {k: None for k in (
        "stlb_bypasses", "llc_bypasses",
        "st_lookups", "st_hits",
        "pfq_probes", "pfq_hits",
        "stlb_miss", "llc_miss", "instrs",
    )}
    try:
        in_roi = False
        for line in Path(path).read_text(errors="replace").splitlines():
            if "Region of Interest Statistics" in line:
                in_roi = True
            if not in_roi:
                continue
            if result["instrs"] is None and "cumulative IPC:" in line:
                m = re.search(r"instructions:\s+(\d+)", line)
                if m:
                    result["instrs"] = int(m.group(1))
            m = re.fullmatch(r"cpu0_STLB BYPASSES:\s+(\d+)", line.strip())
            if m:
                result["stlb_bypasses"] = int(m.group(1))
            m = re.fullmatch(r"LLC BYPASSES:\s+(\d+)", line.strip())
            if m:
                result["llc_bypasses"] = int(m.group(1))
            m = re.search(r"SHADOW TABLE LOOKUPS:\s+(\d+)\s+HITS:\s+(\d+)", line)
            if m:
                result["st_lookups"] = int(m.group(1))
                result["st_hits"]    = int(m.group(2))
            m = re.search(r"PFQ PROBES:\s+(\d+)\s+HITS:\s+(\d+)", line)
            if m:
                result["pfq_probes"] = int(m.group(1))
                result["pfq_hits"]   = int(m.group(2))
            if result["stlb_miss"] is None and re.match(r"cpu0_STLB TOTAL\s+ACCESS:", line):
                m = re.search(r"MISS:\s+(\d+)", line)
                if m:
                    result["stlb_miss"] = int(m.group(1))
            if result["llc_miss"] is None and re.match(r"LLC TOTAL\s+ACCESS:", line):
                m = re.search(r"MISS:\s+(\d+)", line)
                if m:
                    result["llc_miss"] = int(m.group(1))
    except OSError:
        pass
    return result


def collect_bypass_stats(exp_dir) -> dict:
    """Aggregate bypass stats across all traces in exp_dir.

    Returns a dict with summed counts and derived rates:
      stlb_bypass_pkis  — STLB bypasses per kilo-instruction
      llc_bypass_pkis   — LLC bypasses per kilo-instruction
      st_hit_rate       — st_hits / st_lookups (or nan)
      pfq_hit_rate      — pfq_hits / pfq_probes (or nan)
      stlb_mpki         — aggregate STLB MPKI
      llc_mpki          — aggregate LLC MPKI
    """
    totals = {k: 0 for k in (
        "stlb_bypasses", "llc_bypasses",
        "st_lookups", "st_hits",
        "pfq_probes", "pfq_hits",
        "stlb_miss", "llc_miss", "instrs",
    )}
    for trace in os.listdir(exp_dir):
        out = os.path.join(exp_dir, trace, "champsim.out")
        s = parse_bypass_stats(out)
        for k in totals:
            if s[k] is not None:
                totals[k] += s[k]

    kilo = totals["instrs"] / 1000 if totals["instrs"] else float("nan")
    return {
        "stlb_bypass_pkis":  totals["stlb_bypasses"] / kilo if kilo else float("nan"),
        "llc_bypass_pkis":   totals["llc_bypasses"]  / kilo if kilo else float("nan"),
        "stlb_bypass_pct": (totals["stlb_bypasses"] / totals["stlb_miss"] * 100
                            if totals["stlb_miss"] else float("nan")),
        "llc_bypass_pct":  (totals["llc_bypasses"]  / totals["llc_miss"]  * 100
                            if totals["llc_miss"]  else float("nan")),
        "st_hit_rate":  (totals["st_hits"]  / totals["st_lookups"]
                         if totals["st_lookups"] else float("nan")),
        "pfq_hit_rate": (totals["pfq_hits"] / totals["pfq_probes"]
                         if totals["pfq_probes"] else float("nan")),
        "stlb_mpki": totals["stlb_miss"] / kilo if kilo else float("nan"),
        "llc_mpki":  totals["llc_miss"]  / kilo if kilo else float("nan"),
    }


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


def geomean(vals) -> "float | None":
    """Flat geometric mean of a collection; ignores None and non-positive values."""
    v = [x for x in vals if x is not None and x > 0]
    if not v:
        return None
    return float(np.exp(np.mean(np.log(v))))


def load_baseline(baseline_dir) -> "dict[str, float]":
    """Return {workload_name: ipc} for every trace found in baseline_dir.

    Supports both cluster layout (workload/champsim.out) and flat layout
    (workload.out).  Silently skips files where IPC cannot be parsed.
    """
    base = Path(baseline_dir)
    files = sorted(base.glob("*/champsim.out"))
    if files:
        return {f.parent.name: v
                for f in files
                if (v := parse_ipc(f)) is not None}
    files = sorted(base.glob("*.out"))
    return {f.stem: v for f in files if (v := parse_ipc(f)) is not None}


def find_test_dir(suite: str, study: str) -> str:
    """Return the most recent results/{suite}_{study}_*_test directory."""
    pattern = os.path.join("results", f"{suite}_{study}_*_test")
    matches = sorted(glob.glob(pattern))
    if not matches:
        print(f"No _test results found matching {pattern}", file=sys.stderr)
        sys.exit(1)
    return matches[-1]
