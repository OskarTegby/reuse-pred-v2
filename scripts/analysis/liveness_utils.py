"""
liveness_utils.py — shared parsing for ChampSim liveness output.

Exports
-------
parse_liveness_file(path) -> dict
    Parse LIVENESS EVICTIONS and HIT_HIST sections from a champsim.out file.

load_suite(results_dir) -> list[(wl_name, data)]
    Load liveness data for every trace in a results directory.

parse_correlation(path) -> tuple | None
    Parse (stlb_doa_pct, llc_doa_pct, llc_doa_on_page_pct) from a file.

load_suite_corr(results_dir) -> list[(wl, stlb_doa, llc_doa, llc_on_page)]
    Load correlation data for every trace in a results directory.

parse_per_pc(path, cache) -> (evictions, doa, mostly_dead) arrays
    Parse per-PC liveness arrays from a champsim.out file or pc_liveness.csv.

load_suite_pc(results_dir, cache) -> list[(wl, evictions, doa, md)]
    Load per-PC liveness arrays for every trace in a results directory.
"""

import re
import sys
from pathlib import Path

import numpy as np


# ── Liveness eviction + hit-histogram parsing ─────────────────────────────────

N_HIST_BINS = 9

_EVICT_PAT = re.compile(
    r"^(\S+) LIVENESS EVICTIONS:\s+(\d+)"
    r"\s+DOA:\s+(\d+)\s+\([\d.]+%\)"
    r"\s+MOSTLY_DEAD:\s+(\d+)\s+\([\d.]+%\)"
    r"\s+MOSTLY_ALIVE:\s+(\d+)\s+\([\d.]+%\)",
    re.MULTILINE,
)
_HIST_PAT = re.compile(r"^(\S+) LIVENESS HIT_HIST:(.*)", re.MULTILINE)


def parse_liveness_file(path) -> dict:
    """Return {cache_name: {total, doa, mostly_dead, mostly_alive, hit_hist}}."""
    text = Path(path).read_text(errors="replace")
    result = {}

    for m in _EVICT_PAT.finditer(text):
        result[m.group(1)] = {
            "total":        int(m.group(2)),
            "doa":          int(m.group(3)),
            "mostly_dead":  int(m.group(4)),
            "mostly_alive": int(m.group(5)),
            "hit_hist":     np.zeros(N_HIST_BINS, dtype=float),
        }

    for m in _HIST_PAT.finditer(text):
        name = m.group(1)
        counts = re.findall(r"(\d+)\+?:(\d+)", m.group(2))
        hist = np.zeros(N_HIST_BINS, dtype=float)
        for idx_str, cnt_str in counts:
            idx = min(int(idx_str), N_HIST_BINS - 1)
            hist[idx] += int(cnt_str)
        if name in result:
            result[name]["hit_hist"] = hist

    return result


def load_suite(results_dir) -> list:
    """Load all champsim.out files. Returns [(workload_name, data_dict)]."""
    base = Path(results_dir)
    files = sorted(base.glob("*/champsim.out"))
    nested = True
    if not files:
        files = sorted(base.glob("*.out"))
        nested = False
    if not files:
        sys.exit(f"ERROR: no output files found in {results_dir}")
    rows = []
    for f in files:
        workload = f.parent.name if nested else f.stem
        data = parse_liveness_file(f)
        if not data:
            print(f"  WARNING: no LIVENESS lines in {f} — skipped")
            continue
        rows.append((workload, data))
    return rows


# ── Correlation parsing ───────────────────────────────────────────────────────

_CORR_STLB    = re.compile(r"cpu0_STLB LIVENESS EVICTIONS:\s+(\d+)\s+DOA:\s+(\d+)")
_CORR_LLC_TOT = re.compile(r"LLC LIVENESS EVICTIONS:\s+(\d+)\s+DOA:\s+(\d+)")

# New 4-bucket format (plain_printer.cc):
#   LLC LIVENESS DOA/STLB CORRELATION (denom = LLC DoA):
#     resident_doa=N (X%)  resident_alive=N (X%)
#     evicted_doa=N (X%)   evicted_alive=N (X%)   uncovered=N (X%)
_CORR_V2 = re.compile(
    r"LLC LIVENESS DOA/STLB CORRELATION[^:]*:"
    r".*?resident_doa=(\d+)"
    r".*?resident_alive=(\d+)"
    r".*?evicted_doa=(\d+)"
    r".*?evicted_alive=(\d+)"
    r".*?uncovered=(\d+)",
    re.DOTALL,
)


def parse_correlation_full(path) -> "dict | None":
    """Parse the full 4-bucket DoA/STLB correlation from a champsim.out file.

    Returns a dict with keys:
        stlb_total, stlb_doa,
        llc_total,  llc_doa,
        resident_doa, resident_alive,
        evicted_doa,  evicted_alive,
        uncovered,
        coverage_pct,     # (covered / llc_doa) × 100
        precision_pct,    # ((resident_doa + evicted_doa) / covered) × 100; NaN if covered==0
        stlb_doa_pct,     # stlb_doa / stlb_total × 100
        llc_doa_pct,      # llc_doa  / llc_total  × 100
    or None if the required lines are absent.
    """
    text = Path(path).read_text(errors="replace")
    sm = _CORR_STLB.search(text)
    lm = _CORR_LLC_TOT.search(text)
    cm = _CORR_V2.search(text)
    if not (sm and lm and cm):
        return None

    stlb_total = int(sm.group(1)); stlb_doa = int(sm.group(2))
    llc_total  = int(lm.group(1)); llc_doa  = int(lm.group(2))
    resident_doa   = int(cm.group(1))
    resident_alive = int(cm.group(2))
    evicted_doa    = int(cm.group(3))
    evicted_alive  = int(cm.group(4))
    uncovered      = int(cm.group(5))

    if llc_doa == 0:
        return None

    covered = resident_doa + resident_alive + evicted_doa + evicted_alive
    precision = float("nan") if covered == 0 else \
        100.0 * (resident_doa + evicted_doa) / covered

    return {
        "stlb_total":     stlb_total,
        "stlb_doa":       stlb_doa,
        "llc_total":      llc_total,
        "llc_doa":        llc_doa,
        "resident_doa":   resident_doa,
        "resident_alive": resident_alive,
        "evicted_doa":    evicted_doa,
        "evicted_alive":  evicted_alive,
        "uncovered":      uncovered,
        "coverage_pct":   100.0 * covered / llc_doa,
        "precision_pct":  precision,
        "stlb_doa_pct":   100.0 * stlb_doa / stlb_total if stlb_total > 0 else 0.0,
        "llc_doa_pct":    100.0 * llc_doa  / llc_total  if llc_total  > 0 else 0.0,
    }


def parse_correlation(path) -> "tuple | None":
    """Return (stlb_doa_pct, llc_doa_pct, llc_doa_on_page_pct) or None.

    llc_doa_on_page_pct is the resident_doa fraction (= original stat, now
    one of four buckets).  Use parse_correlation_full() for the full breakdown.
    """
    d = parse_correlation_full(path)
    if d is None:
        return None
    on_page_pct = 100.0 * d["resident_doa"] / d["llc_doa"] if d["llc_doa"] > 0 else 0.0
    return (d["stlb_doa_pct"], d["llc_doa_pct"], on_page_pct)


def load_suite_corr(results_dir) -> list:
    """Return [(workload, stlb_doa_pct, llc_doa_pct, llc_on_page_pct)]."""
    base = Path(results_dir)
    files = sorted(base.glob("*/champsim.out"))
    if not files:
        files = sorted(base.glob("*.out"))
    rows = []
    for f in files:
        wl = f.parent.name if f.name == "champsim.out" else f.stem
        r = parse_correlation(f)
        if r is not None:
            rows.append((wl, r[0], r[1], r[2]))
    return rows


def load_suite_corr_full(results_dir) -> list:
    """Return [(workload, corr_dict)] for every trace that has correlation data."""
    base = Path(results_dir)
    files = sorted(base.glob("*/champsim.out"))
    if not files:
        files = sorted(base.glob("*.out"))
    rows = []
    for f in files:
        wl = f.parent.name if f.name == "champsim.out" else f.stem
        d = parse_correlation_full(f)
        if d is not None:
            rows.append((wl, d))
    return rows


# ── Per-PC liveness parsing ───────────────────────────────────────────────────

_PC_HEADER = re.compile(r"^(\S+) PER-PC LIVENESS \(\d+ PCs\):", re.MULTILINE)
_PC_ROW    = re.compile(
    r"^\s+(0x[0-9a-fA-F]+)\s+(\d+)\s+(\d+)\s+\([\d.]+%\)\s+(\d+)\s+\([\d.]+%\)\s+(\d+)",
    re.MULTILINE,
)


def parse_per_pc(path, cache: str) -> "tuple[np.ndarray, np.ndarray, np.ndarray]":
    """Return (evictions, doa, mostly_dead) arrays for every PC recorded for cache.

    Tries two sources in order:
      1. PER-PC LIVENESS text blocks in champsim.out
      2. pc_liveness.csv written alongside champsim.out
    """
    path = Path(path)
    text = path.read_text(errors="replace")
    start = None
    for m in _PC_HEADER.finditer(text):
        if m.group(1) == cache:
            start = m.end()
            break
    if start is not None:
        next_hdr = _PC_HEADER.search(text, start)
        section  = text[start: next_hdr.start() if next_hdr else len(text)]
        rows = _PC_ROW.findall(section)
        if rows:
            return (np.array([int(r[1]) for r in rows], dtype=float),
                    np.array([int(r[2]) for r in rows], dtype=float),
                    np.array([int(r[3]) for r in rows], dtype=float))

    csv_path = path.parent / "pc_liveness.csv"
    if csv_path.exists():
        import csv as _csv
        evictions, doa, md = [], [], []
        with csv_path.open(newline="") as f:
            for row in _csv.DictReader(f):
                if row["cache"] == cache:
                    evictions.append(int(row["evictions"]))
                    doa.append(int(row["doa"]))
                    md.append(int(row["mostly_dead"]))
        if evictions:
            return (np.array(evictions, dtype=float),
                    np.array(doa, dtype=float),
                    np.array(md, dtype=float))

    return np.zeros(0), np.zeros(0), np.zeros(0)


def load_suite_pc(results_dir, cache: str) -> list:
    """Return [(workload, evictions_arr, doa_arr, md_arr)] for workloads with PC data."""
    base = Path(results_dir)
    files = sorted(base.glob("*/champsim.out"))
    if not files:
        files = sorted(base.glob("*.out"))
    out = []
    for f in files:
        wl = f.parent.name if f.name == "champsim.out" else f.stem
        ev, doa, md = parse_per_pc(f, cache)
        if ev.size > 0:
            out.append((wl, ev, doa, md))
    return out
