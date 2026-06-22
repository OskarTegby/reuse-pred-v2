"""Blackbox reference tests for REPL_HIST_HASH_BITS (fold-XOR PC hash).

Runs bin/champsim_srrip_live on trace-files/pagerank.champsimtrace.xz with
W=1M/S=2M and verifies key invariants for the PC-hash feature added in commit
0e8813d:
  - hash=0 (default, identity): identical to no-hash reference
  - hash=10: no IPC change — pagerank has only 4 unique PCs, no collision at 1024 slots
  - hash=2: IPC still stable — 4 PCs still distribute cleanly into 4 XOR buckets
  - bounded table + hash: occupancy stats still printed correctly
  - simulator exits cleanly for all hash widths tested

Expected IPC values are pinned from a reference run (June 2026, git: main post
repl-hist-pc-hash merge).

Tolerance: ±0.01% on IPC.
"""

import os
import subprocess
import unittest
from pathlib import Path

ROOT  = Path(__file__).resolve().parents[2]
BIN   = ROOT / "bin" / "champsim_srrip_live"
TRACE = ROOT / "trace-files" / "pagerank.champsimtrace.xz"

WARMUP = "1000000"
SIM    = "2000000"

# Pinned from reference run — mode5, no hash (June 2026)
IPC_MODE5_NOHASH = 0.211229
LLC_MISS_NOHASH  = 111112

IPC_TOL = 0.0001  # absolute IPC tolerance

BASE_ENV = dict(
    THD_DOA=6,
    THD_DEAD=10,
    SCORING_MODE=5,
    SRRIP_LIVE_TARGET="llc",
)


def run_sim(env_extra: dict) -> dict:
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
        if "LLC repl_hist:" in line and "unbounded" in line:
            stats["hist_unbounded"] = True
            for tok in line.split():
                if tok.startswith("(") and tok[1:].isdigit():
                    stats["hist_used"] = int(tok[1:])
            for tok in line.split():
                if tok.startswith("scoring_mode="):
                    stats["scoring_mode"] = int(tok.split("=")[1])
        if "LLC repl_hist occupancy" in line and "main" in line:
            for tok in line.split():
                if "/" in tok and tok[0].isdigit():
                    used, cap = tok.split("/")
                    stats["hist_used"] = int(used)
                    stats["hist_cap"]  = int(cap.rstrip(")"))
                    break

    return stats


@unittest.skipUnless(BIN.exists(),   f"binary not found: {BIN}")
@unittest.skipUnless(TRACE.exists(), f"trace not found: {TRACE}")
class TestReplHistHashBits(unittest.TestCase):
    """REPL_HIST_HASH_BITS — unbounded table with fold-XOR hashing."""

    def test_no_hash_baseline_ipc(self):
        s = run_sim(BASE_ENV)
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], IPC_MODE5_NOHASH, delta=IPC_TOL)

    def test_no_hash_llc_miss(self):
        s = run_sim(BASE_ENV)
        self.assertEqual(s.get("llc_miss"), LLC_MISS_NOHASH)

    def test_hash10_ipc_matches_nohash(self):
        # 10-bit hash → 1024 slots; pagerank has 4 PCs — no collision expected
        s = run_sim({**BASE_ENV, "REPL_HIST_HASH_BITS": 10})
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], IPC_MODE5_NOHASH, delta=IPC_TOL,
                               msg="hash=10 should not change IPC on pagerank (no collision)")

    def test_hash10_llc_miss_unchanged(self):
        s = run_sim({**BASE_ENV, "REPL_HIST_HASH_BITS": 10})
        self.assertEqual(s.get("llc_miss"), LLC_MISS_NOHASH)

    def test_hash2_ipc_matches_nohash(self):
        # 2-bit hash → 4 slots; pagerank's 4 PCs happen to distribute cleanly
        s = run_sim({**BASE_ENV, "REPL_HIST_HASH_BITS": 2})
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], IPC_MODE5_NOHASH, delta=IPC_TOL)

    def test_hash10_hist_still_unbounded(self):
        s = run_sim({**BASE_ENV, "REPL_HIST_HASH_BITS": 10})
        self.assertTrue(s.get("hist_unbounded"),
                        msg="hash=10 without REPL_HIST_LLC_CAP should still be unbounded")

    def test_hash10_hist_entry_count_unchanged(self):
        s_no  = run_sim(BASE_ENV)
        s_h10 = run_sim({**BASE_ENV, "REPL_HIST_HASH_BITS": 10})
        self.assertEqual(s_no.get("hist_used"), s_h10.get("hist_used"),
                         msg="hash=10 must not change the number of unique history entries on pagerank")


@unittest.skipUnless(BIN.exists(),   f"binary not found: {BIN}")
@unittest.skipUnless(TRACE.exists(), f"trace not found: {TRACE}")
class TestReplHistHashBitsBounded(unittest.TestCase):
    """REPL_HIST_HASH_BITS combined with a bounded history table."""

    def _run(self, hash_bits, cap=256):
        return run_sim({
            **BASE_ENV,
            "REPL_HIST_HASH_BITS": hash_bits,
            "REPL_HIST_LLC_CAP":   cap,
            "REPL_HIST_REPL":      "tiered",
        })

    def test_bounded_hash10_returncode(self):
        s = self._run(10)
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])

    def test_bounded_hash10_ipc_stable(self):
        # cap=256 is never saturated on pagerank (only 4 PCs) → same IPC as unbounded
        s = self._run(10)
        self.assertAlmostEqual(s["ipc"], IPC_MODE5_NOHASH, delta=IPC_TOL)

    def test_bounded_hash10_occupancy_reported(self):
        s = self._run(10)
        self.assertIn("hist_used", s, msg="bounded+hash must report occupancy")
        self.assertIn("hist_cap",  s, msg="bounded+hash must report capacity")

    def test_bounded_hash10_cap_matches_requested(self):
        s = self._run(10, cap=256)
        self.assertEqual(s.get("hist_cap"), 256)

    def test_bounded_hash10_occupancy_nonzero(self):
        s = self._run(10)
        self.assertGreater(s.get("hist_used", 0), 0)

    def test_bounded_hash10_occupancy_within_cap(self):
        s = self._run(10)
        self.assertLessEqual(s.get("hist_used", 0), s.get("hist_cap", 0))

    def test_bounded_hash2_returncode(self):
        s = self._run(2)
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
