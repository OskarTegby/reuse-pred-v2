# 002 — PC-indexed bHIST via dpPred PC carried through the PFQ

## Problem

bHIST is currently indexed by block address. The block address space is large,
so most entries are one-time observations (a block dies once and its address is
never seen again). The confidence counter rarely accumulates, especially at the
default threshold (6,6), which is why default-threshold performance (+0.95%)
lags far behind optimal (+7.56%).

## Idea

Carry the dpPred PC alongside the PFN in the PFQ (change `deque<uint64_t>` to
`deque<pair<uint64_t, uint64_t>>`). When cbPred gets a PFQ hit, it extracts
the PC that caused the dpPred bypass and uses it as the bHIST key instead of
the block address.

At LLC fill: store the dpPred PC in the BLOCK (new field, analogous to `dp`)
so `update_eviction_counters` can train bHIST with the correct PC at eviction
time, even if the PFQ entry has since aged out.

## Why this helps

- **Key space collapse**: only PCs that triggered dpPred bypasses contribute —
  a small, pre-filtered set rather than the full block address space.
- **Faster counter accumulation**: all LLC fills from pages flagged by the same
  dpPred PC map to one bHIST entry, so the confidence counter grows across
  every block within every dead page touched by that PC.
- **Tighter coupling**: bHIST answers "do LLC fills from pages flagged by
  dpPred PC X consistently die?" rather than "has this specific block address
  died before?" — a more meaningful and stable question.

## Design decisions

- **PC-only vs (PC, address)**: start with PC-only. If too coarse (same dpPred
  PC touches both live and dead blocks across different pages), add the block
  address as a secondary dimension.
- **dpPred PC vs LLC-load PC**: the dpPred PC (STLB miss) is used, not the LLC
  load PC. The former is already proven to be a dead-page predictor; we are
  asking whether it also predicts dead blocks within those pages.
- **PFQ capacity**: unchanged (default 8). Each entry grows by one uint64_t.

## Interaction with promotion buffer (idea 001)

The PC-indexed bHIST key naturally reduces noise, which partially substitutes
for the promotion buffer. The two ideas compose: the buffer stages entries by
dpPred PC and only admits those that die repeatedly across multiple fills.

## Status

Proposed. Implement on bHIST first; evaluate on QMM before extending to pHIST.
