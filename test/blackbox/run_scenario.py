#!/usr/bin/env python3
#
# Black-box scenario runner for the liveness replacement policies. A scenario
# is <policy>_<condition>_<trace>; see README for what each axis covers and
# why these particular traces were picked.
#
#   Usage: run_scenario.py <scenario>            # run + compare
#          GENERATE=1 run_scenario.py <scenario> # write reference output
#          run_scenario.py --list                # print every scenario name
#
# Kept Python-3.3-compatible (no f-strings, no pathlib, no subprocess.run)
# because that is the interpreter available on the cluster (Castillo) where
# the full-size runs execute.

import difflib
import os
import re
import shutil
import subprocess
import sys

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


def list_scenarios():
    out = []
    for p in POLICIES:
        for c in CONDITIONS:
            for t in TRACE_KEYS:
                out.append(p + "_" + c + "_" + t)
    return out


def parse_scenario(scen):
    parts = scen.split("_")
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]


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

# (policy, condition) -> (binary, [fragment name or inline dict, ...]).
# This is the entire test matrix: every scenario's binary and env are read
# straight off this table instead of being computed by per-policy code.
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


def fragment_value(frag):
    return frag if isinstance(frag, dict) else STATIC_FRAGMENTS[frag]


def resolve_binary_and_env(pol, cond):
    entry = SCENARIO_MATRIX.get(pol, {}).get(cond)
    if entry is None:
        return None, None
    binary, fragments = entry
    env = {}
    for frag in fragments:
        env.update(fragment_value(frag))
    return binary, env


def check_prereqs(bin_path, trace, scen):
    if not (os.path.isfile(bin_path) and os.access(bin_path, os.X_OK)):
        sys.stderr.write("SKIP %s: binary not found: %s\n" % (scen, bin_path))
        sys.exit(77)  # 77 is ctest's SKIP_RETURN_CODE (see CMakeLists.txt).
    if not os.path.isfile(trace):
        sys.stderr.write("SKIP %s: trace not found: %s\n" % (scen, trace))
        sys.exit(77)


def run_binary(bin_path, trace, envv, actual_path):
    env = os.environ.copy()
    env.update(envv)
    cmd = [bin_path, "--warmup_instructions", WARMUP,
           "--simulation_instructions", SIM, trace]
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
    # Written line-by-line with an immediate flush (not buffered until exit) so
    # check_progress.sh's incremental verification can see progress mid-run.
    with open(actual_path, "w") as out:
        for line in proc.stdout:
            out.write(WALLCLOCK_RE.sub("", line))
            out.flush()
    proc.wait()


def write_reference(actual_path, reference_path):
    shutil.copy(actual_path, reference_path)
    print("REFERENCE WRITTEN (no comparison): %s" % reference_path)


def compare_to_reference(actual_path, reference_path, scen):
    if not os.path.isfile(reference_path):
        sys.stderr.write("FAIL %s: no reference file (%s). Run with GENERATE=1 to create it.\n"
                          % (scen, reference_path))
        sys.exit(1)
    with open(reference_path) as f:
        reference_lines = f.readlines()
    with open(actual_path) as f:
        actual_lines = f.readlines()
    if reference_lines == actual_lines:
        print("PASS %s" % scen)
        return
    diff = difflib.unified_diff(reference_lines, actual_lines,
                                 fromfile=reference_path, tofile=actual_path)
    sys.stdout.writelines(diff)
    sys.stderr.write("FAIL %s: output diverged from reference\n" % scen)
    sys.exit(1)


def resolve_scenario(scen):
    """Parse+resolve a scenario name to (bin_path, trace, envv), or None
    (having written a message to stderr) if any part of it is unknown."""
    parsed = parse_scenario(scen)
    if parsed is None:
        sys.stderr.write("unknown scenario '%s'\n" % scen)
        return None
    pol, cond, trc = parsed

    if trc not in TRACE_PATHS:
        sys.stderr.write("unknown trace key in '%s'\n" % scen)
        return None

    binary, envv = resolve_binary_and_env(pol, cond)
    if binary is None:
        sys.stderr.write("unknown scenario '%s'\n" % scen)
        return None

    trace = os.environ.get("TRACE") or TRACE_PATHS[trc]
    bin_path = os.path.join(BIN_DIR, binary)
    return bin_path, trace, envv


def ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def run_scenario(scen):
    resolved = resolve_scenario(scen)
    if resolved is None:
        return 2
    bin_path, trace, envv = resolved
    check_prereqs(bin_path, trace, scen)

    ensure_dir(OUT_DIR)
    ensure_dir(EXPECTED_DIR)
    actual_path = os.path.join(OUT_DIR, scen + ".out")
    reference_path = os.path.join(EXPECTED_DIR, scen + ".out")

    run_binary(bin_path, trace, envv, actual_path)

    if os.environ.get("GENERATE", "0") == "1":
        write_reference(actual_path, reference_path)
        return 0

    compare_to_reference(actual_path, reference_path, scen)
    return 0


def main(argv):
    if len(argv) > 1 and argv[1] == "--list":
        print("\n".join(list_scenarios()))
        return 0
    if len(argv) < 2:
        sys.stderr.write("usage: run_scenario.py <policy>_<condition>_<trace>  (or --list)\n")
        return 2
    return run_scenario(argv[1])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
