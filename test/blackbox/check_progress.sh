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
#   RUNNING       actual is a correct prefix of expected, but < the soft milestone
#   SOFT_PASS     correct prefix AND the soft milestone reached -> likely to pass
#   FULL_PASS     actual matches expected exactly -> fully verified
#
# Why a prefix is sufficient: every line of the ChampSim report except the
# stripped wall-clock line is deterministic for a fixed trace+config, so any
# difference in an already-written line is a real failure -- there is no need to
# wait for completion to know a run has diverged.
#
# Soft-pass milestone: ChampSim heartbeats count *total* instructions (warmup+sim)
# and fire every 10M. "Soft pass" means enough has been verified that the run will
# most likely pass. It is a single tunable constant (SOFT_MILESTONE below):
# lowering it surfaces the soft pass sooner (each 10M earlier ~ one heartbeat).
set -euo pipefail

actual="${1:?usage: check_progress.sh <actual.out> <expected.out>}"
expected="${2:?usage: check_progress.sh <actual.out> <expected.out>}"

# --- soft-pass milestone (tunable) -------------------------------------------
WARMUP_INSTRS=50000000
SOFT_SIM_INSTRS=20000000                            # 20M of the 100M sim
SOFT_MILESTONE=$((WARMUP_INSTRS + SOFT_SIM_INSTRS)) # = 70,000,000 total

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

# Correct prefix so far. Soft pass once a heartbeat at >= SOFT_MILESTONE total
# instructions has been emitted. Heartbeat lines are
# "Heartbeat CPU 0 instructions: <N> cycles: ..."; field 5 is N. A single awk
# emits the largest N seen, or 0 if there are no heartbeats yet -- it always
# exits 0 (a grep with no match would exit 1 and, under set -e + pipefail, abort
# this substitution). The "^Heartbeat" anchor excludes the "Simulation
# Instructions:" header and "Simulation finished" lines.
maxhb=$(awk '/^Heartbeat CPU 0 instructions:/ { if ($5+0 > m) m=$5+0 } END { print m+0 }' "$actual")
if [ "$maxhb" -ge "$SOFT_MILESTONE" ]; then
  echo "SOFT_PASS"
else
  echo "RUNNING"
fi
