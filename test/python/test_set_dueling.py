"""Black-box regression tests for set dueling in IPV-Live and SRRIP-Live.

Each pinned test fixes the end-to-end IPC for a specific duel configuration.
The IPC reflects both sampler contamination and follower convergence — a change
to the dueling mechanism (sampler partitioning, hit counting, winner selection)
will shift these numbers.

Ordering test: assigning the higher-IPC config (ins@3 on a DoA trace) to
sampler group 0 must produce higher IPC than assigning ins@2, because cfg0
wins by default on tie and followers adopt its insertion policy.  This
directly tests that follower sets converge to the winning config's behavior.

Note: config_1-wins cannot be demonstrated on pagerank because re-accessed
blocks always hash to sampler group 0 regardless of config assignment.
Correctness for that case is validated by cluster runs on GAP/Ligra.

Trace: pagerank.champsimtrace.xz (100% DoA, 4 unique PCs).
Pinned: June 2026, main branch, post duel-miss-latency merge.
"""

import os
import subprocess
import unittest
from pathlib import Path

ROOT      = Path(__file__).resolve().parents[2]
BIN_IPV   = ROOT / "bin" / "champsim_ipv_live"
BIN_SRRIP = ROOT / "bin" / "champsim_srrip_live"
TRACE     = ROOT / "trace-files" / "pagerank.champsimtrace.xz"

WARMUP  = "1000000"
SIM     = "2000000"
IPC_TOL = 0.0001

BASE_IPV   = dict(THD_DOA=6, THD_DEAD=10, SCORING_MODE=5,
                  SRRIP_LIVE_TARGET="llc", DUEL_N_SAMPLERS=256)
BASE_SRRIP = dict(THD_DOA=6, THD_DEAD=10, BHIST_MODE="pc",
                  SRRIP_LIVE_TARGET="llc", SCORING_MODE=5, DUEL_N_SAMPLERS=256)

_CONFIGS = {
    "ipv_cfg0_ins2": {**BASE_IPV,   "IPV_DOA_0": "0,1,2,2,2", "IPV_DOA_1": "0,1,2,2,3"},
    "ipv_cfg0_ins3": {**BASE_IPV,   "IPV_DOA_0": "0,1,2,2,3", "IPV_DOA_1": "0,1,2,2,2"},
    "ipv_3way":      {**BASE_IPV,   "DUEL_N_CONFIGS": 3,
                                    "IPV_DOA_0": "0,1,2,2,2",
                                    "IPV_DOA_1": "0,1,2,2,3",
                                    "IPV_DOA_2": "0,1,1,2,3"},
    "srrip_cfg0wins":{**BASE_SRRIP, "SRRIP_DOA_INS_RRPV": 2, "SRRIP_DOA_INS_RRPV_B": 3},
}

PINNED = [
    ("ipv_cfg0_ins2",  "ipv_cfg0_ins2",  BIN_IPV,   0.210701, 118055),
    ("ipv_cfg0_ins3",  "ipv_cfg0_ins3",  BIN_IPV,   0.240647, 159718),
    ("ipv_3way",       "ipv_3way",       BIN_IPV,   0.216070, 124999),
    ("srrip_cfg0wins", "srrip_cfg0wins", BIN_SRRIP, 0.210701, 118055),
]

R: dict = {}

def setUpModule():
    for key, env in _CONFIGS.items():
        # Determine binary from pinned table
        binary = next(b for (n, k, b, _, _) in PINNED if k == key)
        if not binary.exists() or not TRACE.exists():
            continue
        R[key] = _run(binary, env)

def _run(binary, env_extra):
    env = {**os.environ, **{k: str(v) for k, v in env_extra.items()}}
    result = subprocess.run(
        [str(binary), "--warmup_instructions", WARMUP,
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

def _make_pinned(key, binary, expected_ipc, expected_miss):
    def test(self):
        self.skipTest(f"binary not found: {binary}") if not binary.exists() else None
        s = R.get(key, {})
        self.assertTrue(s, msg=f"no result for config '{key}'")
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], expected_ipc, delta=IPC_TOL)
        self.assertEqual(s.get("llc_miss"), expected_miss)
    return test


@unittest.skipUnless(TRACE.exists(), f"trace not found: {TRACE}")
class TestPinned(unittest.TestCase):
    """End-to-end regression: each duel config must reproduce its reference IPC and miss count."""

for _name, _key, _bin, _ipc, _miss in PINNED:
    setattr(TestPinned, f"test_{_name}", _make_pinned(_key, _bin, _ipc, _miss))


@unittest.skipUnless(BIN_IPV.exists(),  f"binary not found: {BIN_IPV}")
@unittest.skipUnless(TRACE.exists(),    f"trace not found: {TRACE}")
class TestOrdering(unittest.TestCase):

    def test_follower_convergence_drives_ipc(self):
        # On a 100% DoA trace ins@3 beats ins@2.  Assigning ins@3 to cfg0
        # (which wins by default on tie) causes followers to adopt ins@3,
        # raising IPC.  If follower convergence is broken, the two configs
        # produce the same IPC.
        self.assertGreater(R["ipv_cfg0_ins3"]["ipc"],
                           R["ipv_cfg0_ins2"]["ipc"] + IPC_TOL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
