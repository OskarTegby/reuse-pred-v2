#!/usr/bin/env python3

import os
import subprocess

ROOT = "/home/users/otegby/ChampSim-dev"
RUNNER = os.path.join(ROOT, "test", "blackbox", "run_scenario.py")
OUTPUT_DIR = os.path.join(ROOT, "test", "blackbox", "test_outputs")
LOGDIR = os.path.join(ROOT, "test", "blackbox", "logs")


def main():
    os.makedirs(LOGDIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    scenarios = subprocess.check_output(
        ["python3", RUNNER, "--list"], universal_newlines=True
    ).splitlines()

    env_vars = "SRC_ROOT=%s,BIN_DIR=%s,OUTPUT_DIR=%s,GENERATE=1" % (
        ROOT, os.path.join(ROOT, "bin"), OUTPUT_DIR)

    for scen in scenarios:
        subprocess.check_call([
            "qsub", "-N", "bb_%s" % scen, "-j", "y",
            "-o", os.path.join(LOGDIR, "%s.log" % scen),
            "-v", env_vars,
            "-b", "y", "python3", RUNNER, scen,
        ])

    print("Submitted %d full jobs" % len(scenarios))


if __name__ == "__main__":
    main()
