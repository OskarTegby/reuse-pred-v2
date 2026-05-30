# exp009 — PC-Indexed bHIST

## Motivation

Currently bHIST is indexed by **block address alone**, which suffers from aliasing — multiple PCs that touch different addresses can compete in the same entry if they hash to the same slot. By indexing with **(PC, address)**, we reduce aliasing and allow the predictor to capture PC-specific patterns.

**Hypothesis**: PC-indexed bHIST will outperform flat address-indexed bHIST on most workloads due to reduced aliasing and better capture of per-PC liveness patterns.

## Design

Use the existing **PCPartitionedTable** infrastructure:
- Outer level: 256 PC slots (keyed by dpPred PC from PFQ)
- Inner level: 16 address slots per PC (keyed by block address)
- Total capacity: 256 × 16 = 4096 entries (same as current flat bHIST)
- Replacement: DoA-LFU at both levels (consistent with Phase 1 best practices)
- Optional: per-PC addr buffer (8 entries) to test if smaller inner tables benefit from staging

## Configurations

| Config | BHIST_MODE | PC_WAYS | ADDR_WAYS | ADDR_BUF | Threshold | Question |
|---|---|---|---|---|---|---|
| `pc_256x16` | pc | 256 | 16 | 0 | (0,0) | Baseline PC-indexed; matches flat capacity |
| `pc_256x16_buf` | pc | 256 | 16 | 8 | (0,0) | Does per-addr buffer help? |
| `pc_default` | pc | 256 | 16 | 0 | (6,6) | Real-world performance? |

## Experiment Scope

- **Traces**: All QMM workloads (45 traces) — establish general applicability
- **Comparison baseline**: flat address-indexed bHIST (BHIST_WAYS=4096, no buffer) at same thresholds
- **Metrics**: geomean speedup, per-workload speedup, hit rates/promotion stats

## Expected Outcome

PC-indexed bHIST should improve bypass prediction by 1–3 percentage points due to reduced aliasing. If much larger (>5pp), indicates strong PC correlation; if much smaller (<0.5pp), address indexing is already near-optimal.

## Follow-up

Results feed into Phase 2 planning: does the PC context + address combination provide clearer signals for replacement policy assistance?
