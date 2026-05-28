# 001 — Bounded history tables with promotion buffer and SRRIP replacement

## Problem

Both pHIST and bHIST are currently fully-associative tables backed by a flat
vector with linear-scan lookup. bHIST is address-indexed, so the key space is
large: most entries are one-time dead blocks that fill the table and displace
genuinely persistent entries. There is no filtering — every first death earns
a slot in the main table immediately.

## Idea

Split the history table into two stages:

**Promotion buffer** — small staging area (e.g. 128–256 entries, FIFO or LRU).
New entries land here first. When an entry accumulates enough hits (dead
evictions) to meet the promotion threshold K, it graduates to the main table.
Entries that age out of the buffer without reaching K are discarded. This
filters one-time dead blocks cheaply without consuming main-table capacity.

**Main history table** — uses SRRIP replacement (chosen over LRU/LFU for
server workloads, which mix hot working sets with scan-like streaming accesses).
Entries enter at RRPV=2 (distant). Subsequent confirmed deaths set RRPV=0.
Eviction targets RRPV=3 (with the usual increment-all fallback).

## Key parameters

| Parameter | Role | Starting point |
|---|---|---|
| Buffer capacity | How many candidates are staged | 256 |
| Promotion threshold K | Deaths required before main-table admission | 2 |
| Main table capacity | Controlled by BHIST_WAYS / PHIST_WAYS | 4096 / 1024 |
| SRRIP insertion RRPV | Priority of newly admitted entries | 2 |

## Applicability

Most pressing for bHIST (address-indexed, high noise due to large key space).
pHIST is PC-indexed and accumulates counts faster, so the buffer is less
critical there, but the same structure applies.

## Status

Proposed. Replacement policy sweep (LRU / LFU / SRRIP) currently running on
QMM to establish a baseline before adding the buffer stage.
