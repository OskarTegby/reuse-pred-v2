# Results summary — history table design (QMM, 1MB LLC, 45 traces)

All speedups are geomean IPC vs the no-predictor baseline
(`qmm_1mb_20260527_1543/baseline`), threshold (0,0), 50M warmup + 100M sim.

## Headline progression

| Milestone | Config | Speedup |
|---|---|---|
| Original | fold-XOR full predictor | +7.56% |
| exp004 | bounded LFU (addr-indexed bHIST) | +7.27% |
| exp005a | DoA-LFU pHIST + LFU bHIST | +13.05% |
| exp005b | **SRRIP + two-stage buffer, both tables** | **+14.94%** |

Net: **+7.56% → +14.94%**, roughly doubling the speedup, by reworking the
history-table replacement policy and adding a promotion buffer.

## exp004 — bounded LFU vs fold-XOR

| Config | Speedup |
|---|---|
| fold-XOR full (0,0) | +7.56% |
| bounded LFU full (0,0) | +7.27% |

A bounded 1024/4096 LFU table matches the unbounded fold-XOR maps. This is the
starting point for the policy work.

## exp005a — DoA-LFU and promotion buffer, isolated per table

Baseline for this group is bounded LFU full = +7.27%.
(Buffer rows here used standard LFU in the main table and were superseded by
exp005b; the DoA rows are the durable result.)

| Config | Speedup | vs +7.27% |
|---|---|---|
| DoA-LFU pHIST only | +13.05% | +5.78pp |
| DoA-LFU bHIST only | +7.06% | −0.21pp |
| DoA-LFU both | +12.07% | +4.80pp |

**Conclusion:** essentially all the gain is in pHIST. DoA-LFU (freq increments
only on dead evictions) stops high-traffic PCs that touch live pages from
evicting reliable dead-page predictors. bHIST is already PFQ-pre-filtered, so
DoA-LFU adds nothing there.

## exp005b — fixed SRRIP + two-stage buffer

The SRRIP `on_hit` bug was fixed: dead eviction → rrpv=0 (protect),
live eviction → rrpv=SRRIP_MAX (demote, becomes eviction target → re-enters
buffer). Buffer is DoA-LFU (evict min dead_count); promotion is best-buffer-beats-
worst-main; evicted main entries re-enter the buffer (closed loop).

| Config | Speedup |
|---|---|
| SRRIP pHIST only | +5.91% |
| SRRIP bHIST only | +11.12% |
| SRRIP both | +5.41% |
| SRRIP+buf pHIST | +14.09% |
| SRRIP+buf bHIST | +13.11% |
| **SRRIP+buf both** | **+14.94%** |

**Conclusions:**
- Standalone SRRIP *hurts* pHIST (+5.91% vs DoA-LFU's +13.05%): its aging
  evicts PC entries too aggressively.
- Standalone SRRIP *helps* bHIST a lot (+11.12% vs DoA-LFU's +7.06%): the wide
  address key space benefits from recency-based aging.
- The two-stage buffer rescues SRRIP in pHIST (+14.09%) and amplifies it in
  bHIST (+13.11%): evicted entries get a second chance via re-entry + promotion.
- SRRIP+buffer in **both** tables is the best design so far at **+14.94%**.

## exp005b — pHIST buffer size sweep (SRRIP+buf pHIST)

| Buffer size | Speedup |
|---|---|
| 64 | +14.09% |
| 128 | +14.09% |
| 256 | +14.03% |
| 512 | +14.03% |

**Conclusion:** flat across 64–512 (within noise). The benefit is from the
*mechanism* (re-entry + DoA-LFU promotion gate), not buffer capacity. Even 64
entries suffice.

## Open / next

- Hit-rate and promotion stats now instrumented (PHIST/BHIST_HIT_RATE,
  PROMOTIONS, PROMOTED_HIT_RATE). Need the same hit-rate stat for the hashed
  (fold-XOR) predictor for a like-for-like utilisation comparison.
- pHIST / bHIST size sweeps under the SRRIP+buffer design (does the +14.94%
  design tolerate smaller tables better than plain LFU did?).
