# Experiment Log: liveness-guided-replacement branch

## Exp-001: SRRIP-Live Threshold Sweep — All Suites Baseline

**Purpose**: Establish optimal threshold baselines for each benchmark suite using the validated 2-class liveness design (DoA vs mostly_alive).

**Branch**: liveness-guided-replacement (validation complete: 0.00% diff vs 3-class design)

**Thresholds**: 1, 2, 4, 8, 16

**Date Submitted**: 2026-06-01 (CANCELLED — design changed)

**Status**: CANCELLED (superseded by Exp-002)

---

## Exp-002: Three-Policy LLC Replacement Comparison

**Purpose**: Compare three LLC replacement policies to isolate the impact of liveness-guided replacement:
1. **LRU Baseline** (champsim_lru): Standard LRU replacement — 1 job per suite
2. **Standard SRRIP** (champsim_srrip): SRRIP without liveness guidance — 1 job per suite
3. **Modified SRRIP-Live** (champsim_srrip_live): SRRIP with liveness guidance in LLC ONLY — 5 jobs per suite (thresholds)

**Branch**: liveness-guided-replacement

**Key Change**: SRRIP-Live now applies liveness-guided insertion/promotion to LLC only; STLB uses standard SRRIP behavior.

**Date Submitted**: 2026-06-01 (corrected final submission)

### Results Directories (Exp-002, final corrected)

| Suite | Output Directory | Job IDs | Structure |
|-------|------------------|---------|-----------|
| DPC3 | dpc3_policy_sweep_pc_20260601_0015 | 1403756–1403762 | lru, srrip, srrip_live/thd{1,2,4,8,16} |
| Google | google_policy_sweep_pc_20260601_0015 | 1403763–1403769 | lru, srrip, srrip_live/thd{1,2,4,8,16} |
| QMM | qmm_policy_sweep_pc_20260601_0015 | 1403770–1403776 | lru, srrip, srrip_live/thd{1,2,4,8,16} |
| GAP | gap_policy_sweep_pc_20260601_0015 | 1403777–1403783 | lru, srrip, srrip_live/thd{1,2,4,8,16} |
| GMS | gms_policy_sweep_pc_20260601_0015 | 1403784–1403790 | lru, srrip, srrip_live/thd{1,2,4,8,16} |
| Ligra | ligra_policy_sweep_pc_20260601_0015 | 1403791–1403797 | lru, srrip, srrip_live/thd{1,2,4,8,16} |
| ML | ml_policy_sweep_pc_20260601_0015 | 1403798–1403804 | lru, srrip, srrip_live/thd{1,2,4,8,16} |

### Configuration (Exp-002)

- **LLC**: 1MB (1024 sets × 16 ways × 64 bytes), 40-cycle latency
- **STLB**: 512 entries (128 sets × 8 ways), 8-cycle latency
- **Binaries**:
  - champsim_lru: Standard LRU replacement (threshold-insensitive)
  - champsim_srrip: Standard SRRIP (threshold-insensitive, no liveness)
  - champsim_srrip_live: SRRIP with liveness guidance in LLC ONLY (threshold-sensitive)
- **Liveness Data**: PC-indexed bHIST (512 entries, 8-way)
- **MID_THD**: Thresholds {1, 2, 4, 8, 16} for SRRIP-Live only

### Submission Details (Exp-002, 2026-06-01, final)

- **Total jobs**: 49 (7 suites × 7 job arrays each)
- **Job structure per suite**: 1 LRU + 1 SRRIP + 5 SRRIP-Live threshold variants
- **Total traces**: ~375 × 7 = ~2,625 across all suites
- **Warmup**: 50M cycles
- **Simulation**: 100M cycles
- **Submission time**: ~20 minutes (sequential per suite)
- **Monitor**: `qstat -u $USER` on castillo cluster

### Why Only SRRIP-Live Has Thresholds

- **LRU**: No liveness classification → threshold (MID_THD) has no effect → 1 job
- **SRRIP**: Plain SRRIP, no liveness → threshold (MID_THD) has no effect → 1 job
- **SRRIP-Live**: Uses liveness classification threshold → need 5 jobs to measure sensitivity across {1,2,4,8,16}
