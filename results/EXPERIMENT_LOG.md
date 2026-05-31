# Experiment Log: liveness-guided-replacement branch

## Exp-001: SRRIP-Live Threshold Sweep — All Suites Baseline

**Purpose**: Establish optimal threshold baselines for each benchmark suite using the validated 2-class liveness design (DoA vs mostly_alive).

**Branch**: liveness-guided-replacement (validation complete: 0.00% diff vs 3-class design)

**Thresholds**: 1, 2, 4, 8, 16

**Date Submitted**: 2026-06-01

### Results Directories

| Suite | Output Directory | Job IDs (thd1-thd16) | Status |
|-------|------------------|----------------------|--------|
| DPC3 | dpc3_srrip_live_thd_pc_20260601_0003 | 1403595–1403599 | RUNNING |
| Google | google_srrip_live_thd_pc_20260601_0003 | 1403600–1403604 | RUNNING |
| QMM | qmm_srrip_live_thd_pc_20260601_0003 | 1403605–1403609 | RUNNING |
| GAP | gap_srrip_live_thd_pc_20260601_0003 | 1403610–1403614 | RUNNING |
| GMS | gms_srrip_live_thd_pc_20260601_0003 | 1403615–1403619 | RUNNING |
| Ligra | ligra_srrip_live_thd_pc_20260601_0003 | 1403620–1403624 | RUNNING |
| ML | ml_srrip_live_thd_pc_20260601_0003 | 1403625–1403629 | RUNNING |

### Configuration

- Binary: champsim_srrip_live (2-class liveness)
- Cache: 8MB LLC, 16-way associative
- STLB: 512 entries
- Liveness indexing: PC-indexed (--mid-key pc)
- PC-indexed bHIST: 512 entries, 8-way

### Submission Details (2026-06-01)

- Total jobs: 35 (7 suites × 5 thresholds)
- Total traces: ~500+ across all suites
- Warmup: 50M cycles
- Simulation: 100M cycles
- Submission time: Immediate sequential launch, completed within same hour
- Monitor: `qstat -u $USER` on castillo cluster

### Notes

- Validated 2-class design (DoA vs mostly_alive) matches original 3-class (0.00% IPC difference)
- These results serve as the official baseline for the liveness-guided replacement policy
- Once complete, will extract optimal threshold per suite for next phase (assisted replacement)
