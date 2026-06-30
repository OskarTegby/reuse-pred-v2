#!/usr/bin/env bash
#
# Classify a scenario's (possibly in-progress) output against its expected
# reference. Used for incremental black-box verification while cluster jobs are
# still running, so a diverged run is caught early instead of after the full
# simulation completes.
#
#   Usage: check_progress.sh <actual.out> <expected.out>
#
# Prints exactly one state token on stdout:
#
#   NO-REFERENCE  expected file is missing
#   PENDING       no usable actual output yet (job not started / empty)
#   FAIL          a completed line of actual differs from expected -> diverged
#   RUNNING       actual is a correct prefix of expected, but < 50M sim done
#   SOFT_PASS     correct prefix AND the 50M-sim milestone reached -> likely to pass
#   FULL_PASS     actual matches expected exactly -> fully verified
#
# Why a prefix is sufficient: every line of the ChampSim report except the
# stripped wall-clock line is deterministic for a fixed trace+config, so any
# difference in an already-written line is a real failure -- there is no need to
# wait for completion to know a run has diverged.
#
# Soft-pass milestone: ChampSim heartbeats count *total* instructions
# (warmup+sim). With a 50M warmup, "50M warmup + 30M of the 100M simulation"
# is the heartbeat at 80,000,000 total instructions -- ~a third of the sim
# verified and on-track, hence "most likely to pass". (30M chosen over 50M to
# surface the soft pass ~2 heartbeats / ~25% sooner.)
set -euo pipefail

actual="${1:?usage: check_progress.sh <actual.out> <expected.out>}"
expected="${2:?usage: check_progress.sh <actual.out> <expected.out>}"

[ -f "$expected" ] || { echo "NO-REFERENCE"; exit 0; }
[ -s "$actual" ]   || { echo "PENDING";      exit 0; }

# Exact match -> fully verified.
if diff -q "$expected" "$actual" >/dev/null 2>&1; then
  echo "FULL_PASS"; exit 0
fi

# Count complete (newline-terminated) lines in actual. A trailing partial line
# (a write still in progress) has no newline and is excluded, so we never
# compare half a line.
k=$(tr -cd '\n' < "$actual" | wc -c)
[ "$k" -ge 1 ] || { echo "PENDING"; exit 0; }

# Every completed line of actual must equal expected's first k lines. If actual
# has more complete lines than expected (k > #expected), the line counts differ
# and this diff fails too -- correctly flagging diverged/extra output.
if ! diff -q <(head -n "$k" "$expected") <(head -n "$k" "$actual") >/dev/null 2>&1; then
  echo "FAIL"; exit 0
fi

# Correct prefix so far. Soft pass once the 30M-sim heartbeat has been emitted
# (a Heartbeat line with >= 80,000,000 total instructions: 8 digits starting 8 or
# 9 = 80M-99M, or 9 digits = >=100M). Warmup tops out at 50M and the 60M/70M sim
# heartbeats start 5/6/7, so none of those match. Anchored to "Heartbeat" so the
# "Simulation Instructions: 100000000" header and "Simulation finished" lines do
# not match.
if grep -qE '^Heartbeat CPU 0 instructions: ([89][0-9]{7}|1[0-9]{8}) ' "$actual"; then
  echo "SOFT_PASS"
else
  echo "RUNNING"
fi
