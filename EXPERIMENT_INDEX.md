# Complete Experiment Index and Data Tracking

This document serves as the master index for all experimental data, analysis, and documentation related to the cache liveness prediction research.

**Project**: Liveness-Guided Cache Replacement and Prediction  
**Primary Investigators**: Oskar Tegby, Alberto Ros  
**Institution**: Computer Architecture Group, University of Murcia  
**Status**: Active — scoring mode selection complete; history-table replacement policy under evaluation (2026-06-09)

---

## Quick Navigation

### Documents

| Document | Purpose | Location |
|----------|---------|----------|
| **DATA_SOURCES.md** | Mapping of figures/results to experiments | `results/paper/DATA_SOURCES.md` |
| **DATA_PROVENANCE.md** | Detailed provenance, commits, parameters | `results/report/DATA_PROVENANCE.md` |
| **DEVELOPMENT.md** | Paper development guide | `results/paper/DEVELOPMENT.md` |
| **This file** | Master index and overview | `./EXPERIMENT_INDEX.md` |

### Research Documents

| Document | Type | Status | Path |
|----------|------|--------|------|
| **HPCA 2026 Paper** | Paper submission | In progress | `results/paper/main.tex` → `main.pdf` |
| **Comprehensive Report** | Technical report | Complete | `results/report/build/report.pdf` |
| **Research Phase Plan** | Strategy document | Memory file | `.claude/projects/*/memory/research_phase_plan.md` |

---

## Data Organization by Branch

### liveness-replacement (Primary Results Branch)

**Status**: Complete experimental data collected  
**Primary commits**:

```
99539c2ac032 - feat: extend PACIPV with liveness-class dimension (HEAD)
24fe4735adcf - feat: extend srrip_live to 3-way liveness classification
72ec846a5f91 - feat: add ipv_live — liveness-class IPV replacement policy
547bc52356ef - feat: add srrip_live — SRRIP with liveness-informed insertion
```

**Key results**:

| Metric | QMM | Google | DPC3 | GAP | Notes |
|--------|-----|--------|------|-----|-------|
| SRRIP-Live (LLC) | 4-5% | 2-3% | 2% | 7.9% | Optimal THD varies by suite |
| IPV-Live (LLC) | ~4% | ~3% | ~2% | 11.2% | Learned vectors better for concentrated patterns |
| **ipv_live_both (LLC+STLB)** | **8%** | **4-5%** | ~2% | N/A | **Best combined result** |

**Experimental data location**: `/home/users/otegby/ChampSim-dev/results/`

```
{qmm,google,dpc3,gap,gms,ligra,aiml}_srrip_live_thd_pc_20260520_*
{qmm,google,dpc3,gap,gms,ligra,aiml}_ipv_live_thd_pc_20260520_*
{*}_missing_policy_20260521_*
```

---

### bypass-predictor-reevaluation (Validation Branch)

**Status**: Running validation jobs (as of 2026-05-31)  
**Purpose**: Verify 3-way liveness + learned vectors against 2-class simplified version  
**Job IDs**: 1403591, 1403592 (validation), 1403593, 1403594 (baseline)

**Expected upon completion**:
- Confirmation that 3-way liveness provides ~8% speedup on Qualcomm
- Baseline comparison showing integrated approach matches original implementation
- Data for exp016 (512×8 bHIST budget) and exp017 (unbounded characterization)

---

## Experiment Taxonomy

### Phase 1: Characterization (Complete)

Goal: Understand liveness patterns across workloads

| Exp | Name | Traces | Parameters | Results | Status |
|-----|------|--------|-----------|---------|--------|
| - | Liveness breakdown | 7 suites | 50M warmup, 100M sim | Figures 1-2 | ✓ Complete |
| - | LLC-STLB correlation | 7 suites | Same | Figures 3-4 | ✓ Complete |
| 001-009 | Bypass prediction | 3 suites (legacy) | dpPred, cbPred variants | Figures 5-6 | ✓ Complete |

### Phase 2: Replacement Policy Development (Complete)

Goal: Design and validate liveness-guided replacement

| Exp | Name | Suites | Thresholds | Policies | Status | Key Commits |
|-----|------|--------|-----------|----------|--------|-------------|
| 010 | SRRIP-Live LLC threshold | 7 | 1,2,4,8,16 | srrip_live | ✓ Complete | 547bc52356ef |
| 011 | IPV-Live threshold | 3 | 1,2,4,8,16 | ipv_live | ✓ Complete | 72ec846a5f91 |
| 012 | 3-way classification | 7 | 1,2,4,8,16 | srrip_live (updated) | ✓ Complete | 24fe4735adcf |
| 013 | STLB policy comparison | 7 | 1,2,4,8,16 | stlb_srrip_live, stlb_ipv_live | ✓ Complete | fbc9842d906b |
| 014 | Combined LLC+STLB | 7 | Optimal | All combinations | ✓ Complete | 1287e910835e |
| 015 | Characterization unbounded | 7 | - | srrip_live, ipv_live (unbounded) | ✓ Complete | - |

### Phase 3: Integration and Validation (In Progress)

Goal: Validate integrated approach on liveness-guided-replacement branch

| Job | Name | Branch | Traces | Config | Status | IDs |
|-----|------|--------|--------|--------|--------|-----|
| Validation | SRRIP-Live integration | liveness-guided-replacement | 45 QMM | MID_THD=4,8 | ⏳ Queued | 1403591-92 |
| Baseline | SRRIP-Live original | liveness-replacement | 45 QMM | MID_THD=4,8 | ⏳ Queued | 1403593-94 |
| exp016 | 512×8 bHIST budget | liveness-guided-replacement | 7 suites | Fixed budget | ⏳ Pending | - |
| exp017 | Unbounded characterization | liveness-guided-replacement | 7 suites | Unbounded | ⏳ Pending | - |

---

## Key Results Summary

### 8% Speedup on Qualcomm (Best Case)

**Configuration**: `ipv_live_both` (combined LLC+STLB with learned vectors)

**Components**:
- 3-way liveness classification (DoA, mostly-dead, mostly-alive)
- Separate learned IPV vectors per liveness class
- Applied simultaneously to both LLC and STLB
- PC-indexed bHIST (512 entries, 8-way address hash)

**Commits involved**:
```
547bc52356ef - SRRIP-Live core implementation
72ec846a5f91 - IPV-Live with learned vectors
24fe4735adcf - 3-way classification
41236472e404 - Graduated promotion fix
fbc9842d906b - STLB support
1287e910835e - Combined policy testing
```

**Why it works**:
- Qualcomm has low LLC-STLB DoA correlation (~4%)
- Block-level liveness is recoverable even when page-level signal is lost
- IPV-Live's graduated promotion ramps are robust to mispredictions
- Combined application at both cache levels amplifies the effect

---

## Parameter Reference

### Critical Thresholds

```
DoA Threshold (MID_THD):
  SPEC (DPC3):     Optimal = 8-16     (High workload variance)
  Qualcomm (QMM):  Optimal = 4        (Server workloads, low variance)
  Google:          Optimal = 4        (Data center, consistent patterns)
  GAP:             Optimal = 1        (Frontier-access, few dead PCs)
  AI/ML:           Optimal = 16       (Non-stationary patterns)
```

### IPV-Live Vector Templates

```cpp
// High-confidence DoA: 3 hits required to reach priority
ipv_doa = {0, 0, 1, 2, maxRRPV}

// Medium-confidence mostly-dead: 2 hits required
ipv_mostly_dead = {0, 0, 0, 2, maxRRPV}

// Low-confidence mostly-alive: 1 hit required (standard SRRIP)
ipv_mostly_alive = {0, 0, 0, 0, maxRRPV-1}
```

### bHIST Configuration (exp016)

```
PC Index:   512 entries (set-associative)
Address:    8-way hashing
Total:      ~48 KB (<0.6% vs 8MB LLC)
Replacement: LFU (least-frequently-used entries evicted)
```

---

## Analysis Scripts Reference

### Primary Analysis Tools

| Script | Purpose | Input | Output | Language |
|--------|---------|-------|--------|----------|
| `plot_optimal_thd_per_benchmark.py` | Per-workload geomean per threshold | Threshold sweep dirs | Figures 7-13 | Python3 |
| `plot_combined_policy_comparison.py` | Combined LLC+STLB results | missing_policy dirs | Figure 14 | Python3 |
| `compute_correlation.py` | LLC-STLB DoA correlation | Simulation stats | Figures 3-4 | Python3 |
| `champsim_utils.py` | Shared utilities (geomean, IPC parsing) | - | Library | Python3 |

### Submission Scripts

| Script | Traces | Thresholds | Policies | Jobs |
|--------|--------|-----------|----------|------|
| `sweep_threshold_newsuites.sh` | 7 suites (88 total) | 1,2,4,8,16 | srrip_live, ipv_live | 440 |
| `sweep_missing_policy.sh` | 7 suites (88 total) | Optimal | 7 policy variants | 616 |
| `sweep_exp016.sh` | 45 QMM | Fixed (4,8) | srrip_live | 90 |
| `sweep_exp017.sh` | 45 QMM | Unbounded | srrip_live | 45 |

---

## Reproducibility Checklist

### For Replicating SRRIP-Live Results

- [ ] Check out liveness-replacement branch
- [ ] Build: `make clean && touch src/cache.cc && make static -j$(nproc)`
- [ ] Access cluster results: `/home/users/otegby/ChampSim-dev/results/`
- [ ] Look for: `{qmm,google,dpc3,*}_srrip_live_thd_pc_20260520_*`
- [ ] Run analysis: `python3 scripts/analysis/plot_optimal_thd_per_benchmark.py`
- [ ] Verify: Geomean QMM ~4-5%, Google ~2-3%, DPC3 ~2%

### For Replicating IPV-Live Results

- [ ] Same setup as above
- [ ] Look for: `{*}_ipv_live_thd_pc_20260520_*` directories
- [ ] Run same analysis script (auto-detects ipv_live dirs)
- [ ] Verify: GAP geomean 11.2% (vs 7.9% for SRRIP-Live)

### For Replicating Combined Results

- [ ] Same setup as above
- [ ] Look for: `{*}_missing_policy_20260521_*` directories
- [ ] Run: `python3 scripts/analysis/plot_combined_policy_comparison.py`
- [ ] Verify: QMM ipv_live_both ~8%, Google ipv_live_both ~4-5%

---

## Known Limitations and Caveats

1. **Threshold sensitivity**: No single threshold optimal across all workloads. Requires per-suite tuning (Table 2 in report documents this)

2. **PC-indexed history on AI/ML**: Non-stationary access patterns cause mispredictions. Address-indexed history recovers performance (Figure 10)

3. **SPEC variance**: High inter-workload variance makes geomean less meaningful than per-workload analysis

4. **LLC-STLB correlation as constraint**: 
   - High correlation (>30%): Benefit from STLB guidance
   - Low correlation (<10%): Block-level guidance alone better
   - This is **observed**, not design choice

5. **Prefetcher interaction**: Behavior changes with/without prefetching. All results use L2C next-line prefetcher enabled

6. **Cluster dependency**: All results require Castillo cluster access. Local builds need static linking due to GLIBC version mismatch

---

---

## Phase 4: Scoring Mode Selection (Complete — 2026-06-09)

**Branch**: `bypass`  
**Binary**: `champsim_srrip_live`  
**Baseline**: SRRIP (empty table = SRRIP; all speedups measured vs SRRIP)

### Scoring modes evaluated

| Mode | Name | Config | Description |
|------|------|--------|-------------|
| 0 (ref) | mode0_ref | `SCORING_MODE=0,THD_DEAD=0,THD_DOA=4` | Flat delta, DoA-only threshold |
| 0 (flat3) | mode0_flat3 | `SCORING_MODE=0,THD_DEAD=2,THD_DOA=4` | Flat delta, both thresholds |
| 3 | mode3_decoup | `SCORING_MODE=3,THD_DEAD=2,THD_DOA=4` | Decoupled confirmatory δ (1/2/3 for MA/MD/DoA) |
| 4 | mode4_cal | `SCORING_MODE=4,THD_DEAD=6,THD_DOA=4` | Calibrated GAP specialist |
| **5** | **mode5_recal** | **`SCORING_MODE=5,THD_DEAD=10,THD_DOA=20`** | **Lifespan-scaled δ (5/3/1 for MA/MD/DoA) — winner** |

### Result directories on Castillo (`~/ChampSim-dev/results/`)

| Directory | Contents | Suites |
|-----------|----------|--------|
| `mode5_targeted_20260609_1058/` | mode3_decoup + mode5_recal | All 6 (targeted high-spread traces) |
| `mode_sweep_targeted_20260609_1102/` | mode0_ref + mode0_flat3 + mode4_cal | All 6 (same targeted traces) |
| `{suite}_repl_pol_20260522_0722/lru_baseline/` | LRU baseline | All 6 |

### Targeted trace set (symlinks at `trace-files/targeted_20260609_1058/`)

| Suite | Traces |
|-------|--------|
| DPC3 | 605.mcf_s ×4, 607.cactuBSSN_s ×2, 619.lbm_s ×4 |
| GAP | bc-0, bc-12, cc-13, cc-14, cc-5 |
| GMS | k_clique_list_danisch×2 (soc-pokec-relationships) |
| Ligra | BFSCC, Components-Shortcut, PageRank, PageRankDelta (com-lj) |
| ML | bark.cpp, llama2.c ×2, stable-diffusion.cpp ×2, vit.cpp |
| QMM | srv_617, srv_669, srv_715, srv_73 |

### Suite-level geomeans vs LRU baseline

| Suite | mode3_decoup | **mode5_recal** | mode4_cal |
|-------|-------------|-----------------|-----------|
| DPC3 | +1.1% | **+1.9%** | -0.2% |
| GAP | +11.1% | +10.5% | +12.7% |
| GMS | -2.0% | **+0.3%** | -3.4% |
| Ligra | -0.4% | **+3.9%** | -1.6% |
| ML | -0.9% | **+0.2%** | -1.0% |
| QMM | +3.9% | +3.7% | +2.5% |
| **Overall geomean** | +2.0% | **+3.4%** | +1.5% |

**Winner: mode5_recal** — wins 4/6 suites, losses on GAP (−0.6pp) and QMM (−0.2pp) are marginal.

### Known regressions requiring investigation

- `vit.large.armadillo.1` (ML): all modes ~−12% vs LRU. Likely liveness misclassification of long-running MA blocks.
- `stable-diffusion.cpp-sd-v1-4.ckpt.1` (ML): mode3 −5.5%, mode5 −5.7% vs LRU.

**Next**: Full-suite sweep of mode5_recal across all ~184 LLC-pressured traces to get representative geomeans for the paper.

---

## Phase 5: History Table Replacement Policy (In Progress — 2026-06-09)

**Branch**: `hist-repl-policy`  
**Commit**: `575f4e708d68`  
**Binary**: `champsim_srrip_live_hrp` (on Castillo)  
**Activation**: `REPL_HIST_LLC_CAP=512,REPL_HIST_REPL=lfu_doa` (default is unbounded — policy changes are dead code without both vars)

### Changes vs old policy (`champsim_srrip_live` with `lfu_doa`)

| Aspect | Old | New |
|--------|-----|-----|
| DoA hit | freq +1 | freq +3 |
| MD hit | freq +0 | freq +1 |
| MA hit | freq +0 | freq −2 (floor 0) |
| Insert freq | 1 (always) | DoA→3, MD→1, MA→0 |
| Freq cap | none | 64 |
| Aging | none | penalty = idle_updates / cap_ |
| Clock | `clock_` (on_hit/on_insert only) | `update_count_` (every update call) |

### Lifespan tracking (new in `575f4e7`)

`srrip_live` now tracks `lifespan_sum[4]` and `lifespan_count[4]` per insertion class (DoA/MD/MA/unguided). Printed in `replacement_final_stats()` as average cycles from insertion to eviction. This data will be used to calibrate delta values proportionally to actual observed lifespans.

### Comparison run

| Directory | Contents |
|-----------|----------|
| `hist_repl_targeted_20260609_1233/` | old_repl vs new_repl, mode3_decoup, targeted traces |

Job IDs: 1405041–1405052. Config: `SCORING_MODE=3,THD_DEAD=2,THD_DOA=4,REPL_HIST_LLC_CAP=512,REPL_HIST_REPL=lfu_doa`.

---

## Next Steps (Post-Validation)

1. **Upon validation job completion** (expected 2026-06-01):
   - Verify geomean speedup matches baseline within 2%
   - If successful: release exp016/017 for final characterization
   - If divergent >5%: investigate whether 2-class simplification needs 3-class restoration

2. **Paper submission** (target 2026-06-05):
   - Update with validated results
   - Include hardware implementation feasibility analysis
   - Submit to HPCA 2026

3. **Future work**:
   - Adaptive thresholding (per-workload feedback)
   - ML-based liveness prediction
   - Energy efficiency analysis
   - Real hardware prototype

---

## Contact Information

**Primary Author**: Oskar Tegby  
**Email**: oskar.tegby@proton.me  
**Advisor**: Alberto Ros  

**Repository**: `/home/otegby/repos/code/reuse-pred`  
**Cluster**: Castillo (via abdet proxy)

---

**Last Updated**: 2026-05-31  
**Version**: 1.0  
**Scope**: Complete documentation of all Phase 1-2 results + Phase 3 validation setup
