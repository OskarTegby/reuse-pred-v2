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

### Results Directories (Exp-002, corrected with thresholds)

| Suite | Output Directory | Job IDs (LRU, SRRIP, SRRIP-Live × 5 thresholds) | Thresholds |
|-------|------------------|--------------------------------------------------|------------|
| DPC3 | dpc3_policy_sweep_pc_20260601_0012 | 1403651–1403665 | 1,2,4,8,16 |
| Google | google_policy_sweep_pc_20260601_0012 | 1403666–1403680 | 1,2,4,8,16 |
| QMM | qmm_policy_sweep_pc_20260601_0012 | 1403681–1403695 | 1,2,4,8,16 |
| GAP | gap_policy_sweep_pc_20260601_0012 | 1403696–1403710 | 1,2,4,8,16 |
| GMS | gms_policy_sweep_pc_20260601_0012 | 1403711–1403725 | 1,2,4,8,16 |
| Ligra | ligra_policy_sweep_pc_20260601_0012 | 1403726–1403740 | 1,2,4,8,16 |
| ML | ml_policy_sweep_pc_20260601_0012 | 1403741–1403755 | 1,2,4,8,16 |

### Configuration (Exp-002)

- **LLC**: 1MB (1024 sets × 16 ways × 64 bytes), 40-cycle latency
- **STLB**: 512 entries (128 sets × 8 ways), 8-cycle latency
- **Binaries**:
  - champsim_lru: Standard LRU replacement everywhere
  - champsim_srrip: Standard SRRIP everywhere (no liveness guidance)
  - champsim_srrip_live: SRRIP with liveness guidance in LLC ONLY (STLB uses standard SRRIP)
- **Liveness Data**: PC-indexed bHIST (512 entries, 8-way)
- **MID_THD**: Default = 1 (threshold for DoA classification)

### Submission Details (Exp-002, 2026-06-01, corrected)

- Total jobs: 105 (7 suites × 3 policies × 5 thresholds)
- Total traces: ~375 × 15 = ~5,625 across all suites/configs
- Warmup: 50M cycles
- Simulation: 100M cycles
- Submission time: Sequential per suite, completed ~45 minutes
- Monitor: `qstat -u $USER` on castillo cluster
- Per-policy structure: `{suite}_policy_sweep_pc_20260601_0012/{policy}/thd{threshold}/`

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
