#!/usr/bin/env python3
"""
find_best_pacipv.py — identify the best IPV pair from a pacipv class sweep.

Reads results produced by sweep_pacipv_class.sh + run_pacipv_search.sh.
For each pair_NNNNN/ directory, collects IPC across all trace subdirs,
computes geomean IPC, and ranks pairs from best to worst.

Usage:
  python3 find_best_pacipv.py <results_dir> [--top-k N] [--baseline-dir DIR]

  <results_dir>     top-level results directory (contains pair_00000/, pair_00001/, ...)
  --top-k N         print the top N pairs (default 10)
  --baseline-dir    if given, report speedup (%) vs this LRU results dir
                    instead of raw geomean IPC
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from champsim_utils import parse_ipc, geomean


def read_ipv_pair(pair_dir: Path) -> "tuple[str, str] | None":
    f = pair_dir / next(iter(pair_dir.glob("*/ipv_pair.txt")), Path(""))
    if not f.exists():
        # try any ipv_pair.txt one level deeper
        candidates = list(pair_dir.glob("*/ipv_pair.txt"))
        if not candidates:
            return None
        f = candidates[0]
    lines = {k: v for k, v in
             (l.strip().split("=", 1) for l in f.read_text().splitlines() if "=" in l)}
    return lines.get("demand"), lines.get("prefetch")


def score_pair(pair_dir: Path, baseline_dirs: "dict[str, Path]") -> "float | None":
    ipcs = []
    for trace_dir in pair_dir.iterdir():
        if not trace_dir.is_dir():
            continue
        ipc = parse_ipc(trace_dir / "champsim.out")
        if ipc is None:
            continue
        if baseline_dirs:
            trace = trace_dir.name
            base_ipc = None
            for bd in baseline_dirs.values():
                base_ipc = parse_ipc(bd / trace / "champsim.out")
                if base_ipc:
                    break
            if base_ipc and base_ipc > 0:
                ipcs.append(ipc / base_ipc)
        else:
            ipcs.append(ipc)
    return geomean(ipcs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir")
    ap.add_argument("--top-k",        type=int, default=10)
    ap.add_argument("--baseline-dir", action="append", dest="baseline_dirs", default=[])
    args = ap.parse_args()

    results_dir = Path(args.results_dir)
    baseline_dirs = {str(p): Path(p) for p in args.baseline_dirs}

    pair_dirs = sorted(d for d in results_dir.iterdir()
                       if d.is_dir() and d.name.startswith("pair_"))
    if not pair_dirs:
        sys.exit(f"No pair_* directories found in {results_dir}")

    scores = []
    for pd in pair_dirs:
        ipv = read_ipv_pair(pd)
        score = score_pair(pd, baseline_dirs)
        if score is not None and ipv and ipv[0] and ipv[1]:
            scores.append((score, ipv[0], ipv[1], pd.name))

    if not scores:
        sys.exit("No complete results found.")

    scores.sort(reverse=True)
    metric = "geomean speedup vs baseline" if baseline_dirs else "geomean IPC"
    print(f"{'Rank':>4}  {'Score':>10}  {'Demand IPV':<15}  {'Prefetch IPV':<15}  Dir")
    print("-" * 72)
    for rank, (score, demand, prefetch, name) in enumerate(scores[: args.top_k], 1):
        val = f"{(score - 1) * 100:+.3f}%" if baseline_dirs else f"{score:.4f}"
        print(f"{rank:>4}  {val:>10}  {demand:<15}  {prefetch:<15}  {name}")

    best = scores[0]
    print(f"\nBest pair:")
    print(f"  demand  : {best[1]}")
    print(f"  prefetch: {best[2]}")
    print(f"\nTo use, pass these to the next sweep round or set in pacipv.cc defaults.")


if __name__ == "__main__":
    main()
