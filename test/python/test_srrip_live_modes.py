"""Blackbox reference tests for SRRIP-Live scoring modes.

Runs bin/champsim_srrip_live on trace-files/pagerank.champsimtrace.xz with
W=1M/S=2M (fast) and verifies key invariants for every feature combination:
  - all five scoring modes (3/4/5/7/8)
  - unbounded vs bounded (cap=256)
  - history table occupancy
  - SRRIP baseline (no liveness tracking)

Expected IPC values are pinned from a reference run and must remain stable
across code changes unless the simulator logic changes intentionally.

Tolerance: ±0.01% on IPC (covers fp rounding differences between builds).
"""

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / "bin" / "champsim_srrip_live"
TRACE = ROOT / "trace-files" / "pagerank.champsimtrace.xz"

WARMUP = "1000000"
SIM = "2000000"

# Pinned expected values from reference run (June 2026, git: maz-morph-unbounded)
# Slow classifiers (MA dd=1): modes 3, 7, 8
IPC_SLOW = 0.25177
# Fast classifiers (MA dd≥3): modes 4, 5
IPC_FAST = 0.251271
# SRRIP (no liveness tracking)
IPC_SRRIP = 0.250658

LLC_MISS_SRRIP = 166650
LLC_MISS_SLOW = 166650
LLC_MISS_FAST = 166653

IPC_TOL = 0.0001   # absolute IPC tolerance


def run_sim(env_extra: dict) -> dict:
    """Run the simulator and return a dict of key stats."""
    env = {**os.environ, **{k: str(v) for k, v in env_extra.items()}}
    result = subprocess.run(
        [str(BIN),
         "--warmup_instructions", WARMUP,
         "--simulation_instructions", SIM,
         str(TRACE)],
        capture_output=True, text=True, env=env, timeout=120
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
        if "LLC repl_hist occupancy" in line and "main" in line:
            # "main 5/256 (2%)"
            for tok in line.split():
                if "/" in tok and tok[0].isdigit():
                    used, cap = tok.split("/")
                    stats["hist_used"] = int(used)
                    stats["hist_cap"] = int(cap.rstrip(")"))
                    break
        if "LLC repl_hist:" in line and "unbounded" in line:
            stats["hist_unbounded"] = True
            # Format: "LLC repl_hist: unbounded (5 entries)  scoring_mode=N"
            # "(5" and "entries)" are separate tokens — match "(N" prefix.
            for tok in line.split():
                if tok.startswith("(") and tok[1:].isdigit():
                    stats["hist_used"] = int(tok[1:])
                    break
        if "scoring_mode=" in line:
            for tok in line.split():
                if tok.startswith("scoring_mode="):
                    stats["scoring_mode"] = int(tok.split("=")[1])

    return stats


BASE_ENV = dict(
    THD_DOA=6,
    THD_DEAD=10,
    BHIST_MODE="pc",
    SRRIP_LIVE_TARGET="llc",
)


@unittest.skipUnless(BIN.exists(), f"binary not found: {BIN}")
@unittest.skipUnless(TRACE.exists(), f"trace not found: {TRACE}")
class TestSRRIPBaseline(unittest.TestCase):

    def test_srrip_ipc(self):
        s = run_sim({})
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], IPC_SRRIP, delta=IPC_TOL,
                               msg=f"SRRIP IPC {s['ipc']} != {IPC_SRRIP}")

    def test_srrip_llc_miss(self):
        s = run_sim({})
        self.assertEqual(s.get("llc_miss"), LLC_MISS_SRRIP,
                         msg=f"SRRIP LLC miss {s.get('llc_miss')} != {LLC_MISS_SRRIP}")

    def test_default_scoring_mode(self):
        # Without SCORING_MODE env var the binary uses mode 2 (legacy default).
        # The history table is always active; mode 2 is not one of our study modes.
        s = run_sim({})
        self.assertEqual(s.get("scoring_mode"), 2,
                         msg="default run should use scoring_mode=2")


@unittest.skipUnless(BIN.exists(), f"binary not found: {BIN}")
@unittest.skipUnless(TRACE.exists(), f"trace not found: {TRACE}")
class TestUnboundedModes(unittest.TestCase):
    """Verify all five scoring modes work and produce the expected split."""

    def _run(self, mode):
        return run_sim({**BASE_ENV, "SCORING_MODE": mode})

    def test_mode3_ipc(self):
        s = self._run(3)
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], IPC_SLOW, delta=IPC_TOL)

    def test_mode4_ipc(self):
        s = self._run(4)
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], IPC_FAST, delta=IPC_TOL)

    def test_mode5_ipc(self):
        s = self._run(5)
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], IPC_FAST, delta=IPC_TOL)

    def test_mode7_ipc(self):
        s = self._run(7)
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], IPC_SLOW, delta=IPC_TOL)

    def test_mode8_ipc(self):
        s = self._run(8)
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], IPC_SLOW, delta=IPC_TOL)

    def test_all_beat_srrip(self):
        for mode in (3, 4, 5, 7, 8):
            with self.subTest(mode=mode):
                s = self._run(mode)
                self.assertGreater(s["ipc"], IPC_SRRIP,
                                   msg=f"mode {mode} IPC {s['ipc']} ≤ SRRIP {IPC_SRRIP}")

    def test_slow_vs_fast_differ(self):
        s3 = self._run(3)
        s5 = self._run(5)
        self.assertNotAlmostEqual(s3["ipc"], s5["ipc"], delta=IPC_TOL,
                                  msg="modes 3 and 5 should differ on this trace")

    def test_modes_3_7_8_match(self):
        # All slow classifiers (MA dd=1) produce identical output
        s3 = self._run(3)
        s7 = self._run(7)
        s8 = self._run(8)
        self.assertAlmostEqual(s3["ipc"], s7["ipc"], delta=IPC_TOL)
        self.assertAlmostEqual(s3["ipc"], s8["ipc"], delta=IPC_TOL)

    def test_modes_4_5_match(self):
        # Fast classifiers (MA dd≥3) produce identical output on this trace
        s4 = self._run(4)
        s5 = self._run(5)
        self.assertAlmostEqual(s4["ipc"], s5["ipc"], delta=IPC_TOL)

    def test_unbounded_scoring_mode_in_output(self):
        for mode in (3, 4, 5, 7, 8):
            with self.subTest(mode=mode):
                s = self._run(mode)
                self.assertEqual(s.get("scoring_mode"), mode,
                                 msg=f"scoring_mode not printed or wrong in output")

    def test_unbounded_hist_is_unbounded(self):
        s = self._run(5)
        self.assertTrue(s.get("hist_unbounded"),
                        msg="unbounded run should print 'LLC repl_hist: unbounded'")

    def test_unbounded_has_entries(self):
        s = self._run(5)
        used = s.get("hist_used", 0)
        self.assertGreater(used, 0,
                           msg="history table should have at least one entry after warmup")


@unittest.skipUnless(BIN.exists(), f"binary not found: {BIN}")
@unittest.skipUnless(TRACE.exists(), f"trace not found: {TRACE}")
class TestBoundedModes(unittest.TestCase):
    """Verify bounded (cap=256) path activates and matches unbounded on this trace."""

    def _run(self, mode, cap=256):
        return run_sim({
            **BASE_ENV,
            "SCORING_MODE": mode,
            "REPL_HIST_LLC_CAP": cap,
            "REPL_HIST_REPL": "tiered",
        })

    def test_bounded_ipc_matches_unbounded_mode5(self):
        # Trace has only 5 unique PCs — cap=256 is never full, so bounded == unbounded
        s = self._run(5)
        self.assertAlmostEqual(s["ipc"], IPC_FAST, delta=IPC_TOL)

    def test_bounded_occupancy_reported(self):
        s = self._run(5)
        self.assertIn("hist_used", s, msg="bounded path must print occupancy stats")
        self.assertIn("hist_cap", s, msg="bounded path must print occupancy stats")

    def test_bounded_cap_matches_requested(self):
        s = self._run(5, cap=256)
        self.assertEqual(s.get("hist_cap"), 256)

    def test_bounded_occupancy_nonzero(self):
        s = self._run(5)
        self.assertGreater(s.get("hist_used", 0), 0)

    def test_bounded_occupancy_within_cap(self):
        s = self._run(5)
        self.assertLessEqual(s.get("hist_used", 0), s.get("hist_cap", 0))

    def test_all_modes_bounded_ipc_positive(self):
        for mode in (3, 4, 5, 7, 8):
            with self.subTest(mode=mode):
                s = self._run(mode)
                self.assertGreater(s.get("ipc", 0), 0)

    def test_slow_fast_split_preserved_in_bounded(self):
        s3 = self._run(3)
        s5 = self._run(5)
        # IPC split must survive the bounded path
        self.assertAlmostEqual(s3["ipc"], IPC_SLOW, delta=IPC_TOL)
        self.assertAlmostEqual(s5["ipc"], IPC_FAST, delta=IPC_TOL)


@unittest.skipUnless(BIN.exists(), f"binary not found: {BIN}")
@unittest.skipUnless(TRACE.exists(), f"trace not found: {TRACE}")
class TestLLCMissCounts(unittest.TestCase):
    """LLC miss counts are a key indicator that routing into the history table is correct."""

    def test_srrip_miss_count(self):
        s = run_sim({})
        self.assertEqual(s.get("llc_miss"), LLC_MISS_SRRIP)

    def test_slow_modes_miss_count(self):
        for mode in (3, 7, 8):
            with self.subTest(mode=mode):
                s = run_sim({**BASE_ENV, "SCORING_MODE": mode})
                self.assertEqual(s.get("llc_miss"), LLC_MISS_SLOW,
                                 msg=f"mode {mode} LLC miss count wrong")

    def test_fast_modes_miss_count(self):
        for mode in (4, 5):
            with self.subTest(mode=mode):
                s = run_sim({**BASE_ENV, "SCORING_MODE": mode})
                self.assertEqual(s.get("llc_miss"), LLC_MISS_FAST,
                                 msg=f"mode {mode} LLC miss count wrong")


if __name__ == "__main__":
    unittest.main(verbosity=2)
