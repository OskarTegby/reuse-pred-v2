#!/usr/bin/env python3
"""
Enumerate all valid IPV configurations for maxRRPV = 3.

Two constraints are applied (matching PACIPV, Mostofi et al. ISCA 2025):

1. Monotone:       ipv[k] <= k  — a hit never worsens RRPV.
2. Strict-descent: ipv[k] <  k  for k = 1, 2.
   A hit at RRPV=1 or RRPV=2 must strictly improve the line.
   At RRPV=3 (eviction priority) any value <=3 is allowed — the line
   will be evicted regardless, so keeping it at 3 on a hit is valid.

  ipv[0] = 0         (only valid value)
  ipv[1] = 0         (forced: must be < 1)
  ipv[2] in {0, 1}   (must be < 2)
  ipv[3] in {0,1,2,3}
  ipv[4] in {0,1,2,3}  (insertion — unconstrained within range)

Total without --min-ipv: 1 * 1 * 2 * 4 * 4 = 32 vectors.

An optional element-wise lower bound --min-ipv a,b,c,d,e restricts each
position to values >= the corresponding bound.  This enforces the liveness
ordering constraint on top of the PACIPV constraints:
  doa[k] >= mostly_dead[k] >= mostly_alive[k].

Usage:
  python3 enumerate_ipvs.py                        # all 32
  python3 enumerate_ipvs.py --min-ipv 0,0,1,0,3   # constrained subset
  python3 enumerate_ipvs.py --count                # just print the count
"""

import sys

def all_ipvs(min_vals=None):
    """Yield all valid IPV strings satisfying element-wise >= min_vals."""
    if min_vals is None:
        min_vals = [0, 0, 0, 0, 0]
    for i1 in range(min_vals[1], 1):    # ipv[1] forced to 0 (< 1)
        for i2 in range(min_vals[2], 2):  # ipv[2] in {0,1}  (< 2)
            for i3 in range(min_vals[3], 4):  # ipv[3] in {0..3}
                for i4 in range(min_vals[4], 4):  # ipv[4] in {0..3}
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
