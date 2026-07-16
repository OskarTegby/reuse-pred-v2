#!/usr/bin/env python3

import re
import sys

SOFT_MILESTONE = 70_000_000

HEARTBEAT_RE = re.compile(r"^Heartbeat CPU 0 instructions: (\d+)")


def classify(actual_path, expected_path):
    try:
        with open(expected_path) as f:
            expected_lines = f.readlines()
    except FileNotFoundError:
        return "NO-REFERENCE"

    try:
        with open(actual_path) as f:
            actual_lines = f.readlines()
    except FileNotFoundError:
        return "PENDING"
    if not actual_lines:
        return "PENDING"

    if actual_lines == expected_lines:
        return "FULL_PASS"

    with open(actual_path, "rb") as f:
        k = f.read().count(b"\n")
    if k == 0:
        return "PENDING"

    if actual_lines[:k] != expected_lines[:k]:
        return "FAIL"

    maxhb = 0
    for line in actual_lines:
        m = HEARTBEAT_RE.match(line)
        if m:
            maxhb = max(maxhb, int(m.group(1)))
    return "SOFT_PASS" if maxhb >= SOFT_MILESTONE else "RUNNING"


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("usage: check_progress.py <actual.out> <expected.out>\n")
        return 2
    print(classify(argv[1], argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
