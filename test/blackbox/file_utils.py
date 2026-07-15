import difflib
import os
import shutil
import subprocess
import sys


def ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def output_paths(out_dir, expected_dir, name, suffix=".out"):
    ensure_dir(out_dir)
    ensure_dir(expected_dir)
    return (os.path.join(out_dir, name + suffix),
            os.path.join(expected_dir, name + suffix))


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


def write_reference(actual_path, reference_path):
    shutil.copy(actual_path, reference_path)
    print("REFERENCE WRITTEN (no comparison): %s" % reference_path)


def compare_to_reference(actual_path, reference_path, label):
    require(os.path.isfile(reference_path),
            "FAIL %s: no reference file (%s). Run with GENERATE=1 to create it."
            % (label, reference_path), 1)
    diff = diff_lines(reference_path, actual_path)
    if diff is None:
        print("PASS %s" % label)
        return
    sys.stdout.writelines(diff)
    sys.stderr.write("FAIL %s: output diverged from reference\n" % label)
    sys.exit(1)
