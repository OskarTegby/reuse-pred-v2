#!/usr/bin/env python3
"""
extract_paper_data.py — harvest all data needed to reproduce paper plots.

Reads champsim.out files from the original results/ directories and writes
compact JSON files to results/paper/data/. Running the plot scripts with
USE_PAPER_DATA=1 (or pointing them at paper/data/) will then work without
the full results tree.

Usage:
    python3 scripts/analysis/extract_paper_data.py
"""

import json
import os
import re
import sys
from pathlib import Path

ROOT       = Path(__file__).resolve().parents[2]
RESULTS    = ROOT / "results"
CLUSTER    = RESULTS / "cluster"
PAPER_DATA = RESULTS / "paper" / "data"

PAPER_DATA.mkdir(parents=True, exist_ok=True)

# ── Parsing helpers ────────────────────────────────────────────────────────────

IPC_PAT      = re.compile(r"cumulative IPC:\s+([0-9.]+)\s+instructions:\s+(\d+)")
LIVENESS_LLC = re.compile(
    r"LLC LIVENESS EVICTIONS:\s+(\d+)\s+"
    r"DOA:\s+(\d+).*?MOSTLY_DEAD:\s+(\d+).*?MOSTLY_ALIVE:\s+(\d+)"
)
LIVENESS_STLB = re.compile(
    r"cpu0_STLB LIVENESS EVICTIONS:\s+(\d+)\s+"
    r"DOA:\s+(\d+).*?MOSTLY_DEAD:\s+(\d+).*?MOSTLY_ALIVE:\s+(\d+)"
)


def parse_out(path: Path) -> dict:
    """Extract IPC and liveness counts from one champsim.out."""
    result = {}
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return result

    in_roi = False
    for line in text.splitlines():
        if "Region of Interest Statistics" in line:
            in_roi = True
        if in_roi:
            m = IPC_PAT.search(line)
            if m:
                result["ipc"] = float(m.group(1))
                break

    m = LIVENESS_LLC.search(text)
    if m:
        result["llc_liveness"] = {
            "total": int(m.group(1)), "doa": int(m.group(2)),
            "dead":  int(m.group(3)), "alive": int(m.group(4)),
        }
    m = LIVENESS_STLB.search(text)
    if m:
        result["stlb_liveness"] = {
            "total": int(m.group(1)), "doa": int(m.group(2)),
            "dead":  int(m.group(3)), "alive": int(m.group(4)),
        }
    return result


def extract_dir(src: Path, label: str) -> dict:
    """
    Walk src/*/champsim.out and return {trace_name: {ipc, llc_liveness, …}}.
    src may be a flat dir (trace_name/champsim.out) or already contain the file.
    """
    records = {}
    if not src.exists():
        print(f"  MISSING: {src}", file=sys.stderr)
        return records
    for trace_dir in sorted(src.iterdir()):
        out = trace_dir / "champsim.out"
        if trace_dir.is_dir() and out.exists():
            data = parse_out(out)
            if data:
                records[trace_dir.name] = data
    print(f"  {label}: {len(records)} traces from {src.name}")
    return records


def save(data: dict, name: str):
    path = PAPER_DATA / f"{name}.json"
    path.write_text(json.dumps(data, indent=2))


# ── Experiment catalogue ───────────────────────────────────────────────────────

SUITES = ["dpc3", "gap", "gms", "google", "ligra", "ml", "qmm"]
THRESHOLDS = [1, 2, 4, 8, 16]

# Liveness + LLC LRU baseline (same dir, different use)
LLC_LRU_DIRS = {s: RESULTS / f"{s}_repl_pol_20260522_0722" / "lru_baseline"
                for s in SUITES}

# LLC SRRIP-Live threshold dirs
SRRIP_LLC_DIRS = {
    "dpc3":   RESULTS / "dpc3_srrip_live_thd_pc_20260513_0055",
    "qmm":    RESULTS / "qmm_srrip_live_thd_pc_20260513_0056",
    "google": RESULTS / "google_srrip_live_thd_pc_20260513_0056",
    "gap":    RESULTS / "gap_srrip_live_thd_pc_20260520_0059",
    "gms":    RESULTS / "gms_srrip_live_thd_pc_20260520_0128",
    "ligra":  RESULTS / "ligra_srrip_live_thd_pc_20260520_0059",
    "ml":     RESULTS / "ml_srrip_live_thd_pc_20260520_0059",
}

# LLC IPV-Live threshold dirs
IPV_LLC_DIRS = {
    "dpc3":   CLUSTER / "dpc3_ipv_live_thd_addr_20260514_1432",
    "qmm":    CLUSTER / "qmm_ipv_live_thd_pc_20260514_1432",
    "google": CLUSTER / "google_ipv_live_thd_pc_20260514_1432",
    "gap":    RESULTS / "gap_ipv_live_thd_pc_20260520_0819",
    "gms":    RESULTS / "gms_ipv_live_thd_pc_20260520_0819",
    "ligra":  RESULTS / "ligra_ipv_live_thd_pc_20260520_0819",
    "ml":     RESULTS / "ml_ipv_live_thd_pc_20260520_0819",
}

# STLB SRRIP-Live threshold dirs
SRRIP_STLB_DIRS = {
    "dpc3":   RESULTS / "dpc3_stlb_thd_pc_20260514_0025",
    "qmm":    RESULTS / "qmm_stlb_thd_pc_20260514_0025",
    "google": RESULTS / "google_stlb_thd_pc_20260514_0025",
    "gap":    RESULTS / "gap_stlb_thd_pc_20260520_0826",
    "gms":    RESULTS / "gms_stlb_thd_pc_20260520_0826",
    "ligra":  RESULTS / "ligra_stlb_thd_pc_20260520_0826",
    "ml":     RESULTS / "ml_stlb_thd_pc_20260520_0826",
}

# STLB IPV-Live threshold dirs
IPV_STLB_DIRS = {
    "dpc3":   RESULTS / "dpc3_stlb_ipv_live_thd_pc_20260524_0142",
    "qmm":    RESULTS / "qmm_stlb_ipv_live_thd_pc_20260516_0902",
    "google": RESULTS / "google_stlb_ipv_live_thd_pc_20260516_0902",
    "gap":    RESULTS / "gap_stlb_ipv_live_thd_pc_20260520_0827",
    "gms":    RESULTS / "gms_stlb_ipv_live_thd_pc_20260520_0827",
    "ligra":  RESULTS / "ligra_stlb_ipv_live_thd_pc_20260520_0827",
    "ml":     RESULTS / "ml_stlb_ipv_live_thd_pc_20260520_0827",
}

# STLB LRU baseline dirs
STLB_LRU_DIRS = {
    "dpc3":   RESULTS / "dpc3_stlb_policy_pc_20260513_0916" / "lru",
    "qmm":    RESULTS / "qmm_stlb_policy_pc_20260513_0916" / "lru",
    "google": RESULTS / "google_stlb_policy_pc_20260513_0916" / "lru",
    "gap":    RESULTS / "gap_stlb_policy_pc_20260523_1529" / "lru",
    "gms":    RESULTS / "gms_stlb_policy_pc_20260523_1529" / "lru",
    "ligra":  RESULTS / "ligra_stlb_policy_pc_20260523_1529" / "lru",
    "ml":     RESULTS / "ml_stlb_policy_pc_20260523_1529" / "lru",
}

# Combined LLC+STLB dirs (best threshold per suite)
COMBINED_DIRS = {
    "dpc3": {
        "llc_srrip":  SRRIP_LLC_DIRS["dpc3"]   / "srrip_live_thd8",
        "stlb_srrip": SRRIP_STLB_DIRS["dpc3"]  / "stlb_srrip_live_thd16",
        "both_srrip": CLUSTER / "dpc3_srrip_live_both_thd_addr_20260514_2018" / "srrip_live_both_thd16",
        "both_ipv":   CLUSTER / "dpc3_ipv_live_both_thd_addr_20260517_2217"   / "ipv_live_both_thd16",
        "lru":        LLC_LRU_DIRS["dpc3"],
    },
    "google": {
        "llc_srrip":  SRRIP_LLC_DIRS["google"]  / "srrip_live_thd8",
        "stlb_srrip": SRRIP_STLB_DIRS["google"] / "stlb_srrip_live_thd16",
        "both_srrip": CLUSTER / "google_srrip_live_both_thd_pc_20260514_2018" / "srrip_live_both_thd8",
        "both_ipv":   CLUSTER / "google_ipv_live_both_thd_pc_20260517_2218"   / "ipv_live_both_thd8",
        "lru":        LLC_LRU_DIRS["google"],
    },
    "qmm": {
        "llc_srrip":  SRRIP_LLC_DIRS["qmm"]  / "srrip_live_thd4",
        "stlb_srrip": SRRIP_STLB_DIRS["qmm"] / "stlb_srrip_live_thd1",
        "both_srrip": CLUSTER / "qmm_srrip_live_both_thd_pc_20260514_2018" / "srrip_live_both_thd4",
        "both_ipv":   CLUSTER / "qmm_ipv_live_both_thd_pc_20260517_2218"   / "ipv_live_both_thd2",
        "lru":        LLC_LRU_DIRS["qmm"],
    },
}

# ── Extract ────────────────────────────────────────────────────────────────────

print("=== Liveness + LLC LRU baseline ===")
for suite in SUITES:
    data = extract_dir(LLC_LRU_DIRS[suite], suite)
    save(data, f"llc_lru_{suite}")

print("\n=== LLC SRRIP-Live thresholds ===")
for suite in SUITES:
    for thd in THRESHOLDS:
        src = SRRIP_LLC_DIRS[suite] / f"srrip_live_thd{thd}"
        data = extract_dir(src, f"{suite}/thd{thd}")
        save(data, f"llc_srrip_{suite}_thd{thd}")

print("\n=== LLC IPV-Live thresholds ===")
for suite in SUITES:
    for thd in THRESHOLDS:
        src = IPV_LLC_DIRS[suite] / f"ipv_live_thd{thd}"
        data = extract_dir(src, f"{suite}/thd{thd}")
        save(data, f"llc_ipv_{suite}_thd{thd}")

print("\n=== STLB SRRIP-Live thresholds ===")
for suite in SUITES:
    data = extract_dir(STLB_LRU_DIRS[suite], f"{suite} lru")
    save(data, f"stlb_lru_{suite}")
    for thd in THRESHOLDS:
        src = SRRIP_STLB_DIRS[suite] / f"stlb_srrip_live_thd{thd}"
        data = extract_dir(src, f"{suite}/thd{thd}")
        save(data, f"stlb_srrip_{suite}_thd{thd}")

print("\n=== STLB IPV-Live thresholds ===")
for suite in SUITES:
    for thd in THRESHOLDS:
        src = IPV_STLB_DIRS[suite] / f"stlb_ipv_live_thd{thd}"
        data = extract_dir(src, f"{suite}/thd{thd}")
        save(data, f"stlb_ipv_{suite}_thd{thd}")

print("\n=== Combined LLC+STLB ===")
for suite, configs in COMBINED_DIRS.items():
    for key, src in configs.items():
        data = extract_dir(src, f"{suite}/{key}")
        save(data, f"combined_{suite}_{key}")

print(f"\nDone. {len(list(PAPER_DATA.glob('*.json')))} JSON files in {PAPER_DATA}")
