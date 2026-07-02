# Kept Python-3.3-compatible (no f-strings, no pathlib) to match
# run_scenario.py, which runs under the cluster's Python 3.3.

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("SRC_ROOT") or os.path.abspath(os.path.join(HERE, "..", ".."))
BIN_DIR = os.environ.get("BIN_DIR") or os.path.join(ROOT, "bin")
EXPECTED_DIR = os.path.join(HERE, "expected")
OUT_DIR = os.environ.get("OUTPUT_DIR") or os.path.join(HERE, "test_outputs")
WARMUP = os.environ.get("WARMUP") or "50000000"
SIM = os.environ.get("SIM") or "100000000"
DPC3 = "/home/users/shared/traces/dpc3_traces"

POLICIES = ["lru", "srrip", "ipv"]
CONDITIONS = ["base", "fixed", "bypass", "duel", "addr"]
TRACE_KEYS = ["pr", "cactus", "bwaves", "qmm"]

TRACE_PATHS = {
    "pr": os.path.join(ROOT, "trace-files", "ligra",
                        "ligra_PageRank.com-lj.ungraph.gcc_6.3.0_O3.drop_51000M.length_250M.champsimtrace.xz"),
    "cactus": os.path.join(DPC3, "607.cactuBSSN_s-3477B.champsimtrace.xz"),
    "bwaves": os.path.join(DPC3, "603.bwaves_s-891B.champsimtrace.xz"),
    "qmm": os.path.join(ROOT, "trace-files", "QMM", "srv_12.champsimtrace.xz"),
}

WALLCLOCK_RE = re.compile(r" \(Simulation time: \d+ hr \d+ min \d+ sec\)")

# Named env fragments a scenario can merge together (later fragments in a
# scenario's list override earlier ones).
STATIC_FRAGMENTS = {
    "base": {"THD_DOA": "6", "BHIST_MODE": "pc", "SRRIP_LIVE_TARGET": "llc"},
    "addr": {"REPL_HIST_MODE": "addr", "REPL_HIST_LLC_CAP": "4096", "REPL_HIST_REPL": "lfu_doa"},
    "ipv_vec": {"IPV_DOA": "0:1:2:2:3"},
    # SRRIP/IPV express bypass by disabling the in-cache insert; LRU-Live
    # instead uses LRU_LIVE_DOA_INS=bypass (see SCENARIO_MATRIX below).
    "bypass_override": {"SRRIP_LIVE_TARGET": "none", "LIVENESS_BYPASS": "1"},
}

# A lookup table instead of per-policy code, so scenario resolution never
# needs to branch on policy.
SCENARIO_MATRIX = {
    "lru": {
        "base":   ("champsim_lru", []),
        "fixed":  ("champsim_lru_live", ["base", {"LRU_LIVE_DOA_INS": "2n3"}]),
        "bypass": ("champsim_lru_live", ["base", {"LRU_LIVE_DOA_INS": "bypass"}]),
        "duel":   ("champsim_lru_live", ["base", {
            "LRU_LIVE_DOA_INS": "2n3", "LRU_LIVE_DOA_INS_B": "lru",
            "DUEL_N_SAMPLERS": "32", "DUEL_METRIC": "latency"}]),
        "addr":   ("champsim_lru_live", ["base", {"LRU_LIVE_DOA_INS": "2n3"}, "addr"]),
    },
    "srrip": {
        "base":   ("champsim_srrip", []),
        "fixed":  ("champsim_srrip_live", ["base"]),
        "bypass": ("champsim_srrip_live", ["base", "bypass_override"]),
        "duel":   ("champsim_srrip_live", ["base", {
            "SRRIP_DOA_INS_RRPV": "2", "SRRIP_DOA_HIT_RRPV": "2",
            "SRRIP_DOA_INS_RRPV_B": "3", "SRRIP_DOA_HIT_RRPV_B": "0",
            "DUEL_N_SAMPLERS": "32"}]),
        "addr":   ("champsim_srrip_live", ["base", "addr"]),
    },
    "ipv": {
        "base":   ("champsim_ipv", []),
        "fixed":  ("champsim_ipv_live", ["base", "ipv_vec"]),
        "bypass": ("champsim_ipv_live", ["base", "bypass_override", "ipv_vec"]),
        "duel":   ("champsim_ipv_live", ["base", {
            "DUEL_N_CONFIGS": "2", "DUEL_N_SAMPLERS": "32",
            "IPV_DOA_0": "0:1:2:2:2", "IPV_DOA_1": "0:1:2:2:3",
            "DUEL_METRIC": "latency"}]),
        "addr":   ("champsim_ipv_live", ["base", "ipv_vec", "addr"]),
    },
}
