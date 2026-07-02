# Generic file/process helpers -- no knowledge of scenarios, policies, or
# ChampSim. Kept Python-3.3-compatible like the rest of this test runner.

import difflib
import os
import subprocess
import sys


def ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def is_executable_file(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)


def require(condition, message, exit_code):
    if not condition:
        sys.stderr.write(message + "\n")
        sys.exit(exit_code)


def env_flag(name):
    return os.environ.get(name, "0") == "1"


def stream_subprocess_to_file(cmd, env, out_path, transform_line=None):
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
    # Line-buffered with an immediate flush (not buffered until exit) so a
    # caller polling `out_path` mid-run sees progress as it happens.
    with open(out_path, "w") as out:
        for line in proc.stdout:
            out.write(transform_line(line) if transform_line else line)
            out.flush()
    proc.wait()


def diff_lines(path_a, path_b):
    with open(path_a) as f:
        lines_a = f.readlines()
    with open(path_b) as f:
        lines_b = f.readlines()
    if lines_a == lines_b:
        return None
    return difflib.unified_diff(lines_a, lines_b, fromfile=path_a, tofile=path_b)
