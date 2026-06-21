#!/usr/bin/env python3
"""
compare_validation.py — Compare validation results with liveness-replacement baseline.

Computes geomean IPC speedup for each threshold from validation run and compares
to liveness-replacement baseline threshold sweep results.
"""

import os
import sys
import json
from pathlib import Path
from statistics import geometric_mean

def read_ipc_results(result_dir):
    """Read IPC results from a ChampSim result directory."""
    results = {}
    for trace_dir in Path(result_dir).glob("srv_*"):
        trace_name = trace_dir.name
        stat_file = trace_dir / "stats.json"
        if stat_file.exists():
            try:
                with open(stat_file) as f:
                    data = json.load(f)
                    if "sim_IPC" in data:
                        results[trace_name] = float(data["sim_IPC"])
            except (json.JSONDecodeError, KeyError):
                pass
    return results

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 compare_validation.py <validation_result_dir> <baseline_thd_dir>")
        print("  validation_result_dir: results/qmm_validate_srrip_live_YYYYMMDD_HHMM/")
        print("  baseline_thd_dir:      results/qmm_srrip_live_thd_pc_20260513_0056/")
        sys.exit(1)

    val_dir = Path(sys.argv[1])
    baseline_dir = Path(sys.argv[2])

    if not val_dir.exists():
        print(f"Validation dir not found: {val_dir}")
        sys.exit(1)
    if not baseline_dir.exists():
        print(f"Baseline dir not found: {baseline_dir}")
        sys.exit(1)

    print(f"Validation: {val_dir.name}")
    print(f"Baseline:   {baseline_dir.name}")
    print()

    # Find baseline baseline (no threshold, just LRU or default config)
    # For now, assume we're comparing to the srrip_live results from the same timestamp

    thresholds = [1, 2, 4, 8, 16]
    results_by_thd = {}

    # Read validation results
    print("Validation results:")
    for thd in [4, 8]:
        thd_dir = val_dir / f"srrip_live_mid{thd}"
        if thd_dir.exists():
            ipcs = read_ipc_results(thd_dir)
            if ipcs:
                geomean = geometric_mean(ipcs.values())
                results_by_thd[thd] = geomean
                print(f"  MID_THD={thd}: geomean IPC = {geomean:.4f} ({len(ipcs)} traces)")

    print()
    print("Baseline results (from liveness-replacement):")
    for thd in thresholds:
        thd_dir = baseline_dir / f"srrip_live_thd{thd}"
        if thd_dir.exists():
            ipcs = read_ipc_results(thd_dir)
            if ipcs:
                geomean = geometric_mean(ipcs.values())
                print(f"  THD={thd}: geomean IPC = {geomean:.4f} ({len(ipcs)} traces)")

if __name__ == "__main__":
    main()
