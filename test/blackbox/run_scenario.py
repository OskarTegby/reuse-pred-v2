#!/usr/bin/env python3

# Black-box scenario runner for the liveness replacement policies. A scenario
# is <policy>_<condition>_<trace>; see README for what each axis covers and
# why these particular traces were picked.
#
#   Usage: run_scenario.py <scenario>            # run + compare
#          GENERATE=1 run_scenario.py <scenario> # write reference output
#          run_scenario.py --list                # print every scenario name

import os
import sys

from file_utils import is_executable_file, require, env_flag, \
    stream_subprocess_to_file, output_paths, write_reference, compare_to_reference
from scenario import EXPECTED_DIR, OUT_DIR, WARMUP, SIM, WALLCLOCK_RE
from scenario_utils import list_scenarios, resolve_scenario

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

    actual_path, reference_path = output_paths(OUT_DIR, EXPECTED_DIR, scen)
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
