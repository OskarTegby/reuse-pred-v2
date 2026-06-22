"""Blackbox reference tests for IPV-Live replacement policy.

Runs bin/champsim_ipv_live on trace-files/pagerank.champsimtrace.xz with
W=1M/S=2M (fast) and verifies key invariants:
  - Default run (no env vars): stable IPC and LLC miss count
  - Canonical config (THD_DOA=6, THD_DEAD=10, SCORING_MODE=5, SRRIP_LIVE_TARGET=llc)
  - parse_ipv delimiter fix: colon-separated IPV vectors parse all 5 elements
  - Comma and colon delimiters produce identical results
  - Activation rate and insert-mix sanity checks

Expected IPC values are pinned from a reference run (June 2026, git: main post
repl-hist-pc-hash merge).

Tolerance: ±0.01% on IPC.
"""

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BIN  = ROOT / "bin" / "champsim_ipv_live"
TRACE = ROOT / "trace-files" / "pagerank.champsimtrace.xz"

WARMUP = "1000000"
SIM    = "2000000"

# Pinned from reference run (default config, no env overrides)
IPC_DEFAULT  = 0.211229
LLC_MISS_DEFAULT = 111112

# Pinned from canonical config (THD_DOA=6, THD_DEAD=10, SCORING_MODE=5, SRRIP_LIVE_TARGET=llc)
# Identical to default because pagerank is 100% DoA — predictor makes no replacement change
IPC_CANONICAL = 0.211229

# Pinned for custom IPV_DOA={0,1,2,2,3} (insert@3 instead of default 2)
# This changes eviction priority and therefore IPC
IPC_DOA_INS3 = 0.251271

IPC_TOL = 0.0001  # absolute IPC tolerance


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
        if "Activation rate" in line:
            # "Activation rate : 100.0%  (N guided / M total insertions)"
            for tok in line.split():
                if tok.endswith("%"):
                    try:
                        stats["activation_pct"] = float(tok.rstrip("%"))
                    except ValueError:
                        pass
        if "Insert mix" in line:
            stats["insert_mix_line"] = line
        if "IPV_doa" in line and ":" in line:
            # "  IPV_doa         : {0,1,2,2,2}"
            bracket = line[line.index("{"):line.index("}") + 1]
            stats["ipv_doa"] = list(map(int, bracket.strip("{}").split(",")))
        if "LLC repl_hist:" in line:
            if "unbounded" in line:
                stats["hist_unbounded"] = True
            if "scoring_mode=" in line:
                for tok in line.split():
                    if tok.startswith("scoring_mode="):
                        stats["scoring_mode"] = int(tok.split("=")[1])

    return stats


BASE_ENV = dict(
    THD_DOA=6,
    THD_DEAD=10,
    SCORING_MODE=5,
    SRRIP_LIVE_TARGET="llc",
)


@unittest.skipUnless(BIN.exists(),   f"binary not found: {BIN}")
@unittest.skipUnless(TRACE.exists(), f"trace not found: {TRACE}")
class TestIPVLiveDefault(unittest.TestCase):
    """Default run — no env overrides."""

    def setUp(self):
        self.s = run_sim({})

    def test_returncode(self):
        self.assertEqual(self.s["returncode"], 0, msg=self.s["raw"][-500:])

    def test_ipc(self):
        self.assertAlmostEqual(self.s["ipc"], IPC_DEFAULT, delta=IPC_TOL)

    def test_llc_miss(self):
        self.assertEqual(self.s.get("llc_miss"), LLC_MISS_DEFAULT)

    def test_default_ipv_doa_vector(self):
        # Default IPV_DOA = {0,1,2,2,2}
        self.assertEqual(self.s.get("ipv_doa"), [0, 1, 2, 2, 2])

    def test_default_scoring_mode(self):
        # Without SCORING_MODE the binary defaults to mode 2
        self.assertEqual(self.s.get("scoring_mode"), 2)


@unittest.skipUnless(BIN.exists(),   f"binary not found: {BIN}")
@unittest.skipUnless(TRACE.exists(), f"trace not found: {TRACE}")
class TestIPVLiveCanonical(unittest.TestCase):
    """Canonical config: THD_DOA=6, THD_DEAD=10, SCORING_MODE=5, SRRIP_LIVE_TARGET=llc."""

    def setUp(self):
        self.s = run_sim(BASE_ENV)

    def test_returncode(self):
        self.assertEqual(self.s["returncode"], 0, msg=self.s["raw"][-500:])

    def test_ipc(self):
        self.assertAlmostEqual(self.s["ipc"], IPC_CANONICAL, delta=IPC_TOL)

    def test_scoring_mode_in_output(self):
        self.assertEqual(self.s.get("scoring_mode"), 5)

    def test_hist_is_unbounded(self):
        self.assertTrue(self.s.get("hist_unbounded"),
                        msg="no cap set — should report unbounded history table")

    def test_full_activation(self):
        # pagerank is 100% DoA — every insertion should be liveness-guided
        pct = self.s.get("activation_pct", 0.0)
        self.assertGreaterEqual(pct, 99.0,
                                msg=f"activation rate {pct}% unexpectedly low")

    def test_doa_dominated_insert_mix(self):
        line = self.s.get("insert_mix_line", "")
        self.assertIn("DoA=", line)
        # Extract DoA% — should be dominant for pagerank
        for tok in line.split():
            if tok.startswith("DoA="):
                doa_pct = float(tok.split("=")[1].rstrip("%"))
                self.assertGreater(doa_pct, 70.0,
                                   msg=f"DoA insertion mix {doa_pct}% unexpectedly low for pagerank")


@unittest.skipUnless(BIN.exists(),   f"binary not found: {BIN}")
@unittest.skipUnless(TRACE.exists(), f"trace not found: {TRACE}")
class TestIPVParseDelimiterFix(unittest.TestCase):
    """Verify the parse_ipv delimiter bug fix (commit b05e779).

    Before the fix: strtok used ',' only for continuation, so colon-separated
    strings were only partially parsed (elements 2-4 fell back to defaults).
    After the fix: both ',' and ':' are accepted throughout, so colon-separated
    and comma-separated strings are fully parsed and produce identical results.
    """

    def _run_with_ipv(self, ipv_str: str) -> dict:
        return run_sim({**BASE_ENV, "IPV_DOA": ipv_str})

    def test_colon_delimiter_parses_all_5_elements(self):
        s = self._run_with_ipv("0:1:2:2:3")
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        # All 5 elements must be parsed; element [4] is 3, not default 2
        self.assertEqual(s.get("ipv_doa"), [0, 1, 2, 2, 3],
                         msg="colon-separated IPV_DOA did not parse all 5 elements")

    def test_comma_delimiter_parses_all_5_elements(self):
        s = self._run_with_ipv("0,1,2,2,3")
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertEqual(s.get("ipv_doa"), [0, 1, 2, 2, 3])

    def test_colon_and_comma_produce_identical_ipc(self):
        s_colon = self._run_with_ipv("0:1:2:2:3")
        s_comma = self._run_with_ipv("0,1,2,2,3")
        self.assertAlmostEqual(s_colon["ipc"], s_comma["ipc"], delta=IPC_TOL,
                               msg="colon vs comma IPV_DOA should produce identical IPC")

    def test_colon_ipv_doa_ins3_ipc(self):
        # Pinned IPC for IPV_DOA={0,1,2,2,3} — insert@3 raises DoA insertion priority
        s = self._run_with_ipv("0:1:2:2:3")
        self.assertAlmostEqual(s["ipc"], IPC_DOA_INS3, delta=IPC_TOL,
                               msg=f"IPV_DOA={{0,1,2,2,3}} IPC {s.get('ipc')} != {IPC_DOA_INS3}")

    def test_custom_ipv_differs_from_default(self):
        # Sanity: {0,1,2,2,3} must produce different IPC from the default {0,1,2,2,2}
        s_custom = self._run_with_ipv("0,1,2,2,3")
        s_default = run_sim(BASE_ENV)
        self.assertNotAlmostEqual(s_custom["ipc"], s_default["ipc"], delta=IPC_TOL,
                                  msg="custom IPV and default IPV should differ in IPC")


if __name__ == "__main__":
    unittest.main(verbosity=2)
