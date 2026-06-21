# Figure 1: SRRIP-Live Threshold Sensitivity

## Data Source

**Threshold Sweep Results:** `results/{suite}_srrip_live_thd_pc_{date}/srrip_live_thd{threshold}/`

**Baseline:** θ=1 (minimum threshold) for each suite

## Methodology

Figure 1 shows **relative improvement across thresholds** - how much better SRRIP-Live performs at each threshold compared to θ=1.

Each suite uses its θ=1 SRRIP-Live results as the reference point (0% improvement by definition), then compares higher thresholds to this baseline.

This avoids external baseline dependencies and focuses on the threshold sensitivity effect: **how does the DoA classification threshold affect SRRIP-Live performance?**

## Configuration Details

All results from threshold sweep experiments (May 2026):
- Binary: `champsim_verify` (standard configuration)
- Cache: 8MB LLC, 16-way associative
- STLB: 512 entries
- Replacement policy: `srrip_live` at thresholds {1, 2, 4, 8, 16}
- Liveness classification: 3-way (DoA, mostly-dead, mostly-alive)
- PC-indexed bHIST: 512 entries, 8-way address hash
- Per-workload IPC extracted from `champsim.out`

## Results Observed

| Suite | θ=1 | θ=4 | θ=8 | θ=16 | Pattern |
|-------|-----|-----|-----|------|---------|
| DPC3  | 0.0% | +0.6% | +0.9% | +0.8% | Modest improvement, peaks at θ=8 |
| GAP   | 0.0% | -0.3% | +0.4% | +0.4% | Flat across thresholds |
| GMS   | 0.0% | +1.4% | +2.1% | +2.4% | Steady improvement with higher θ |
| Google | 0.0% | +6.3% | +7.4% | +7.1% | Strong improvement, peaks at θ=8 |
| Ligra | 0.0% | +4.8% | +5.0% | +5.7% | Improvement continues to θ=16 |
| ML    | 0.0% | +1.1% | +2.1% | +2.2% | Modest improvement |
| QMM   | 0.0% | +1.8% | +1.6% | +1.3% | Improvement peaks at θ=4 |
| Maz   | (no data) | — | — | — | Missing threshold sweep data |

## Key Insights

1. **Google & Ligra benefit most from higher thresholds** - both show 6-7% additional improvement from θ=1 to optimal
2. **QMM has narrow optimal window** - best improvement at θ=4, degrades slightly at higher thresholds
3. **DPC3 & GAP relatively threshold-insensitive** - changes <1% across range
4. **GMS shows monotonic improvement** - gets better with increasing threshold

This shows that the DoA threshold (θ) is a critical tuning parameter with suite-dependent optimal values.
