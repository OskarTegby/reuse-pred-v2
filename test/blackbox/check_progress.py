#!/usr/bin/env python3

import re
import sys

SOFT_MILESTONE = 70_000_000

HEARTBEAT_RE = re.compile(r"^Heartbeat CPU 0 instructions: (\d+)")


def read_lines(path):
    try:
        with open(path) as f:
            return f.readlines()
    except FileNotFoundError:
        return None


def count_complete_lines(path):
    with open(path, "rb") as f:
        return f.read().count(b"\n")


def max_heartbeat_instructions(lines):
    maxhb = 0
    for line in lines:
        m = HEARTBEAT_RE.match(line)
        if m:
            maxhb = max(maxhb, int(m.group(1)))
    return maxhb


def prefix_status(actual_path, actual_lines, expected_lines):
    k = count_complete_lines(actual_path)
    if k == 0:
        return "PENDING"
    if actual_lines[:k] != expected_lines[:k]:
        return "FAIL"
    return None


def classify(actual_path, expected_path):
    expected_lines = read_lines(expected_path)
    if expected_lines is None:
        return "NO-REFERENCE"

    actual_lines = read_lines(actual_path)
    if not actual_lines:
        return "PENDING"

    if actual_lines == expected_lines:
        return "FULL_PASS"

    result = prefix_status(actual_path, actual_lines, expected_lines)
    if result is not None:
        return result

    if max_heartbeat_instructions(actual_lines) >= SOFT_MILESTONE:
        return "SOFT_PASS"
    return "RUNNING"


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("usage: check_progress.py <actual.out> <expected.out>\n")
        return 2
    print(classify(argv[1], argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
