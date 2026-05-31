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
1. **LRU Baseline** (champsim_lru): Standard LRU replacement
2. **Standard SRRIP** (champsim_srrip): SRRIP without liveness guidance
3. **Modified SRRIP-Live** (champsim_srrip_live): SRRIP with liveness guidance in LLC ONLY

**Branch**: liveness-guided-replacement

**Key Change**: SRRIP-Live now applies liveness-guided insertion/promotion to LLC only; STLB uses standard SRRIP behavior.

**Date Submitted**: 2026-06-01

### Results Directories (Exp-002)

| Suite | Output Directory | Job IDs (LRU, SRRIP, SRRIP-Live) | Status |
|-------|------------------|-----------------------------------|--------|
| DPC3 | dpc3_policy_sweep_pc_20260601_0011 | 1403630, 1403631, 1403632 | RUNNING |
| Google | google_policy_sweep_pc_20260601_0011 | 1403633, 1403634, 1403635 | RUNNING |
| QMM | qmm_policy_sweep_pc_20260601_0011 | 1403636, 1403637, 1403638 | RUNNING |
| GAP | gap_policy_sweep_pc_20260601_0011 | 1403639, 1403640, 1403641 | RUNNING |
| GMS | gms_policy_sweep_pc_20260601_0011 | 1403642, 1403643, 1403644 | RUNNING |
| Ligra | ligra_policy_sweep_pc_20260601_0011 | 1403645, 1403646, 1403647 | RUNNING |
| ML | ml_policy_sweep_pc_20260601_0011 | 1403648, 1403649, 1403650 | RUNNING |

### Configuration (Exp-002)

- **LLC**: 1MB (1024 sets × 16 ways × 64 bytes), 40-cycle latency
- **STLB**: 512 entries (128 sets × 8 ways), 8-cycle latency
- **Binaries**:
  - champsim_lru: Standard LRU replacement everywhere
  - champsim_srrip: Standard SRRIP everywhere (no liveness guidance)
  - champsim_srrip_live: SRRIP with liveness guidance in LLC ONLY (STLB uses standard SRRIP)
- **Liveness Data**: PC-indexed bHIST (512 entries, 8-way)
- **MID_THD**: Default = 1 (threshold for DoA classification)

### Submission Details (Exp-002, 2026-06-01)

- Total jobs: 21 (7 suites × 3 policies)
- Total traces: ~375 across all suites
- Warmup: 50M cycles
- Simulation: 100M cycles
- Submission time: Sequential per suite, completed ~15 minutes
- Monitor: `qstat -u $USER` on castillo cluster

### Design Changes from Exp-001

1. **SRRIP-Live modification**: Now applies liveness guidance to LLC ONLY
   - LLC: DoA blocks inserted at maxRRPV (immediate eviction candidate)
   - STLB: Standard SRRIP insertion/promotion (no liveness guidance)
   - Rationale: Isolate impact of liveness-guided replacement in LLC

2. **Three-policy comparison**:
   - Establishes LRU baseline performance per suite
   - Standard SRRIP control (no liveness benefit)
   - Modified SRRIP-Live test case (liveness benefit in LLC only)

3. **Clear hypothesis**: Liveness-guided replacement improves performance in LLC; STLB does not need it
