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
import re
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

# pagerank's four load PCs (deterministic virtual addresses from the trace).
# Two are heavily re-referenced and classify strongly DoA; two are barely seen.
PC_HEAVY = {"0x555555563de8", "0x555555563df1"}
PC_LIGHT = {"0x555555563dfa", "0x555555563e02"}
PC_ALL   = PC_HEAVY | PC_LIGHT


def run_sim(env_extra: dict) -> dict:
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
    "cap256":               {**BASE, "REPL_HIST_LLC_CAP": 256,
                                     "REPL_HIST_REPL": "tiered",
                                     "REPL_HIST_DUMP_PCS": 1},
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
    ("cap256",           "cap256",            0.222176, 111104),
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

    # History-table contents under a realistic cap (256).  On pagerank all four
    # PCs fit, so the table must hold exactly that set.  This is the local
    # placeholder for the real test: the same assertions on a many-PC trace
    # (QMM/SPEC) verify which PCs the eviction policy retains under pressure.

    def test_table_holds_exactly_the_trace_pcs(self):
        self.assertEqual(R["cap256"].get("pc_count"), len(PC_ALL))
        self.assertEqual(set(R["cap256"]["pcs"].keys()), PC_ALL)

    def test_heavy_pcs_classify_strongly_doa(self):
        # The two re-referenced PCs must accumulate large DoA scores; the two
        # rarely-seen PCs must stay near zero.  A classification regression that
        # mislabels them flips this ordering even if IPC barely moves.
        pcs = R["cap256"]["pcs"]
        for k in PC_HEAVY:
            self.assertGreater(pcs[k][0], 1000, msg=f"{k} doa={pcs[k][0]} too low")
        for k in PC_LIGHT:
            self.assertLess(pcs[k][0], 100, msg=f"{k} doa={pcs[k][0]} too high")


if __name__ == "__main__":
    unittest.main(verbosity=2)
