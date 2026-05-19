#!/usr/bin/env python3
"""
Enumerate all monotone IPV configurations for maxRRPV = 3.

Monotone constraint: ipv[k] <= k for k = 0..3 (a hit never worsens RRPV).
  ipv[0] = 0         (only valid value)
  ipv[1] in {0, 1}
  ipv[2] in {0, 1, 2}
  ipv[3] in {0, 1, 2, 3}
  ipv[4] in {0, 1, 2, 3}  (insertion — unconstrained within range)

Total without --min-ipv: 1 * 2 * 3 * 4 * 4 = 96 vectors.

An optional element-wise lower bound --min-ipv a,b,c,d,e restricts each
position to values >= the corresponding bound.  This enforces the liveness
ordering constraint: doa[k] >= mostly_dead[k] >= mostly_alive[k].

Usage:
  python3 enumerate_ipvs.py                        # all 96
  python3 enumerate_ipvs.py --min-ipv 0,1,1,0,3   # constrained subset
  python3 enumerate_ipvs.py --count                # just print the count
"""

import sys

def all_ipvs(min_vals=None):
    """Yield all monotone IPV strings satisfying element-wise >= min_vals."""
    if min_vals is None:
        min_vals = [0, 0, 0, 0, 0]
    for i1 in range(min_vals[1], 2):
        for i2 in range(min_vals[2], 3):
            for i3 in range(min_vals[3], 4):
                for i4 in range(min_vals[4], 4):
                    yield f"0,{i1},{i2},{i3},{i4}"

def parse_min_ipv(s):
    parts = [int(x) for x in s.split(",")]
    if len(parts) != 5:
        raise ValueError(f"--min-ipv expects 5 comma-separated integers, got: {s}")
    return parts

if __name__ == "__main__":
    min_vals = None
    args = sys.argv[1:]
    if "--min-ipv" in args:
        idx = args.index("--min-ipv")
        min_vals = parse_min_ipv(args[idx + 1])
        args = args[:idx] + args[idx + 2:]

    if "--count" in args:
        print(sum(1 for _ in all_ipvs(min_vals)))
    else:
        for v in all_ipvs(min_vals):
            print(v)
