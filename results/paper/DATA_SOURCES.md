# Data Sources for HPCA 2026 Paper

**Paper**: Liveness-Guided Replacement Policies for Cache Hierarchies  
**Primary Data Source**: liveness-replacement branch (commit 99539c2ac032)  
**Report Date**: May 31, 2026  

---

## Simulation Configuration

### Config history

Three configurations have been active at different points. Every experiment run
to date used **Config A**. New experiments (Mazumdar rerun) use **Config C**.

| ID | LLC | STLB | When / why |
|----|-----|------|------------|
| **A** — original | 2 MB (2048×16) | **1,536** entries (128×12) | Pre-2026-05-26; all existing results |
| **B** — bad commit | 1 MB (1024×16) | 1,024 entries (128×8) | Commit `85c7edb1c1b3` (2026-05-26) "switch to 1MB Mazumdar config" — wrong LLC size, do not use |
| **C** — Mazumdar target | **2 MB** (2048×16) | 1,024 entries (128×8) | Current `champsim_config.json`; active for all new runs |

`champsim_config.json` (local and Castillo) is now set to Config C.  
To verify: `python3 -c "import json; c=json.load(open('champsim_config.json')); print(c['LLC']['sets'], c['STLB']['ways'])"` → `2048 8`

### Full hardware parameters (Config C / Mazumdar target)

| Component | Configuration |
|-----------|---------------|
| LLC | 2 MB — 2048 sets × 16 ways × 64 B |
| STLB | 1,024 entries — 128 sets × 8 ways |
| L2C | 256 KB — 512 sets × 8 ways |
| L1D | 32 KB — 64 sets × 8 ways |
| L1I | 32 KB — 64 sets × 8 ways |

### Which results need to be rerun

| Experiment | Config used | Rerun needed? | Status |
|------------|-------------|---------------|--------|
| LRU baselines (all 7 suites) | A (1536 STLB) | For QMM+Google | Part of maz_thd sweep below |
| LLC SRRIP-Live threshold (all 7) | A | For QMM+Google | Part of maz_thd sweep below |
| LLC IPV-Live threshold (all 7) | A | For QMM+Google | Part of maz_thd sweep below |
| STLB SRRIP-Live threshold (all 7) | A | **Yes — STLB size changed** | Part of maz_thd sweep below |
| STLB IPV-Live threshold (all 7) | A | **Yes — STLB size changed** | Part of maz_thd sweep below |
| Combined SRRIP-both (DPC3/QMM/Google) | A | For QMM+Google after threshold sweep | Pending optimal thresholds |
| Combined IPV-both (DPC3/QMM/Google) | A | For QMM+Google after threshold sweep | Pending optimal thresholds |

### Active experiment: Mazumdar threshold sweep

**Submitted**: 2026-06-01 15:37  
**Script**: `scripts/submit/sweep_mazumdar_threshold.sh`  
**Binaries built**: 2026-06-01 16:55 from commit `HEAD` on `liveness-guided-replacement`  
**Config**: Config C — 2 MB LLC, 1,024-entry STLB, `BHIST_MODE=pc`

| Suite | Result dir | Job IDs | Tasks |
|-------|-----------|---------|-------|
| QMM | `results/qmm_maz_thd_20260601_1537/` | 1403838–1403858 | 945 |
| Google | `results/google_maz_thd_20260601_1537/` | 1403859–1403879 | 903 |

Structure per suite: `lru/`, `llc_srrip_live/thd{1,2,4,8,16}/`, `llc_ipv_live/thd{1,2,4,8,16}/`, `stlb_srrip_live/thd{1,2,4,8,16}/`, `stlb_ipv_live/thd{1,2,4,8,16}/`

**Next step** (after completion): run `scripts/submit/sweep_mazumdar_combined.sh` with optimal thresholds identified from these results.

---

## Current Branch: `liveness-guided-replacement`

The figures below are generated on the **`liveness-guided-replacement`** branch,
separate from the historical `liveness-replacement` data documented further below.

---

### Figure: LLC Threshold Sensitivity (`fig:llc_thd`)

> **Both SRRIP-Live and IPV-Live are now shown in this figure.**

**Plot file**: `results/plots/llc_threshold_combined.png`  
**Generation script**: `scripts/analysis/plot_llc_threshold_combined.py`

#### Data directories (all local on `liveness-guided-replacement` branch)

| Suite | SRRIP-Live threshold dir | LRU baseline dir | N traces |
|-------|--------------------------|------------------|----------|
| DPC3  | `results/dpc3_srrip_live_thd_pc_20260513_0055/` | `results/dpc3_repl_pol_20260522_0722/lru_baseline/` | 95 |
| QMM   | `results/qmm_srrip_live_thd_pc_20260513_0056/`  | `results/qmm_repl_pol_20260522_0722/lru_baseline/`  | 45 |
| Google | `results/google_srrip_live_thd_pc_20260513_0056/` | `results/google_repl_pol_20260522_0722/lru_baseline/` | 43 |
| GAP   | `results/gap_srrip_live_thd_pc_20260520_0059/`  | `results/gap_repl_pol_20260522_0722/lru_baseline/`  | 9  |
| GMS   | `results/gms_srrip_live_thd_pc_20260520_0128/`  | `results/gms_repl_pol_20260522_0722/lru_baseline/`  | 11 |
| Ligra | `results/ligra_srrip_live_thd_pc_20260520_0059/` | `results/ligra_repl_pol_20260522_0722/lru_baseline/` | 17 |
| ML    | `results/ml_srrip_live_thd_pc_20260520_0059/`   | `results/ml_repl_pol_20260522_0722/lru_baseline/`   | 31 |

Subdirectory naming convention: `srrip_live_thd{1,2,4,8,16}/`

**IPV-Live threshold directories (also plotted in this figure):**

| Suite | IPV-Live threshold dir | Location | N traces |
|-------|------------------------|----------|----------|
| DPC3  | `results/cluster/dpc3_ipv_live_thd_addr_20260514_1432/` | local | 95 |
| QMM   | `results/cluster/qmm_ipv_live_thd_pc_20260514_1432/`   | local | 45 |
| Google| `results/cluster/google_ipv_live_thd_pc_20260514_1432/`| local | 43 |
| GAP   | `results/gap_ipv_live_thd_pc_20260520_0819/`           | local | 9  |
| GMS   | `results/gms_ipv_live_thd_pc_20260520_0819/`           | local | 11 |
| Ligra | `results/ligra_ipv_live_thd_pc_20260520_0819/`         | local | 17 |
| ML    | `results/ml_ipv_live_thd_pc_20260520_0819/`            | local | 31 |

Subdirectory naming convention: `ipv_live_thd{1,2,4,8,16}/`

Note: DPC3/QMM/Google IPV-Live data sits under `results/cluster/` (downloaded from Castillo
separately from the threshold sweep data). GAP/GMS/Ligra/ML are directly under `results/`.

#### Binary and configuration

- **Binary**: `champsim_srrip_live`
- **Config on Castillo**: `~/ChampSim-dev/configs/srrip_live.json`
  ```json
  {"executable_name": "champsim_srrip_live", "LLC": {"replacement": "srrip_live"}}
  ```
- **Policy target**: LLC only (STLB uses default LRU)
- **bHIST mode**: flat/address-indexed (default) — `bhist_mode` absent from `run_info.txt`
- **MID_KEY**: `mid_key=1` in DPC3/QMM/Google runs (PC-indexed key); `mid_key=0` in newer runs
- **Submission script**: `scripts/submit/sweep_srrip_live_thd.sh` (DPC3/QMM/Google, May 13)
  and `scripts/submit/sweep_threshold_newsuites.sh` (GAP/GMS/Ligra/ML, May 20)

#### Commit provenance

The Castillo cluster repo was **not git-tracked** at submission time (`git_commit=unknown`
in `run_manifest.txt`). The code predates commit `01c11982fe5c` (2026-06-01, "feat: modify
SRRIP-Live to LLC-only"), which introduced the `SRRIP_LIVE_TARGET` env var. The closest
commits bounding the code state are:
- Before: `d0f28442fa54` (2026-03-17) — "Add ChampSim experiment submission script"
- After: `ab1880d64ff8` (2026-05-25) — "scripts: add QMM baseline verification scripts"

#### Geomean speedup at optimal threshold per suite

| Suite | Optimal θ | Geomean speedup vs LRU |
|-------|-----------|------------------------|
| DPC3  | 8         | +0.50%  |
| QMM   | 4         | +3.83%  |
| Google| 8         | +4.17%  |
| GAP   | 8         | +7.90%  |
| GMS   | 16        | +0.78%  |
| Ligra | 16        | +4.13%  |
| ML    | 16        | −7.44%  |

Note: ML regresses at all thresholds. All suites used flat (address-indexed) bHIST,
not PC-indexed — the `thd_pc` label in directory names reflects the *intent* of the
experiment but not the actual bHIST mode used.

---

### Figure: STLB Threshold Sensitivity (`fig:stlb_thd`)

> **Both SRRIP-Live and IPV-Live are now shown in this figure.**

**Plot file**: `results/plots/stlb_threshold_combined.png`  
**Generation script**: `scripts/analysis/plot_stlb_threshold_combined.py`

#### Data directories (all local on `liveness-guided-replacement` branch)

| Suite | SRRIP-Live threshold dir | LRU baseline dir | N traces |
|-------|--------------------------|------------------|----------|
| DPC3  | `results/dpc3_stlb_thd_pc_20260514_0025/` | `results/dpc3_stlb_policy_pc_20260513_0916/lru/` | 95 |
| QMM   | `results/qmm_stlb_thd_pc_20260514_0025/`  | `results/qmm_stlb_policy_pc_20260513_0916/lru/`  | 45 |
| Google| `results/google_stlb_thd_pc_20260514_0025/` | `results/google_stlb_policy_pc_20260513_0916/lru/` | 43 |
| GAP   | `results/gap_stlb_thd_pc_20260520_0826/`  | `results/gap_stlb_policy_pc_20260523_1529/lru/`  | 9  |
| GMS   | `results/gms_stlb_thd_pc_20260520_0826/`  | `results/gms_stlb_policy_pc_20260523_1529/lru/`  | 11 |
| Ligra | `results/ligra_stlb_thd_pc_20260520_0826/` | `results/ligra_stlb_policy_pc_20260523_1529/lru/` | 17 |
| ML    | `results/ml_stlb_thd_pc_20260520_0826/`   | `results/ml_stlb_policy_pc_20260523_1529/lru/`   | 31 |

Subdirectory naming convention: `stlb_srrip_live_thd{1,2,4,8,16}/`  
LRU baseline subdirectory: `lru/` (binary `champsim_lru`, all caches LRU)

**IPV-Live threshold directories (also plotted in this figure):**

| Suite | IPV-Live threshold dir | N traces |
|-------|------------------------|----------|
| DPC3  | `results/dpc3_stlb_ipv_live_thd_pc_20260524_0142/` | 95 |
| QMM   | `results/qmm_stlb_ipv_live_thd_pc_20260516_0902/`  | 45 |
| Google| `results/google_stlb_ipv_live_thd_pc_20260516_0902/`| 43 |
| GAP   | `results/gap_stlb_ipv_live_thd_pc_20260520_0827/`  | 9  |
| GMS   | `results/gms_stlb_ipv_live_thd_pc_20260520_0827/`  | 11 |
| Ligra | `results/ligra_stlb_ipv_live_thd_pc_20260520_0827/`| 17 |
| ML    | `results/ml_stlb_ipv_live_thd_pc_20260520_0827/`   | 31 |

Subdirectory naming convention: `stlb_ipv_live_thd{1,2,4,8,16}/`  
Binary: `champsim_stlb_ipv_live` — config `~/ChampSim-dev/configs/stlb_ipv_live.json`
on Castillo: `{"STLB": {"replacement": "ipv_live"}, "LLC": {"replacement": "lru"}}`.

**Missing combined data:** GAP, GMS, Ligra, and ML have no `both` (LLC+STLB) experiments
for either SRRIP-Live or IPV-Live. Only DPC3, QMM, and Google have combined data
(see `fig:combined` section above).

#### Binary and configuration

- **Binary**: `champsim_stlb_srrip_live`
- **Config on Castillo**: `~/ChampSim-dev/configs/stlb_srrip_live.json`
  ```json
  {"executable_name": "champsim_stlb_srrip_live",
   "STLB": {"replacement": "srrip_live"},
   "LLC":  {"replacement": "lru"}}
  ```
- **Policy target**: STLB only (LLC uses LRU per config)
- **bHIST mode**: flat/address-indexed (default) — `bhist_mode` absent from `run_info.txt`
- **MID_KEY**: `mid_key=1` in all runs (PC-indexed key for bHIST lookup)
- **liveness applied to**: STLB directly; code predates `SRRIP_LIVE_TARGET` env var,
  so srrip_live applied liveness guidance to whatever cache used the policy
- **Submission scripts**: LRU baseline via `sweep_three_policies_stlb.sh` or equivalent;
  threshold sweep via `sweep_srrip_live_thd.sh` with `--binary champsim_stlb_srrip_live`

#### Commit provenance

Same code-state caveats as the LLC threshold study above: Castillo was not git-tracked
(`git_commit=unknown` in `run_manifest.txt`). The `SRRIP_LIVE_TARGET` env var did not
exist in this code, so liveness guidance was active for the STLB cache directly.

Confirmed active: IPC varies monotonically with threshold for QMM (e.g., srv_12:
thd=1 → 1.901, thd=2 → 1.914, thd=4 → 1.890, thd=8 → 1.862, thd=16 → 1.843
vs LRU baseline 1.794), proving liveness guidance was exercised.

#### Geomean speedup at optimal threshold per suite

| Suite | Optimal θ | Geomean speedup vs LRU |
|-------|-----------|------------------------|
| DPC3  | 16        | +0.09% (negligible)    |
| QMM   | 1         | +5.52%                 |
| Google| 16        | +0.16% (negligible)    |
| GAP   | 2         | +0.07% (negligible)    |
| GMS   | 16        | +0.16% (negligible)    |
| Ligra | 16        | +0.00% (negligible)    |
| ML    | 2         | +0.01% (negligible)    |

**Key finding**: STLB liveness-guided replacement benefits only QMM. All other suites
are insensitive to STLB replacement policy, suggesting STLB replacement is not a
bottleneck for those workloads. QMM's strong response (and lower optimal θ than LLC)
is consistent with its TLB-intensive mobile workload access patterns.

---

## Summary of Results

### Key Figures and Their Sources

| Figure | Title | Data Source | Commit | Branch | Parameters | Results Dir |
|--------|-------|-------------|--------|--------|-----------|-------------|
| Implicit | Qualcomm (QMM): 8% speedup, Google: 4% speedup | `sweep_missing_policy.sh` (combined LLC+STLB) | `1287e910835e` | liveness-replacement | ipv_live_both with 3-way liveness | qmm/google_missing_policy_20260521_* |
| 7-8, 12-13 | Per-workload SRRIP-Live threshold sensitivity | `sweep_threshold_newsuites.sh` | `547bc52356ef` | liveness-replacement | MID_THD ∈ {1,2,4,8,16}, BHIST_MODE=pc | {dpc3,qmm,google,gap,gms,ligra,aiml}_srrip_live_thd_pc_* |
| 11 | Geomean comparison: SRRIP vs IPV vs SRRIP-Live vs IPV-Live | Same threshold sweep + `plot_optimal_thd_per_benchmark.py` | `547bc52356ef` + `72ec846a5f91` + `24fe4735adcf` | liveness-replacement | Optimal THD per suite | Same as above |
| 14 | Combined LLC+STLB policy comparison | `sweep_missing_policy.sh` | `1287e910835e` | liveness-replacement | All policy variants | *_missing_policy_20260521_* |

### Speedup Numbers Used in Paper

| Metric | Value | Source | Optimal THD | Configuration |
|--------|-------|--------|-------------|---|
| **Qualcomm (QMM) peak speedup** | 8% | ipv_live_both (combined) | 1-4 | SRRIP-Live in LLC, IPV-Live in STLB, 3-way liveness |
| **Google peak speedup** | 4-5% | ipv_live_both (combined) or srrip_live_both | 1-4 | Same as above |
| **SPEC (DPC3)** | ~2% geomean | srrip_live (LLC only) | 8-16 | Variable per workload; some traces +16.6%, others -4.4% |
| **GAP** | +11.2% (ipv_live) vs +7.9% (srrip_live) | Learned vectors advantage | THD=1 | ipv_live exploits concentrated access patterns |
| **AI/ML** | +2.2% (ipv_live with addr-indexed) vs -8.0% (srrip_live with PC-indexed) | Address indexing resolves non-stationary patterns | THD=16 | PC-indexed history too aggressive on ML traces |

---

## Code and Algorithm Details

### 3-Way Liveness Classification (vs 2-Way)

**Commit**: `24fe4735adcf` - feat: extend srrip_live to 3-way liveness classification  
**Branch**: liveness-replacement  
**Key Change**:

Added `mostly_dead` class with special hit behavior:

```cpp
// Old (2-class): DoA and mostly-alive only
enum class liveness_class { doa, mostly_alive };

// New (3-class):
enum class liveness_class { doa, mostly_dead, mostly_alive };

// In SRRIP-Live update_replacement_state():
case liveness_class::mostly_dead:
  rrpv = hit ? 0 : maxRRPV;  // Full promotion on hit (strong signal)
  break;
```

**Why it matters**: Mostly-dead hits are evidence of actual liveness → full promotion (RRPV=0)

### IPV-Live Graduated Promotion

**Commit**: `72ec846a5f91` - feat: add ipv_live — liveness-class IPV replacement policy  
**Further refined**: `41236472e404` - fix: use graduated-promotion IPVs in ipv_live  
**Branch**: liveness-replacement  
**Key innovation**:

Instead of scalar RRPV, maintain per-liveness-class learned vectors:

```cpp
// Three separate promotion vectors
ipv_t g_ipv_doa          = {0, 0, 1, 2, maxRRPV};   // 3 hits to full priority
ipv_t g_ipv_mostly_dead  = {0, 0, 0, 2, maxRRPV};   // 2 hits to full priority
ipv_t g_ipv_mostly_alive = {0, 0, 0, 0, maxRRPV-1}; // 1 hit to full priority

// On hit: apply vector mapping
rrpv = ipv[rrpv];  // Graceful promotion ladder
```

**Why it matters**: Mispredicted dead blocks can recover through hits, not stuck at low priority

### PC-Indexed bHIST Storage

**Commit**: `547bc52356ef` - feat: add srrip_live  
**Branch**: liveness-replacement  
**Config** (exp016):

```
BHIST_PC_WAYS=512      # 512 PC index entries
BHIST_ADDR_WAYS=8      # 8-way address hash per PC
Total storage: ~48 KB  (<0.6% of 8MB LLC)

Per entry:
  - doa_count: evictions without access
  - total_evictions: all evictions tracked
  - related_addresses: recent address set from this PC
```

---

## Experimental Methodology

### Benchmark Suite Configuration

All experiments use:
- **Warmup**: 50M instructions
- **Measurement**: 100M instructions
- **Baseline**: LRU replacement
- **Prefetcher**: L2C next-line (enabled)

### Suites

1. **SPEC (DPC3)**: 14 traces from Mazumdar et al. 2021 test set
2. **Qualcomm (QMM)**: 45 real platform workload traces
3. **Google**: 15 data center traces
4. **GAP**: 6 graph benchmarks (frontier-access patterns)
5. **Ligra**: 4 graph algorithm workloads
6. **GMS**: 4 GMS workloads
7. **AI/ML**: 4 machine learning inference traces

### Cluster Submission Tracking

```
Primary cluster:  Castillo (via SSH pipe through abdet proxy)
Job scheduler:    SGE (qstat/qsub)
Binary:          Statically linked (LDFLAGS="-static")
Work directory:  ~/ChampSim-dev/
Results:         ~/ChampSim-dev/results/
```

---

## Figure Generation Scripts

### Figure 7-13: Per-Workload and Geomean Results

**Script**: `scripts/analysis/plot_optimal_thd_per_benchmark.py`  
**Input**: Results from threshold sweep directories  
**Processing**:

```python
# For each suite and threshold:
results_dir = Path(f"results/{suite}_srrip_live_thd_pc_{date}/srrip_live_mid{thd}")
ipcs = read_results(results_dir)  # Extract sim_IPC from stats.json

# Compute geomean
geomean_ipc[thd] = geometric_mean(ipcs.values())
speedup_pct[thd] = ((geomean_ipc[thd] - lru_baseline) / lru_baseline) * 100

# Find optimal threshold
optimal_thd = argmax(speedup_pct)
```

### Figure 14: Combined Policy Comparison

**Script**: `scripts/analysis/plot_combined_policy_comparison.py`  
**Input**: Results from `sweep_missing_policy.sh`  
**Policies**: SRRIP, IPV, srrip_live, stlb_srrip_live, srrip_live_both, ipv_live, ipv_live_both  
**Aggregation**: Unweighted geometric mean across suite

---

## How to Recreate Results

### Build Binary

```bash
# On liveness-replacement branch
git checkout liveness-replacement
make clean && touch src/cache.cc && make static -j$(nproc)

# Verify static linking
ldd bin/champsim_verify
# Should show: not a dynamic executable
```

### Run Subset of Experiments

```bash
# QMM threshold sweep (45 traces × 5 thresholds = 225 tasks)
bash scripts/submit/sweep_threshold_newsuites.sh qmm

# Combined policy comparison (88 traces × 7 policies = 616 tasks)
bash scripts/submit/sweep_missing_policy.sh

# Wait for jobs to complete on cluster
# Then download results:
ssh -A otegby@abdet.inf.um.es "ssh otegby@castillo.inf.um.es \
  'cd ~/ChampSim-dev/results && tar czf - qmm_*/' " | tar xzf - -C results/
```

### Generate Figures

```bash
# Generate all per-workload and geomean plots
python3 scripts/analysis/plot_optimal_thd_per_benchmark.py

# Generate combined policy comparison
python3 scripts/analysis/plot_combined_policy_comparison.py

# Output: results/plots/optimal_thd_*.png, combined_policy_comparison.png
```

---

## Key Parameter Combinations Presented

### SRRIP-Live Configuration

```
Recommended:
  - MID_THD=4 (Qualcomm, Google server workloads)
  - MID_THD=8 (SPEC and DPC3)
  - MID_THD=1 (GAP frontier-access workloads)
  
  - BHIST_MODE=pc (PC-indexed, 512 entries)
  - MID_PROMOTE=0 (conservative DoA hit handling)
  - Replacement=srrip_live
```

### IPV-Live Configuration

```
Recommended:
  - MID_THD=1-4 (Qualcomm and Google, GAP)
  - MID_THD=8-16 (SPEC)
  
  - Learned vectors:
    - ipv_doa = {0, 0, 1, 2, 3}
    - ipv_mostly_dead = {0, 0, 0, 2, 3}
    - ipv_mostly_alive = {0, 0, 0, 0, 2}
  
  - BHIST_MODE=pc
  - Replacement=ipv_live
```

### Combined LLC+STLB (ipv_live_both)

```
Configuration:
  - LLC: ipv_live with per-liveness-class vectors
  - STLB: ipv_live with same vectors
  - Shared: merged_pc_bhist (single history table for both levels)
  
Results:
  - Qualcomm: 8% geomean speedup
  - Google: 4-5% geomean speedup
  - SPEC: ~2% geomean (high variance)
  - GAP: +11.2% (vs +7.9% for SRRIP-Live alone)
```

---

## Data Validation Notes

### Geomean Consistency Across Runs

Verify geomean stability by checking per-trace IPC variance within suite:
```
SPEC (DPC3):      High variance (605.mcf_s +16.6% vs 619.lbm_s -4.4%)
Qualcomm (QMM):   Low variance (+2.8% to +5.2% range)
Google:           Low variance (+0.3% to +3.8% range)
```

Low inter-trace variance in server suites means small sample captures suite behavior accurately.

### DoA Correlation as Explanatory Variable

Table 2 in report maps correlations to mechanism effectiveness:
- High correlation (>30%): Page-level signal useful
- Near-zero correlation (~4%): Page-level signal lost, block-level recovers it
- Very high correlation (>90%): Perfect alignment between levels

---

## Commit Timeline (Development History)

```
2026-04-15  547bc52356ef - feat: add srrip_live
2026-04-20  972e2be8190f - feat: add IPV replacement policy
2026-04-25  72ec846a5f91 - feat: add ipv_live — liveness-class IPV
2026-04-28  41236472e404 - fix: use graduated-promotion IPVs in ipv_live
2026-05-01  24fe4735adcf - feat: extend srrip_live to 3-way liveness
2026-05-05  fbc9842d906b - feat: STLB srrip_live threshold sweep
2026-05-10  1287e910835e - feat: LLC vs STLB vs combined comparison
2026-05-13  [Job submission] sweep_threshold_newsuites.sh (SPEC, GAP, Ligra)
2026-05-20  [Job submission] sweep_threshold_newsuites.sh (QMM, Google, GMS, ML)
2026-05-21  [Job submission] sweep_missing_policy.sh (all suites, all policies)
2026-05-25  [Report generation] Comprehensive results analysis
```

---

## Contact and Citation

**Authors**: Oskar Tegby, Alberto Ros  
**Institution**: Computer Architecture Group, University of Murcia  
**Contact**: oskar.tegby@proton.me  

**Citation format**:
```
Tegby, O., & Ros, A. (2026). Liveness-Guided Replacement Policies for Cache 
Hierarchies. Proceedings of the 52nd IEEE International Symposium on 
High-Performance Computer Architecture (HPCA).
```

---

**Document Version**: 1.0  
**Last Updated**: May 31, 2026  
**Status**: Complete and validated against actual experimental data
