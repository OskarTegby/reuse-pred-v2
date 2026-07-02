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

import os
import shutil
import sys

from fileutils import ensure_dir, stream_subprocess_to_file, diff_lines
from scenario_config import (
    BIN_DIR, EXPECTED_DIR, OUT_DIR, WARMUP, SIM,
    POLICIES, CONDITIONS, TRACE_KEYS, TRACE_PATHS,
    WALLCLOCK_RE, STATIC_FRAGMENTS, SCENARIO_MATRIX,
)


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


def resolve_fragment(frag):
    return frag if isinstance(frag, dict) else STATIC_FRAGMENTS[frag]


def resolve_binary_and_env(pol, cond):
    entry = SCENARIO_MATRIX.get(pol, {}).get(cond)
    if entry is None:
        return None, None
    binary, fragments = entry
    env = {}
    for frag in fragments:
        env.update(resolve_fragment(frag))
    return binary, env


def check_prereqs(bin_path, trace, scen):
    if not (os.path.isfile(bin_path) and os.access(bin_path, os.X_OK)):
        sys.stderr.write("SKIP %s: binary not found: %s\n" % (scen, bin_path))
        sys.exit(77)  # 77 is ctest's SKIP_RETURN_CODE (see CMakeLists.txt).
    if not os.path.isfile(trace):
        sys.stderr.write("SKIP %s: trace not found: %s\n" % (scen, trace))
        sys.exit(77)


def run_binary(bin_path, trace, env_vars, actual_path):
    env = os.environ.copy()
    env.update(env_vars)
    cmd = [bin_path, "--warmup_instructions", WARMUP,
           "--simulation_instructions", SIM, trace]
    stream_subprocess_to_file(cmd, env, actual_path,
                               lambda line: WALLCLOCK_RE.sub("", line))


def write_reference(actual_path, reference_path):
    shutil.copy(actual_path, reference_path)
    print("REFERENCE WRITTEN (no comparison): %s" % reference_path)


def compare_to_reference(actual_path, reference_path, scen):
    if not os.path.isfile(reference_path):
        sys.stderr.write("FAIL %s: no reference file (%s). Run with GENERATE=1 to create it.\n"
                          % (scen, reference_path))
        sys.exit(1)
    diff = diff_lines(reference_path, actual_path)
    if diff is None:
        print("PASS %s" % scen)
        return
    sys.stdout.writelines(diff)
    sys.stderr.write("FAIL %s: output diverged from reference\n" % scen)
    sys.exit(1)


def unknown_scenario(scen):
    sys.stderr.write("unknown scenario '%s'\n" % scen)
    return None


def resolve_scenario(scen):
    """Parse+resolve a scenario name to (bin_path, trace, env_vars), or None
    (having written a message to stderr) if any part of it is unknown."""
    parsed = parse_scenario(scen)
    if parsed is None:
        return unknown_scenario(scen)
    pol, cond, trc = parsed

    if trc not in TRACE_PATHS:
        return unknown_scenario(scen)

    binary, env_vars = resolve_binary_and_env(pol, cond)
    if binary is None:
        return unknown_scenario(scen)

    trace = os.environ.get("TRACE") or TRACE_PATHS[trc]
    bin_path = os.path.join(BIN_DIR, binary)
    return bin_path, trace, env_vars


def output_paths(scen):
    ensure_dir(OUT_DIR)
    ensure_dir(EXPECTED_DIR)
    return (os.path.join(OUT_DIR, scen + ".out"),
            os.path.join(EXPECTED_DIR, scen + ".out"))


def generating():
    return os.environ.get("GENERATE", "0") == "1"


def finish(actual_path, reference_path, scen):
    if generating():
        write_reference(actual_path, reference_path)
        return 0
    compare_to_reference(actual_path, reference_path, scen)
    return 0


def run_scenario(scen):
    resolved = resolve_scenario(scen)
    if resolved is None:
        return 2
    bin_path, trace, env_vars = resolved
    check_prereqs(bin_path, trace, scen)

    actual_path, reference_path = output_paths(scen)
    run_binary(bin_path, trace, env_vars, actual_path)
    return finish(actual_path, reference_path, scen)


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
