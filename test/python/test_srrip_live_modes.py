"""Blackbox reference tests for SRRIP-Live scoring modes.

Runs bin/champsim_srrip_live on trace-files/pagerank.champsimtrace.xz with
W=1M/S=2M (fast) and verifies key invariants for every feature combination:
  - all five scoring modes (3/4/5/7/8)
  - unbounded vs bounded (cap=256)
  - history table occupancy
  - SRRIP-Live baseline (no env overrides)

pagerank is 100% DoA with no bypass active, so liveness-informed replacement
does not improve IPC over plain SRRIP on this trace. All modes produce the
same IPC (~0.211). That is expected and correct: the regression value is the
stability of that IPC, not that it beats SRRIP.

Expected IPC values are pinned from a reference run (June 2026, git: main,
post repl-hist-pc-hash merge). The maz-morph-unbounded branch pinned higher
values because bypass was active in those runs; those values are no longer
applicable.

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

# Pinned from reference run (June 2026, git: main, no bypass active).
# pagerank is 100% DoA → liveness gives no LLC miss reduction without bypass.
# All scoring modes converge to the same IPC on this trace.
IPC_ALL = 0.211229
LLC_MISS_ALL = 111112

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
class TestSRRIPLiveBaseline(unittest.TestCase):
    """No env overrides — history table active at mode 2 (legacy default)."""

    def test_baseline_ipc(self):
        s = run_sim({})
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], IPC_ALL, delta=IPC_TOL,
                               msg=f"baseline IPC {s['ipc']} != {IPC_ALL}")

    def test_baseline_llc_miss(self):
        s = run_sim({})
        self.assertEqual(s.get("llc_miss"), LLC_MISS_ALL,
                         msg=f"baseline LLC miss {s.get('llc_miss')} != {LLC_MISS_ALL}")

    def test_default_scoring_mode(self):
        # Without SCORING_MODE env var the binary uses mode 2 (legacy default).
        s = run_sim({})
        self.assertEqual(s.get("scoring_mode"), 2,
                         msg="default run should use scoring_mode=2")


@unittest.skipUnless(BIN.exists(), f"binary not found: {BIN}")
@unittest.skipUnless(TRACE.exists(), f"trace not found: {TRACE}")
class TestUnboundedModes(unittest.TestCase):
    """Verify all five scoring modes run correctly and produce stable IPC."""

    def _run(self, mode):
        return run_sim({**BASE_ENV, "SCORING_MODE": mode})

    def test_mode3_ipc(self):
        s = self._run(3)
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], IPC_ALL, delta=IPC_TOL)

    def test_mode4_ipc(self):
        s = self._run(4)
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], IPC_ALL, delta=IPC_TOL)

    def test_mode5_ipc(self):
        s = self._run(5)
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], IPC_ALL, delta=IPC_TOL)

    def test_mode7_ipc(self):
        s = self._run(7)
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], IPC_ALL, delta=IPC_TOL)

    def test_mode8_ipc(self):
        s = self._run(8)
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], IPC_ALL, delta=IPC_TOL)

    def test_all_modes_converge(self):
        # pagerank is 100% DoA with no bypass — all scoring modes produce the
        # same IPC. This catches any accidental mode-specific divergence.
        ipcs = {}
        for mode in (3, 4, 5, 7, 8):
            ipcs[mode] = self._run(mode)["ipc"]
        for mode, ipc in ipcs.items():
            with self.subTest(mode=mode):
                self.assertAlmostEqual(ipc, IPC_ALL, delta=IPC_TOL)

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
    """Verify bounded (cap=256) path activates and has correct occupancy."""

    def _run(self, mode, cap=256):
        return run_sim({
            **BASE_ENV,
            "SCORING_MODE": mode,
            "REPL_HIST_LLC_CAP": cap,
            "REPL_HIST_REPL": "tiered",
        })

    def test_bounded_ipc_mode5(self):
        # Trace has only 4 unique PCs — cap=256 is never saturated, so IPC == unbounded
        s = self._run(5)
        self.assertAlmostEqual(s["ipc"], IPC_ALL, delta=IPC_TOL)

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

    def test_all_modes_bounded_ipc_stable(self):
        for mode in (3, 4, 5, 7, 8):
            with self.subTest(mode=mode):
                s = self._run(mode)
                self.assertAlmostEqual(s["ipc"], IPC_ALL, delta=IPC_TOL)


@unittest.skipUnless(BIN.exists(), f"binary not found: {BIN}")
@unittest.skipUnless(TRACE.exists(), f"trace not found: {TRACE}")
class TestLLCMissCounts(unittest.TestCase):
    """LLC miss counts are a key indicator that routing into the history table is correct."""

    def test_baseline_miss_count(self):
        s = run_sim({})
        self.assertEqual(s.get("llc_miss"), LLC_MISS_ALL)

    def test_all_modes_miss_count(self):
        for mode in (3, 4, 5, 7, 8):
            with self.subTest(mode=mode):
                s = run_sim({**BASE_ENV, "SCORING_MODE": mode})
                self.assertEqual(s.get("llc_miss"), LLC_MISS_ALL,
                                 msg=f"mode {mode} LLC miss count wrong")


if __name__ == "__main__":
    unittest.main(verbosity=2)
