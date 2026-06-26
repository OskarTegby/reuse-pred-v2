#!/usr/bin/env bash
#
# Directional invariant check across two scenarios.
#
#   Usage: assert_order.sh <scenario_a> gt|lt <scenario_b>
#
# Asserts a relationship between the cumulative IPC of two scenarios that must
# hold regardless of future tuning, e.g. "bypass beats 2n3 insertion on a 100%
# DoA trace".  The golden diffs pin absolute output; these invariants catch the
# orthogonal failure where a future change legitimately updates the goldens but
# silently inverts a relationship the design depends on.
#
# Reuses the scenario's already-produced test_outputs file when present (the
# golden run leaves it there); otherwise runs the scenario to produce it.
#
set -euo pipefail

A="${1:?usage: assert_order.sh <a> gt|lt <b>}"
OP="${2:?usage: assert_order.sh <a> gt|lt <b>}"
B="${3:?usage: assert_order.sh <a> gt|lt <b>}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${OUTPUT_DIR:-$HERE/test_outputs}"

PHASE="${PHASE:-gate}"

ipc_of() {
  local scen="$1" f="$OUT_DIR/$1.$PHASE.out"
  if [ ! -f "$f" ]; then
    GENERATE=0 "$HERE/run_scenario.sh" "$scen" "$PHASE" >/dev/null 2>&1 || true
  fi
  # ROI cumulative IPC line: "CPU 0 cumulative IPC: 0.222176 instructions: ..."
  awk '/CPU 0 cumulative IPC:/ {print $5; exit}' "$f"
}

IA="$(ipc_of "$A")"
IB="$(ipc_of "$B")"

if [ -z "$IA" ] || [ -z "$IB" ]; then
  echo "SKIP: could not read IPC (A='$IA' B='$IB'); binaries built?" >&2
  exit 77
fi

awk -v a="$IA" -v b="$IB" -v op="$OP" -v na="$A" -v nb="$B" 'BEGIN{
  ok = (op=="gt") ? (a>b) : (a<b);
  printf "%s IPC=%s   %s IPC=%s   require %s %s %s\n", na, a, nb, b, na, op, nb;
  if (ok) { print "PASS"; exit 0 } else { print "FAIL: invariant violated"; exit 1 }
}'
