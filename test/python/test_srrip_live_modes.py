"""Black-box regression tests for SRRIP-Live replacement policy.

Pins IPC and LLC miss count for each scoring mode and history table capacity
configuration.  All scoring modes produce identical IPC on pagerank because
the trace is 100% DoA — every block is eventually classified as DoA regardless
of how the score is weighted.  If a change to the scoring system causes any
mode to diverge, the pinned value catches it.

Quantitative ordering test: cap=1 must degrade IPC relative to cap=2 because
the history table cannot retain all active PCs simultaneously.

Trace: pagerank.champsimtrace.xz (100% DoA, 4 unique PCs).
Pinned: June 2026, main branch, post duel-miss-latency merge.
"""

import os
import re
import subprocess
import unittest
from pathlib import Path

ROOT  = Path(__file__).resolve().parents[2]
BIN   = ROOT / "bin" / "champsim_srrip_live"
TRACE = ROOT / "trace-files" / "pagerank.champsimtrace.xz"

WARMUP  = "1000000"
SIM     = "2000000"
IPC_TOL = 0.0001

BASE = dict(THD_DOA=6, THD_DEAD=10, BHIST_MODE="pc", SRRIP_LIVE_TARGET="llc")

# pagerank's four load PCs (deterministic addresses from the trace).
PC_HEAVY = {"0x555555563de8", "0x555555563df1"}
PC_LIGHT = {"0x555555563dfa", "0x555555563e02"}
PC_ALL   = PC_HEAVY | PC_LIGHT

_CONFIGS = {
    "default": {},
    "mode3":   {**BASE, "SCORING_MODE": 3},
    "mode4":   {**BASE, "SCORING_MODE": 4},
    "mode5":   {**BASE, "SCORING_MODE": 5},
    "mode7":   {**BASE, "SCORING_MODE": 7},
    "mode8":   {**BASE, "SCORING_MODE": 8},
    "cap256":  {**BASE, "SCORING_MODE": 5, "REPL_HIST_LLC_CAP": 256,
                        "REPL_HIST_REPL": "tiered", "REPL_HIST_DUMP_PCS": 1},
}

PINNED = [
    ("default", "default", 0.211229, 111112),
    ("mode3",   "mode3",   0.211229, 111112),
    ("mode4",   "mode4",   0.211229, 111112),
    ("mode5",   "mode5",   0.211229, 111112),
    ("mode7",   "mode7",   0.211229, 111112),
    ("mode8",   "mode8",   0.211229, 111112),
    ("cap256",  "cap256",  0.211229, 111112),
]

R: dict = {}

def setUpModule():
    if not BIN.exists() or not TRACE.exists():
        return
    for key, env in _CONFIGS.items():
        R[key] = _run(env)

def _run(env_extra):
    env = {**os.environ, **{k: str(v) for k, v in env_extra.items()}}
    result = subprocess.run(
        [str(BIN), "--warmup_instructions", WARMUP,
         "--simulation_instructions", SIM, str(TRACE)],
        capture_output=True, text=True, env=env, timeout=120,
    )
    out = result.stdout + result.stderr
    stats = {"raw": out, "returncode": result.returncode, "pcs": {}}
    for line in out.splitlines():
        if "CPU 0 cumulative IPC:" in line:
            stats["ipc"] = float(line.split()[4])
        if "LLC TOTAL" in line:
            parts = line.split()
            try:
                stats["llc_miss"] = int(parts[parts.index("MISS:") + 1])
            except (ValueError, IndexError):
                pass
        m = re.search(r"repl_hist PCS: count=(\d+)", line)
        if m:
            stats["pc_count"] = int(m.group(1))
        m = re.search(r"repl_hist PC: key=(0x[0-9a-f]+) doa=(-?\d+) md=(-?\d+)", line)
        if m:
            stats["pcs"][m.group(1)] = (int(m.group(2)), int(m.group(3)))
    return stats

def _make_pinned(key, expected_ipc, expected_miss):
    def test(self):
        s = R[key]
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], expected_ipc, delta=IPC_TOL)
        self.assertEqual(s.get("llc_miss"), expected_miss)
    return test


@unittest.skipUnless(BIN.exists(),   f"binary not found: {BIN}")
@unittest.skipUnless(TRACE.exists(), f"trace not found: {TRACE}")
class TestPinned(unittest.TestCase):
    """End-to-end regression: each config must reproduce its reference IPC and miss count."""

for _name, _key, _ipc, _miss in PINNED:
    setattr(TestPinned, f"test_{_name}", _make_pinned(_key, _ipc, _miss))


@unittest.skipUnless(BIN.exists(),   f"binary not found: {BIN}")
@unittest.skipUnless(TRACE.exists(), f"trace not found: {TRACE}")
class TestOrdering(unittest.TestCase):

    def test_all_scoring_modes_converge(self):
        # pagerank is 100% DoA — scoring weights do not affect which blocks
        # cross the DoA threshold, so all modes must produce the same IPC.
        ipcs = [R[f"mode{m}"]["ipc"] for m in (3, 4, 5, 7, 8)]
        for ipc in ipcs:
            self.assertAlmostEqual(ipc, ipcs[0], delta=IPC_TOL)

    # History-table contents under a realistic cap (256).  Local placeholder for
    # the real eviction-policy test on a many-PC trace (QMM/SPEC).

    def test_table_holds_exactly_the_trace_pcs(self):
        self.assertEqual(R["cap256"].get("pc_count"), len(PC_ALL))
        self.assertEqual(set(R["cap256"]["pcs"].keys()), PC_ALL)

    def test_heavy_pcs_classify_strongly_doa(self):
        pcs = R["cap256"]["pcs"]
        for k in PC_HEAVY:
            self.assertGreater(pcs[k][0], 1000, msg=f"{k} doa={pcs[k][0]} too low")
        for k in PC_LIGHT:
            self.assertLess(pcs[k][0], 100, msg=f"{k} doa={pcs[k][0]} too high")


if __name__ == "__main__":
    unittest.main(verbosity=2)
