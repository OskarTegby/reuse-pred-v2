# 005 — DoA-LFU, promotion buffer, and PC-partitioned bHIST

**Date**: 2026-05-29
**Branch**: bypass-predictor-reevaluation
**Commit**: bf82dec848b8 (jobs submitted from this state)

**005a — per-table isolation** (running): 1403491–1403496, 270 tasks, `qmm_table_policy_20260529_1520`

**005b — fixed SRRIP + two-stage buffer** (running): 1403503–1403508, 270 tasks, `qmm_srrip_20260529_2252`
- `srrip_phist/bhist/both`: fixed SRRIP (dead→rrpv=0, alive→rrpv=SRRIP_MAX) standalone
- `srrip_buf_phist/bhist/both`: SRRIP + 128-entry DoA-LFU buffer with re-entry on eviction

**007 — Default threshold validation** (running): 1403512–1403517, 270 tasks, `qmm_srrip_default_20260530_1406`
- Re-runs 005b configs at (6,6) threshold to validate +14.94% holds in practice

**008 — Size sensitivity at (0,0)** (running): 1403532–1403545, 630 tasks, `qmm_sizes_optimal_20260530_1409`
- pHIST buffer sweep: 0, 32, 64, 128, 256, 512 entries
- pHIST table size: 256, 512, 1024, 2048 ways
- bHIST table size: 1024, 2048, 4096, 8192 ways

**011 — Shrunk tables with larger buffers** (running): 1403546–1403547, 90 tasks, `qmm_exp011_shrunk_20260530_1923`
- Test mechanism value of buffers (shrink main, enlarge buffer, total constant)

**012 — PC-indexed bHIST for bypass only** (running): 1403548–1403549, 90 tasks, `qmm_exp012_pcbhist_bypass_20260530_1923`
- Isolate pure bypass prediction value (256×16=4096 entries, same budget as flat)

**013–014 — Pending Phase 2 implementation** (replacement policy guidance):
- exp013: PC-indexed bHIST for replacement guidance only
- exp014: PC-indexed bHIST for both bypass + replacement (full integration)

**005c — deferred** (pending 005a/005b results):
- `lfu_doa_buf_opt`: flat bHIST, DoA-LFU, buffer=256 — does buffer compound DoA-LFU?
- `pc_opt`: PCPartitionedTable 256×16, no addr buffer
- `pc_buf_opt`: PCPartitionedTable 256×16, addr buffer=8
- Groups 3+4 from original plan: flat DoA-LFU size sweep (2048→128 with/without buffer),
  PC-partitioned addr_ways sweep (16→8→4→2 with/without buffer)

---

## Motivation

Experiment 004 established that LFU outperforms LRU/SRRIP for the flat
address-indexed bHIST, and that the bHIST size sweep shows graceful degradation
below 1024 entries. Three follow-on directions are tested here:

1. **DoA-LFU**: in standard LFU, a live eviction (accessed=true) increments
   freq just as a dead one does. This is wrong for a bypass predictor — a live
   eviction tells us the entry was reused and is not a good bypass candidate, so
   it should not raise its eviction priority. DoA-LFU increments freq only on
   dead (DoA) evictions, keeping entries that are *persistently* dead at the top
   of the eviction priority list.

2. **Promotion buffer**: new entries enter a small FIFO staging area first.
   An entry is promoted to the main table only when its accumulated dead count
   exceeds the current LFU victim's freq. This filters one-off dead accesses
   cheaply and prevents noisy entries from displacing confirmed-dead ones.

3. **PC-partitioned bHIST**: bHIST keyed by (dpPred PC, block address) instead
   of block address alone. The outer PC level collapses the key space to the
   small set of dpPred PCs; the inner addr level tracks which specific block
   addresses under each PC have been consistently dead. Requires a PFQ hit to
   obtain the dpPred PC. Implemented as PCPartitionedTable (256 PC × 16 addr).

---

## Questions this experiment is designed to answer

**Group 1 — Flat bHIST policy comparison (4096 entries)**

1. Does DoA-LFU outperform standard LFU for the flat address-indexed bHIST?
   Compare: `lfu_doa_opt` vs `lfu_opt` (reference, matches exp004 lfu_full_opt).

2. Does the promotion buffer help standard LFU?
   Compare: `lfu_buf_opt` vs `lfu_opt`.

3. Does the promotion buffer help DoA-LFU?
   Compare: `lfu_doa_buf_opt` vs `lfu_doa_opt`.

4. What is the best flat bHIST configuration overall?
   Compare all four Group 1 configs.

**Group 2 — PC-partitioned bHIST (256 PC × 16 addr = 4096 total)**

5. Does the PC-partitioned bHIST (with DoA-LFU at both levels) beat the best
   flat bHIST configuration?

6. Does the per-PC addr promotion buffer help the PC-partitioned structure?
   Compare: `pc_buf_opt` vs `pc_opt`.

**Group 3 — Flat bHIST size sweep with DoA-LFU**

7. Does DoA-LFU change the size sensitivity vs standard LFU (exp004 Group 3)?
   Compare degradation curves: LFU_DOA vs LFU across 4096→128 entries.

8. Does the promotion buffer extend useful range to smaller sizes?
   Compare: `flat_doa_buf_{N}` vs `flat_doa_{N}` across all sizes.
   If the buffer allows a smaller main table to match a larger table without it,
   the buffer is substituting for capacity.

**Group 4 — PC-partitioned addr_ways sweep (pc_ways fixed at 256)**

9. How many addr slots per PC are needed? At what point does the inner table
   become too small to track the full per-PC address distribution?

10. Does the per-PC addr buffer extend useful range at smaller addr_ways?

---

## Configs

All configs: DPPRED=1, CBPRED=1, THD=(0,0), QMM 45 traces, 1MB LLC, LRU
replacement, 50M warmup + 100M simulation instructions.

### Group 1 — Flat bHIST policy comparison

| Config | BHIST_MODE | HIST_REPL | BHIST_WAYS | BHIST_BUF_CAP |
|---|---|---|---|---|
| lfu_opt | flat | lfu | 4096 | 0 |
| lfu_doa_opt | flat | lfu_doa | 4096 | 0 |
| lfu_buf_opt | flat | lfu | 4096 | 256 |
| lfu_doa_buf_opt | flat | lfu_doa | 4096 | 256 |

### Group 2 — PC-partitioned bHIST

| Config | BHIST_MODE | BHIST_PC_WAYS | BHIST_ADDR_WAYS | BHIST_ADDR_BUF |
|---|---|---|---|---|
| pc_opt | pc | 256 | 16 | 0 |
| pc_buf_opt | pc | 256 | 16 | 8 |

### Group 3 — Flat DoA-LFU size sweep

| Config | BHIST_WAYS | BHIST_BUF_CAP |
|---|---|---|
| flat_doa_2048 | 2048 | 0 |
| flat_doa_1024 | 1024 | 0 |
| flat_doa_512 | 512 | 0 |
| flat_doa_256 | 256 | 0 |
| flat_doa_128 | 128 | 0 |
| flat_doa_buf_2048 | 2048 | 256 |
| flat_doa_buf_1024 | 1024 | 256 |
| flat_doa_buf_512 | 512 | 256 |
| flat_doa_buf_256 | 256 | 256 |
| flat_doa_buf_128 | 128 | 256 |

### Group 4 — PC-partitioned addr_ways sweep (pc_ways=256)

| Config | BHIST_ADDR_WAYS | BHIST_ADDR_BUF |
|---|---|---|
| pc_a8 | 8 | 0 |
| pc_a4 | 4 | 0 |
| pc_a2 | 2 | 0 |
| pc_a8_buf | 8 | 8 |
| pc_a4_buf | 4 | 8 |

---

## Results

*(to be filled in when jobs complete)*

---

## Observations

*(to be filled in when jobs complete)*
