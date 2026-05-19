#!/usr/bin/env python3
"""
Enumerate all valid monotone non-decreasing IPV 3-chains.

A chain (mostly_alive, mostly_dead, doa) satisfies:
  v_ma[k] <= v_md[k] <= v_doa[k]  for k = 0..4   (liveness ordering)
  v_x[k]  <= k                                     (IPV monotonicity)

Position ranges (maxRRPV = 3):
  pos 0: always 0     → 1  non-decreasing triple
  pos 1: {0,1}        → 4  non-decreasing triples
  pos 2: {0,1,2}      → 10 non-decreasing triples
  pos 3: {0,1,2,3}    → 20 non-decreasing triples
  pos 4: {0,1,2,3}    → 20 non-decreasing triples  (insertion)

Total: 1 × 4 × 10 × 20 × 20 = 16,000 chains.

Output: one chain per line, three tab-separated IPV strings:
  <mostly_alive_ipv>\t<mostly_dead_ipv>\t<doa_ipv>

The full joint demand-and-prefetch search space (16,000²) is too large to
sweep exhaustively.  Instead, sweep demand chains and prefetch chains in
two separate passes, holding the other access type fixed each time.

Usage:
  python3 enumerate_ipv_chains.py            # all 16,000 chains
  python3 enumerate_ipv_chains.py --count    # just print the count
"""

import sys


def nd_triples(max_val):
    """Yield all (a, b, c) with 0 <= a <= b <= c <= max_val."""
    for a in range(max_val + 1):
        for b in range(a, max_val + 1):
            for c in range(b, max_val + 1):
                yield a, b, c


def all_chains():
    """Yield (mostly_alive, mostly_dead, doa) IPV string triples."""
    for (a1, b1, c1) in nd_triples(1):
        for (a2, b2, c2) in nd_triples(2):
            for (a3, b3, c3) in nd_triples(3):
                for (a4, b4, c4) in nd_triples(3):
                    yield (f"0,{a1},{a2},{a3},{a4}",
                           f"0,{b1},{b2},{b3},{b4}",
                           f"0,{c1},{c2},{c3},{c4}")


if __name__ == "__main__":
    if "--count" in sys.argv:
        print(sum(1 for _ in all_chains()))
    else:
        for ma, md, doa in all_chains():
            print(f"{ma}\t{md}\t{doa}")
