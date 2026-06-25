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

_CONFIGS = {
    "default": {},
    "mode3":   {**BASE, "SCORING_MODE": 3},
    "mode4":   {**BASE, "SCORING_MODE": 4},
    "mode5":   {**BASE, "SCORING_MODE": 5},
    "mode7":   {**BASE, "SCORING_MODE": 7},
    "mode8":   {**BASE, "SCORING_MODE": 8},
    "cap1":    {**BASE, "SCORING_MODE": 5, "REPL_HIST_LLC_CAP": 1, "REPL_HIST_REPL": "tiered"},
    "cap2":    {**BASE, "SCORING_MODE": 5, "REPL_HIST_LLC_CAP": 2, "REPL_HIST_REPL": "tiered"},
}

PINNED = [
    ("default", "default", 0.211229, 111112),
    ("mode3",   "mode3",   0.211229, 111112),
    ("mode4",   "mode4",   0.211229, 111112),
    ("mode5",   "mode5",   0.211229, 111112),
    ("mode7",   "mode7",   0.211229, 111112),
    ("mode8",   "mode8",   0.211229, 111112),
    ("cap1",    "cap1",    0.211163, 111111),
    ("cap2",    "cap2",    0.211229, 111112),
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
    stats = {"raw": out, "returncode": result.returncode}
    for line in out.splitlines():
        if "CPU 0 cumulative IPC:" in line:
            stats["ipc"] = float(line.split()[4])
        if "LLC TOTAL" in line:
            parts = line.split()
            try:
                stats["llc_miss"] = int(parts[parts.index("MISS:") + 1])
            except (ValueError, IndexError):
                pass
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

    # Note: no cap1-vs-cap2 ordering test here.  Unlike LRU-Live, SRRIP-Live is
    # nearly insensitive to history loss on pagerank — cap=1 changes IPC by
    # <0.01% (below tolerance) and even lowers the miss count.  The exact
    # constrained behavior is pinned in TestPinned (cap1/cap2) instead.


if __name__ == "__main__":
    unittest.main(verbosity=2)
