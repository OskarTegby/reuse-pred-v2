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

from fileutils import (
    ensure_dir, is_executable_file, require, env_flag,
    stream_subprocess_to_file, diff_lines,
)
from scenario import BIN_DIR, EXPECTED_DIR, OUT_DIR, WARMUP, SIM, TRACE_PATHS, WALLCLOCK_RE
from scenario_utils import list_scenarios, parse_scenario, resolve_binary_and_env

SKIP = 77  # ctest's SKIP_RETURN_CODE (see CMakeLists.txt).


def check_prereqs(bin_path, trace, scen):
    require(is_executable_file(bin_path), "SKIP %s: binary not found: %s" % (scen, bin_path), SKIP)
    require(os.path.isfile(trace), "SKIP %s: trace not found: %s" % (scen, trace), SKIP)


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
    require(os.path.isfile(reference_path),
            "FAIL %s: no reference file (%s). Run with GENERATE=1 to create it."
            % (scen, reference_path), 1)
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


def finish(actual_path, reference_path, scen):
    if env_flag("GENERATE"):
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
