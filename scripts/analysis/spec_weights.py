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
SPEC_WEIGHTS       = _SPEC_WEIGHTS
benchmark_name     = _benchmark_name
load_spec_weights  = _load_spec_weights


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


def geomean_pct(pct_list: "list[float]") -> float:
    """Flat (unweighted) geomean of a list of %-speedup values."""
    ratios = [v / 100.0 + 1.0 for v in pct_list if not np.isnan(v) and v > -100]
    if not ratios:
        return float("nan")
    return (float(np.exp(np.mean(np.log(ratios)))) - 1.0) * 100.0


def weighted_geomean_pct(vals: "list[float]", weights: "list[float | None]") -> float:
    """Weighted geomean of parallel %-speedup values and weight values.

    Falls back to equal-weight geomean for entries with None weight.
    vals and weights must have the same length.
    """
    pairs = [(v / 100.0 + 1.0, w) for v, w in zip(vals, weights)]
    valid_w = [(r, w) for r, w in pairs if r > 0 and w is not None]
    if valid_w:
        total = sum(w for _, w in valid_w)
        if total > 0:
            return (float(np.exp(sum((w / total) * np.log(r) for r, w in valid_w))) - 1.0) * 100.0
    valid = [r for r, _ in pairs if r > 0]
    return (float(np.exp(np.mean(np.log(valid)))) - 1.0) * 100.0 if valid else float("nan")


def benchmark_weighted_geomean_frac(trace_names: "list[str]", fracs: "list[float]") -> float:
    """Benchmark-weighted geomean of per-trace fractions (e.g. liveness rates).

    Like benchmark_weighted_geomean_pct but operates on 0–1 fractions rather
    than IPC ratios.  Clips values to a small epsilon before taking the log so
    that exact-zero fractions do not collapse the geomean.
    """
    eps = 1e-6
    by_wl = dict(zip(trace_names, fracs))
    groups: dict = {}
    for wl in by_wl:
        groups.setdefault(_benchmark_name(wl), []).append(wl)
    per_bench = []
    for wl_list in groups.values():
        if _SPEC_WEIGHTS:
            pairs = [(by_wl[wl], _SPEC_WEIGHTS.get(wl)) for wl in wl_list]
            if any(w is not None for _, w in pairs):
                pairs = [(v, w) for v, w in pairs if w is not None]
                total_w = sum(w for _, w in pairs)
                if total_w > 0:
                    per_bench.append(
                        float(np.exp(sum((w / total_w) * np.log(max(v, eps))
                                        for v, w in pairs))))
                    continue
        vals = [max(by_wl[wl], eps) for wl in wl_list]
        per_bench.append(float(np.exp(np.mean(np.log(vals)))))
    if not per_bench:
        return float("nan")
    return float(np.exp(np.mean(np.log([max(v, eps) for v in per_bench]))))


def aggregate_spec_liveness(rows: list) -> list:
    """Collapse SPEC simpoints into parent-benchmark rows for liveness data.

    For SPEC traces (identified by the -NNNb suffix): compute SimPoint-weighted
    average liveness fractions within each benchmark and return one synthetic
    row per benchmark.  Non-SPEC rows are kept as-is.

    rows = [(wl_name, {cache: {"total": int, "doa": int, "mostly_dead": int,
                                "mostly_alive": int, ...}})]
    """
    groups: dict = {}
    for wl, data in rows:
        groups.setdefault(_benchmark_name(wl), []).append((wl, data))

    result = []
    for bm_name in sorted(groups.keys()):
        items = groups[bm_name]
        if len(items) == 1 and items[0][0] == bm_name:
            result.append(items[0])
            continue
        all_caches: set = set()
        for _, d in items:
            all_caches |= set(d.keys())
        agg_data: dict = {}
        for cache in all_caches:
            sp_fracs = []
            for wl, data in items:
                d = data.get(cache, {})
                tot = d.get("total", 0)
                if tot == 0:
                    continue
                w = _SPEC_WEIGHTS.get(wl)
                sp_fracs.append((d.get("doa", 0) / tot,
                                 d.get("mostly_dead", 0) / tot,
                                 d.get("mostly_alive", 0) / tot, w))
            if not sp_fracs:
                continue
            w_valid = [(d, m, a, w) for d, m, a, w in sp_fracs if w is not None]
            if w_valid and _SPEC_WEIGHTS:
                total_w = sum(w for _, _, _, w in w_valid)
                if total_w > 0:
                    avg_doa = sum(w / total_w * d for d, _, _, w in w_valid)
                    avg_md  = sum(w / total_w * m for _, m, _, w in w_valid)
                    avg_ma  = sum(w / total_w * a for _, _, a, w in w_valid)
                else:
                    avg_doa = sum(d for d, _, _, _ in sp_fracs) / len(sp_fracs)
                    avg_md  = sum(m for _, m, _, _ in sp_fracs) / len(sp_fracs)
                    avg_ma  = sum(a for _, _, a, _ in sp_fracs) / len(sp_fracs)
            else:
                avg_doa = sum(d for d, _, _, _ in sp_fracs) / len(sp_fracs)
                avg_md  = sum(m for _, m, _, _ in sp_fracs) / len(sp_fracs)
                avg_ma  = sum(a for _, _, a, _ in sp_fracs) / len(sp_fracs)
            SCALE = 10000
            agg_data[cache] = {
                "total":        SCALE,
                "doa":          int(avg_doa * SCALE),
                "mostly_dead":  int(avg_md  * SCALE),
                "mostly_alive": int(avg_ma  * SCALE),
            }
        if agg_data:
            result.append((bm_name, agg_data))
    return result
