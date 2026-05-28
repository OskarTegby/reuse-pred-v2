# 003 — Bounded history tables with LFU/LRU/SRRIP replacement

**Date**: 2026-05-28
**Branch**: bypass-predictor-reevaluation
**Commit**: a081781be794

---

## What was changed

Both history tables were converted from unbounded fold-XOR maps to
bounded HistTable structures with explicit replacement policies:

- **pHIST**: changed from `map<vpn_hash, map<pc_hash, counter>>` (2D,
  VPN×PC indexed) to a 1D `HistTable` indexed by raw PC only. Capacity
  set by `PHIST_WAYS` (default 1024).
- **bHIST**: changed from `map<block_hash, counter>` (fold-XOR, 12-bit
  key) to a `HistTable` indexed by raw block address. Capacity set by
  `BHIST_WAYS` (default 4096).
- **Shadow table**: extended to store (VPN, data, PC) so the PC
  confidence can be reset on re-access.
- **Replacement policy**: selected by `HIST_REPL=lru|lfu|srrip`
  (default: lru).

**Note**: This experiment simultaneously changed the pHIST structure
(dropped the VPN dimension) and introduced replacement policies. The
two changes are confounded — the results below cannot be attributed
solely to the replacement policy. This is why results are treated as
indicative rather than definitive, and why the follow-up (004) runs
controlled ablations.

---

## Results (QMM, 45 traces, 1MB LLC)

| Config | (0,0) | (6,6) |
|---|---|---|
| LRU | +3.47% | +0.14% |
| LFU | +7.27% | +6.12% |
| SRRIP | +3.64% | +0.46% |
| fold-XOR maps (exp 001) | +7.56% | +0.95% |

---

## Conclusion and decision

LFU is the best-performing replacement policy. At the default threshold
(6,6), LFU achieves +6.12% — a large improvement over the fold-XOR
baseline (+0.95%) and close to the fold-XOR optimal (+7.56%). LRU and
SRRIP regress substantially, suggesting they evict entries that the
fold-XOR maps retained through aliasing.

The absolute numbers are confounded by the simultaneous pHIST structural
change and should be discarded as quantitative claims. The relative
ordering (LFU >> SRRIP > LRU) is treated as reliable.

**Decision**: proceed with LFU. The next experiment (004) isolates each
table's contribution and studies the effect of shrinking table capacity.
