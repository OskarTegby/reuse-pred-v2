"""
spec_weights.py — SimPoint-weighted aggregation helpers shared by all plot scripts.

Exports
-------
benchmark_weighted_geomean_pct(ratios_by_wl)
    Simpoint-weighted geomean IPC speedup (%) from a {trace: ipc_ratio} dict.
benchmark_weighted_geomean_abs(vals_by_wl)
    Benchmark-grouped geomean of absolute values (e.g. MPKI).
benchmark_weighted_mean_pct(pct_by_wl)
    Benchmark-grouped arithmetic mean for bypass percentages.
"""

import re
from pathlib import Path

import numpy as np


_DEFAULT_WEIGHTS_DIR = (
    Path(__file__).parents[2] / ".." / "ChampSim-dev" / "trace-files" / "SPEC2006_weights"
).resolve()


def _load_spec_weights(weights_dir: Path) -> "dict[str, float]":
    result: dict = {}
    if not weights_dir.is_dir():
        return result
    for bm_dir in sorted(weights_dir.iterdir()):
        if not bm_dir.is_dir():
            continue
        w_file = bm_dir / "weights.out"
        s_file = bm_dir / "simpoints.out"
        if not (w_file.exists() and s_file.exists()):
            continue
        w_vals = [float(x) for x in w_file.read_text().split()]
        s_ids  = [int(x)   for x in s_file.read_text().split()]
        for sp_id, w in zip(s_ids, w_vals):
            result[f"{bm_dir.name}-{sp_id}B"] = w
    return result


def _benchmark_name(wl: str) -> str:
    m = re.match(r'^(.+)-\d+[A-Z]+$', wl)
    return m.group(1) if m else wl


_SPEC_WEIGHTS: "dict[str, float]" = _load_spec_weights(_DEFAULT_WEIGHTS_DIR)

# Public aliases for scripts that need direct weight lookup.
SPEC_WEIGHTS  = _SPEC_WEIGHTS
benchmark_name = _benchmark_name


def benchmark_weighted_geomean_pct(ratios_by_wl: "dict[str, float]") -> float:
    """Simpoint-weighted geomean speedup (%).

    For SPEC traces with weights: weighted geomean within each benchmark
    (re-normalised for missing simpoints), then equal-weight geomean across
    benchmarks.  For other traces: flat equal-weight geomean.
    ratios_by_wl values are raw ratios (ipc_new/ipc_base), not percentages.
    """
    groups: dict = {}
    for wl, r in ratios_by_wl.items():
        groups.setdefault(_benchmark_name(wl), []).append(wl)
    per_bench = []
    for wl_list in groups.values():
        if _SPEC_WEIGHTS:
            pairs = [(ratios_by_wl[wl], _SPEC_WEIGHTS.get(wl)) for wl in wl_list]
            if any(w is not None for _, w in pairs):
                pairs = [(r, w) for r, w in pairs if w is not None and r > 0]
                total_w = sum(w for _, w in pairs)
                if total_w > 0:
                    per_bench.append(
                        float(np.exp(sum((w / total_w) * np.log(r) for r, w in pairs))))
                    continue
        vals = [ratios_by_wl[wl] for wl in wl_list if ratios_by_wl[wl] > 0]
        if vals:
            per_bench.append(float(np.exp(np.mean(np.log(vals)))))
    if not per_bench:
        return float("nan")
    return (float(np.exp(np.mean(np.log([r for r in per_bench if r > 0])))) - 1) * 100


def benchmark_weighted_geomean_abs(vals_by_wl: "dict[str, float]") -> float:
    """Benchmark-grouped geomean of absolute values (e.g. MPKI).

    No simpoint weights — equal weight within each benchmark group, then
    geomean across groups.
    """
    groups: dict = {}
    for wl, v in vals_by_wl.items():
        if not np.isnan(v) and v > 0:
            groups.setdefault(_benchmark_name(wl), []).append(v)
    if not groups:
        return float("nan")
    bench_means = [float(np.exp(np.mean(np.log(vs)))) for vs in groups.values() if vs]
    return float(np.exp(np.mean(np.log(bench_means)))) if bench_means else float("nan")


def benchmark_weighted_mean_pct(pct_by_wl: "dict[str, float]") -> float:
    """Benchmark-grouped arithmetic mean for bypass percentages (can be 0%)."""
    groups: dict = {}
    for wl, v in pct_by_wl.items():
        if not np.isnan(v):
            groups.setdefault(_benchmark_name(wl), []).append(v)
    if not groups:
        return float("nan")
    bench_means = [float(np.mean(vs)) for vs in groups.values() if vs]
    return float(np.mean(bench_means)) if bench_means else float("nan")
