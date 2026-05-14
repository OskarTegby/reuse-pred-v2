#!/usr/bin/env python3
"""
Enumerate all monotone IPV configurations for maxRRPV = 3.

Monotone constraint: ipv[k] <= k for k = 0..3 (a hit never worsens RRPV).
  ipv[0] = 0  always (only valid value)
  ipv[1] in {0, 1}
  ipv[2] in {0, 1, 2}
  ipv[3] in {0, 1, 2, 3}
  ipv[4] in {0, 1, 2, 3}  (insertion — unconstrained)

Total: 1 * 2 * 3 * 4 * 4 = 96 vectors.

Usage:
  python3 enumerate_ipvs.py          # print all 96 as "a,b,c,d,e"
  python3 enumerate_ipvs.py --count  # just print 96
"""

import sys

def all_ipvs():
    for i1 in range(2):       # ipv[1]
        for i2 in range(3):   # ipv[2]
            for i3 in range(4):  # ipv[3]
                for i4 in range(4):  # ipv[4] insertion
                    yield f"0,{i1},{i2},{i3},{i4}"

if __name__ == "__main__":
    if "--count" in sys.argv:
        print(sum(1 for _ in all_ipvs()))
    else:
        for v in all_ipvs():
            print(v)
