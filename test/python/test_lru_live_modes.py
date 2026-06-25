"""Black-box regression tests for LRU-Live replacement policy.

Each pinned test runs bin/champsim_lru_live with a specific env configuration
and checks that IPC and LLC miss count match the stored reference values.
A code change that shifts classification, insertion position, or eviction
order will compound over the simulation and move these numbers — that is the
guard this test suite provides.

Quantitative ordering tests verify directional correctness that must hold
across all future configurations, e.g. that bypass outperforms 2n3 insertion
on a 100% DoA trace, or that a larger history table matches the unbounded
baseline.

All configurations are cached at module load time so each binary invocation
runs exactly once regardless of how many tests reference the same config.

Trace: pagerank.champsimtrace.xz (100% DoA, no temporal reuse, 4 unique PCs).
Pinned: June 2026, main branch, post duel-miss-latency merge.
"""

import os
import subprocess
import unittest
from pathlib import Path

ROOT  = Path(__file__).resolve().parents[2]
BIN   = ROOT / "bin" / "champsim_lru_live"
TRACE = ROOT / "trace-files" / "pagerank.champsimtrace.xz"

WARMUP  = "1000000"
SIM     = "2000000"
IPC_TOL = 0.0001  # ±0.01% absolute

BASE = dict(THD_DOA=6, THD_DEAD=10, SCORING_MODE=5)


def run_sim(env_extra: dict) -> dict:
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


# Run every configuration exactly once.  Tests reference R[key] directly.
_CONFIGS = {
    "default":              {},
    "cfgA_2n3":             {**BASE, "LRU_LIVE_DOA_INS": "2n3"},
    "cfgB_lru":             {**BASE, "LRU_LIVE_DOA_INS": "lru"},
    "bypass":               {**BASE, "LRU_LIVE_DOA_INS": "bypass"},
    "bypass_disabled":      {**BASE, "LRU_LIVE_DOA_INS": "bypass",
                                     "LRU_LIVE_ALLOW_BYPASS": "0"},
    "duel_hits_n32":        {**BASE, "DUEL_N_SAMPLERS": 32},
    "duel_lat_hyst250k":    {**BASE, "DUEL_N_SAMPLERS": 32,
                                     "DUEL_METRIC": "latency",
                                     "DUEL_HYST": 250000},
    "cap2":                 {**BASE, "REPL_HIST_LLC_CAP": 2},
    "cap1":                 {**BASE, "REPL_HIST_LLC_CAP": 1},
}

R: dict = {}  # populated in setUpModule

def setUpModule():
    if not BIN.exists() or not TRACE.exists():
        return
    for key, env in _CONFIGS.items():
        R[key] = run_sim(env)


# Pinned (name, config_key, expected_ipc, expected_llc_miss)
PINNED = [
    ("default",          "default",          0.222176, 111104),
    ("cfgA_2n3",         "cfgA_2n3",         0.222176, 111104),
    ("cfgB_lru",         "cfgB_lru",         0.251201, 166650),
    ("bypass",           "bypass",           0.251271, 166653),
    ("bypass_disabled",  "bypass_disabled",  0.251201, 166650),
    ("duel_hits_n32",    "duel_hits_n32",     0.220342, 111974),
    ("duel_lat_hyst250k","duel_lat_hyst250k", 0.220342, 111974),
    ("cap2",             "cap2",              0.222176, 111104),
    ("cap1",             "cap1",              0.205836, 111112),
]


def _make_pinned_test(key, expected_ipc, expected_miss):
    def test(self):
        s = R[key]
        self.assertEqual(s["returncode"], 0, msg=s["raw"][-500:])
        self.assertAlmostEqual(s["ipc"], expected_ipc, delta=IPC_TOL,
                               msg=f"IPC {s.get('ipc')} != {expected_ipc}")
        self.assertEqual(s.get("llc_miss"), expected_miss,
                         msg=f"LLC miss {s.get('llc_miss')} != {expected_miss}")
    return test


@unittest.skipUnless(BIN.exists(),   f"binary not found: {BIN}")
@unittest.skipUnless(TRACE.exists(), f"trace not found: {TRACE}")
class TestPinned(unittest.TestCase):
    """End-to-end regression: each config must reproduce its reference IPC and miss count."""

for _name, _key, _ipc, _miss in PINNED:
    setattr(TestPinned, f"test_{_name}", _make_pinned_test(_key, _ipc, _miss))


@unittest.skipUnless(BIN.exists(),   f"binary not found: {BIN}")
@unittest.skipUnless(TRACE.exists(), f"trace not found: {TRACE}")
class TestOrdering(unittest.TestCase):
    """Directional invariants that must hold regardless of future tuning.

    These catch bugs where a change is numerically wrong in a specific direction
    even if no pinned value is broken (e.g. bypass silently regressed to 2n3).
    All results come from the module-level cache — no additional simulations run.
    """

    def test_bypass_outperforms_2n3_on_doa_trace(self):
        # On 100% DoA trace, bypass frees LLC ways entirely — 2n3 wastes them
        # on blocks that will never be hit again.
        self.assertGreater(R["bypass"]["ipc"], R["cfgA_2n3"]["ipc"] + IPC_TOL)

    def test_lru_insertion_outperforms_2n3_on_doa_trace(self):
        # cfgB (lru, evicted on next fill) also frees ways faster than 2n3.
        self.assertGreater(R["cfgB_lru"]["ipc"], R["cfgA_2n3"]["ipc"] + IPC_TOL)

    def test_bypass_disabled_falls_back_to_lru(self):
        # ALLOW_BYPASS=0 must produce the same miss count as lru insertion.
        # IPC difference is <0.01% so we use the integer LLC miss count to
        # distinguish this from the bypass case (which differs by 3 misses).
        self.assertEqual(R["bypass_disabled"]["llc_miss"], R["cfgB_lru"]["llc_miss"])
        self.assertNotEqual(R["bypass_disabled"]["llc_miss"], R["bypass"]["llc_miss"])

    def test_cap2_sufficient_for_this_trace(self):
        # cap=2 is enough for pagerank's steady-state access pattern — IPC
        # matches cap=1 being insufficient but cap=2 recovering fully.
        self.assertAlmostEqual(R["cap2"]["ipc"], R["cfgA_2n3"]["ipc"], delta=IPC_TOL)

    def test_cap1_constraint_degrades_ipc(self):
        # cap=1 forces constant eviction of history entries — PCs lose their
        # liveness counts and are misclassified.  IPC must be worse than cap=2.
        self.assertGreater(R["cap2"]["ipc"], R["cap1"]["ipc"] + IPC_TOL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
