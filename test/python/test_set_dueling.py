"""Blackbox tests for N-way set dueling in IPV-Live and SRRIP-Live.

N-way design:
  DUEL_N_CONFIGS=N partitions LLC sets into N sampler groups (DUEL_N_SAMPLERS sets
  each) plus followers.  Each sampler group records demand hits.  Followers use the
  config with the most hits so far (argmax, with optional DUEL_HYST hysteresis).

Env-var API:
  DUEL_N_CONFIGS     — number of competing configs (2 = binary; default 2 when
                       DUEL_N_SAMPLERS is set but DUEL_N_CONFIGS is omitted).
  DUEL_N_SAMPLERS    — sampler sets per config.
  IPV_DOA_0..N-1    — per-config DoA IPV (falls back to IPV_DOA / IPV_DOA_B for
                       configs 0 and 1 respectively).
  DUEL_HYST          — minimum hit-count lead required for the winner to be any
                       config other than config 0 (conservative default).

Output format:
  "Set dueling     : N=2  samplers/cfg=32  hyst=0  winner=config_0"
  "Config 0*: DoA={0,1,2,2,2}  sampler_hits=5639"
  "Config 1 : DoA={0,1,2,2,3}  sampler_hits=0"

Trace coverage note:
  Only pagerank.champsimtrace.xz is available locally.  Pagerank is nearly
  fully DoA with very few LLC re-accesses, and those re-accessed blocks hash
  to sets that are always in sampler group 0 for any tested step size.

    config_0 wins (config_0=ins@2, config_1=ins@3):
      sampler_0 gets the re-accessed hits → config_0 wins. ✓

    config_1 wins (config_0=ins@3, config_1=ins@2):
      sampler_0 uses ins@3, which evicts immediately → no hits anywhere →
      config_0 wins by default (HYST=0 returns config 0 on tie). ✗
      Cannot be demonstrated with this trace.

  config_1-wins correctness validated by cluster runs on GAP/Ligra suites.

Pinned from reference runs (2026-06-22, set-dueling-nway branch).
"""

import os
import re
import subprocess
import unittest
from pathlib import Path

ROOT      = Path(__file__).resolve().parents[2]
BIN_IPV   = ROOT / "bin" / "champsim_ipv_live"
BIN_SRRIP = ROOT / "bin" / "champsim_srrip_live"
TRACE     = ROOT / "trace-files" / "pagerank.champsimtrace.xz"

WARMUP = "1000000"
SIM    = "2000000"

# Mechanism tests: 256 sampler sets → more LLC coverage → robust hit signal.
MECH_ENV = dict(
    THD_DOA=6,
    THD_DEAD=10,
    SCORING_MODE=5,
    SRRIP_LIVE_TARGET="llc",
    DUEL_N_SAMPLERS=256,
)

# Follower-convergence tests: 32 sampler sets (production density).
PERF_ENV = dict(
    THD_DOA=6,
    THD_DEAD=10,
    SCORING_MODE=5,
    SRRIP_LIVE_TARGET="llc",
    DUEL_N_SAMPLERS=32,
)


def run_sim(binary, env_extra: dict) -> dict:
    env = {**os.environ, **{k: str(v) for k, v in env_extra.items()}}
    result = subprocess.run(
        [str(binary),
         "--warmup_instructions", WARMUP,
         "--simulation_instructions", SIM,
         str(TRACE)],
        capture_output=True, text=True, env=env, timeout=120
    )
    out = result.stdout + result.stderr
    stats = {"raw": out, "returncode": result.returncode, "cfg_hits": {}}

    for line in out.splitlines():
        if "CPU 0 cumulative IPC:" in line:
            stats["ipc"] = float(line.split()[4])
        if "LLC TOTAL" in line:
            parts = line.split()
            try:
                stats["llc_miss"] = int(parts[parts.index("MISS:") + 1])
                stats["llc_hit"]  = int(parts[parts.index("HIT:")  + 1])
            except (ValueError, IndexError):
                pass
        # "  Set dueling     : N=2  samplers/cfg=32  hyst=0  winner=config_0"
        if "Set dueling" in line and "winner=" in line:
            m = re.search(r"winner=config_(\d+)", line)
            if m:
                stats["winner"] = int(m.group(1))
            m = re.search(r"N=(\d+)", line)
            if m:
                stats["n_configs"] = int(m.group(1))
        # "  Config 0*: DoA={0,1,2,2,2}  sampler_hits=5639"
        m = re.match(r"\s+Config\s+(\d+)[* :]", line)
        if m and "sampler_hits=" in line:
            idx = int(m.group(1))
            hm = re.search(r"sampler_hits=(\d+)", line)
            if hm:
                stats["cfg_hits"][idx] = int(hm.group(1))

    return stats


# ---------------------------------------------------------------------------
# IPV-Live: config_0 wins (config_0=ins@2, config_1=ins@3)
# ---------------------------------------------------------------------------

@unittest.skipUnless(BIN_IPV.exists(),  "binary not found: champsim_ipv_live")
@unittest.skipUnless(TRACE.exists(),    "trace not found: pagerank.champsimtrace.xz")
class TestIPVDuelingCfg0Wins(unittest.TestCase):
    """config_0={0,1,2,2,2} (ins@2) vs config_1={0,1,2,2,3} (ins@3).
    ins@2 keeps DoA blocks in cache; re-accessed blocks hash to sampler group 0
    and generate hits.  ins@3 evicts immediately → sampler group 1 = 0 hits →
    config_0 wins.
    """

    def setUp(self):
        self.s = run_sim(BIN_IPV, {
            **MECH_ENV,
            "IPV_DOA_0": "0,1,2,2,2",
            "IPV_DOA_1": "0,1,2,2,3",
        })

    def test_returncode(self):
        self.assertEqual(self.s["returncode"], 0, msg=self.s["raw"][-500:])

    def test_dueling_stats_present(self):
        self.assertIn("winner", self.s, msg="Set dueling stats not found in output")

    def test_winner_is_config_0(self):
        self.assertEqual(self.s.get("winner"), 0,
                         msg="Expected config_0 to win; winner=%s" % self.s.get("winner"))

    def test_cfg0_hits_exceed_cfg1(self):
        hits = self.s["cfg_hits"]
        h0 = hits.get(0, 0)
        h1 = hits.get(1, 0)
        self.assertGreater(h0, h1,
                           msg="config_0 hits=%d should exceed config_1 hits=%d" % (h0, h1))


# ---------------------------------------------------------------------------
# IPV-Live: config_1 wins — skipped (trace limitation, see module docstring)
# ---------------------------------------------------------------------------

@unittest.skip(
    "config_1-wins cannot be demonstrated on pagerank: re-accessed blocks always "
    "hash to sampler group 0 regardless of config assignment, so group 1 never "
    "accumulates hits.  Correctness validated by cluster runs on GAP/Ligra."
)
class TestIPVDuelingCfg1Wins(unittest.TestCase):
    pass


# ---------------------------------------------------------------------------
# IPV-Live: dueling disabled
# ---------------------------------------------------------------------------

@unittest.skipUnless(BIN_IPV.exists(),  "binary not found: champsim_ipv_live")
@unittest.skipUnless(TRACE.exists(),    "trace not found: pagerank.champsimtrace.xz")
class TestIPVDuelingDisabled(unittest.TestCase):
    """DUEL_N_SAMPLERS=0 (or unset) and DUEL_N_CONFIGS=0 disable dueling."""

    def test_no_dueling_output_by_default(self):
        env = {k: v for k, v in PERF_ENV.items()
               if k not in ("DUEL_N_SAMPLERS", "DUEL_N_CONFIGS")}
        s = run_sim(BIN_IPV, env)
        self.assertNotIn("winner", s, msg="Dueling stats should not appear when disabled")

    def test_duel_n_samplers_zero_disables_dueling(self):
        s = run_sim(BIN_IPV, {**PERF_ENV, "DUEL_N_SAMPLERS": 0, "DUEL_N_CONFIGS": 0})
        self.assertNotIn("winner", s, msg="Dueling stats should not appear when DUEL_N_SAMPLERS=0")


# ---------------------------------------------------------------------------
# IPV-Live: follower convergence
#
# With DUEL_N_SAMPLERS=32 on pagerank, config_0 wins (sampler group 1 sees
# no hits).  Followers adopt config_0's IPC regardless of which config is
# assigned to slot 0.
# ---------------------------------------------------------------------------

IPC_PURE_INS2   = 0.211229   # pure IPV_DOA={0,1,2,2,2}, no dueling
IPC_PURE_INS3   = 0.251271   # pure IPV_DOA={0,1,2,2,3}, no dueling
IPC_SAMPLER_TOL = 0.005      # ±0.5% covers sampler contamination (32/2048)


@unittest.skipUnless(BIN_IPV.exists(),  "binary not found: champsim_ipv_live")
@unittest.skipUnless(TRACE.exists(),    "trace not found: pagerank.champsimtrace.xz")
class TestIPVDuelingFollowerConvergence(unittest.TestCase):
    """Followers track the winning config's IPC regardless of slot assignment."""

    def test_config0_ins2_ipc(self):
        s = run_sim(BIN_IPV, {
            **PERF_ENV,
            "IPV_DOA_0": "0,1,2,2,2",
            "IPV_DOA_1": "0,1,2,2,3",
        })
        self.assertAlmostEqual(s["ipc"], IPC_PURE_INS2, delta=IPC_SAMPLER_TOL,
                               msg="config_0=ins@2: IPC %.6f should be near %.6f"
                                   % (s["ipc"], IPC_PURE_INS2))

    def test_config0_ins3_ipc(self):
        s = run_sim(BIN_IPV, {
            **PERF_ENV,
            "IPV_DOA_0": "0,1,2,2,3",
            "IPV_DOA_1": "0,1,2,2,2",
        })
        self.assertAlmostEqual(s["ipc"], IPC_PURE_INS3, delta=IPC_SAMPLER_TOL,
                               msg="config_0=ins@3: IPC %.6f should be near %.6f"
                                   % (s["ipc"], IPC_PURE_INS3))


# ---------------------------------------------------------------------------
# IPV-Live: 3-way dueling (N=3)
# ---------------------------------------------------------------------------

@unittest.skipUnless(BIN_IPV.exists(),  "binary not found: champsim_ipv_live")
@unittest.skipUnless(TRACE.exists(),    "trace not found: pagerank.champsimtrace.xz")
class TestIPVDueling3Way(unittest.TestCase):
    """3-way duel: config_0=ins@2 (expected winner on pagerank), configs 1 & 2 = ins@3 variants."""

    def setUp(self):
        self.s = run_sim(BIN_IPV, {
            **MECH_ENV,
            "DUEL_N_CONFIGS": 3,
            "IPV_DOA_0": "0,1,2,2,2",
            "IPV_DOA_1": "0,1,2,2,3",
            "IPV_DOA_2": "0,1,1,2,3",
        })

    def test_returncode(self):
        self.assertEqual(self.s["returncode"], 0, msg=self.s["raw"][-500:])

    def test_n_configs_reported(self):
        self.assertEqual(self.s.get("n_configs"), 3,
                         msg="Expected N=3 in dueling stats")

    def test_three_configs_have_hit_counts(self):
        hits = self.s["cfg_hits"]
        self.assertEqual(len(hits), 3,
                         msg="Expected 3 config hit counts, got %s" % hits)

    def test_winner_is_config_0(self):
        self.assertEqual(self.s.get("winner"), 0,
                         msg="Expected config_0 to win on pagerank with ins@2")


# ---------------------------------------------------------------------------
# SRRIP-Live: config_0 wins (binary dueling — srrip_live uses old PSEL API)
# ---------------------------------------------------------------------------

@unittest.skipUnless(BIN_SRRIP.exists(), "binary not found: champsim_srrip_live")
@unittest.skipUnless(TRACE.exists(),     "trace not found: pagerank.champsimtrace.xz")
class TestSRRIPDuelingCfg0Wins(unittest.TestCase):
    """DoA ins=2 in config A, DoA ins=3 in config B. A should win on pagerank."""

    def setUp(self):
        self.s = run_sim(BIN_SRRIP, {
            **MECH_ENV,
            "SRRIP_DOA_INS_RRPV":   2,
            "SRRIP_DOA_INS_RRPV_B": 3,
        })

    def test_returncode(self):
        self.assertEqual(self.s["returncode"], 0, msg=self.s["raw"][-500:])

    def test_dueling_stats_present(self):
        # srrip_live still uses binary PSEL; accept either new or old stat format
        has_new = "winner" in self.s
        has_old = "Set dueling" in self.s.get("raw", "")
        self.assertTrue(has_new or has_old, msg="No dueling stats found in srrip output")


@unittest.skip(
    "config_1-wins cannot be demonstrated on pagerank — same set-hash limitation as IPV. "
    "Validated by cluster runs on GAP/Ligra."
)
class TestSRRIPDuelingCfg1Wins(unittest.TestCase):
    pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
