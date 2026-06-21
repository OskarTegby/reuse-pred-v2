# Plot Generation Guide for Paper

This guide explains how to regenerate publication-quality plots for the HPCA 2026 paper with the improvements requested:
- Remove `lru_mid` (deprecated)
- Better space usage (short trace names)
- Consistent organization: per-suite for threshold scaling, per-workload for optimal results

---

## Plot Strategy for Paper

### Figure 1: Threshold Sensitivity (Per-Suite Geomean)

**Purpose**: Show how geomean IPC changes across different DoA thresholds for each suite

**Format**: 3 side-by-side plots (one per suite: SPEC, Qualcomm, Google)
- X-axis: Threshold θ ∈ {1, 2, 4, 8, 16}
- Y-axis: Geomean speedup (%) relative to LRU
- Bars: SRRIP vs SRRIP-Live side-by-side

**Data Source**:
```
results/{dpc3,qmm,google}_srrip_live_thd_pc_20260520_*/
  └─ srrip_live_mid{1,2,4,8,16}/
  └─ srrip/
  └─ lru/
```

**Key Points**:
- Removes per-workload clutter
- Shows optimal threshold at a glance (peak on graph)
- Consistent scale across suites for comparison

### Figure 2: Per-Workload Optimal Results

**Purpose**: Identify which workloads benefit most from liveness guidance

**Format**: 3 subplots (one per suite), each with:
- X-axis: Workload IDs (shortened: "srv_7" → "7", "srv_743" → "743")
- Y-axis: Speedup (%) at optimal threshold
- Bars: SRRIP (reference) vs SRRIP-Live vs IPV-Live

**Data Source**:
```
results/{dpc3,qmm,google}_*_20260520_*/
  └─ srrip/
  └─ srrip_live_mid{4 or 8}/  (optimal threshold per suite)
  └─ ipv_live_mid{4 or 8}/
  └─ lru/
```

**Key Points**:
- Per-workload precision
- Sorted by SRRIP-Live speedup (descending) for easy reading
- Shortened trace names save horizontal space
- Geomean as rightmost column

### Figure 3: Combined Policy Comparison (LLC vs LLC+STLB)

**Purpose**: Show additive benefit of applying liveness guidance to both cache levels

**Format**: Single plot showing:
- X-axis: Workload ID
- Y-axis: Speedup (%)
- Bar groups: srrip_live_both, ipv_live_both (one per policy combination)

**Data Source**:
```
results/*_missing_policy_20260521_*/
  └─ srrip_live_both/
  └─ ipv_live_both/
  └─ lru/
```

---

## Implementation Steps

### Step 1: Extract Result Data

```bash
# From cluster, download the three main result sets:
ssh -A otegby@abdet.inf.um.es "ssh otegby@castillo.inf.um.es \
  'cd ~/ChampSim-dev/results && \
   tar czf - {dpc3,qmm,google}_srrip_live_thd_pc_*/ | \
   head -c 500G'" | tar xzf - -C results/

# Download combined policy results:
ssh -A otegby@abdet.inf.um.es "ssh otegby@castillo.inf.um.es \
  'cd ~/ChampSim-dev/results && \
   tar czf - *_missing_policy_20260521_*/' " | tar xzf - -C results/
```

### Step 2: Generate Threshold Sensitivity Plots

These show geomean across thresholds (per-suite):

```python
#!/usr/bin/env python3
"""Generate Figure 1: Threshold sensitivity per suite."""

from pathlib import Path
from statistics import geometric_mean
import matplotlib.pyplot as plt
import numpy as np

suites = ["dpc3", "qmm", "google"]
suite_dirs = [
    Path("results/dpc3_srrip_live_thd_pc_20260520_*").glob("*")[0],
    Path("results/qmm_srrip_live_thd_pc_20260520_*").glob("*")[0],
    Path("results/google_srrip_live_thd_pc_20260520_*").glob("*")[0],
]

thresholds = [1, 2, 4, 8, 16]

fig, axes = plt.subplots(1, 3, figsize=(14, 4))

for ax, suite_dir, suite_name in zip(axes, suite_dirs, suites):
    srrip_geomeans = []
    srrip_live_geomeans = []
    
    # Load LRU baseline
    lru_ipcs = {}
    for trace_dir in (suite_dir / "lru").glob("srv_*"):
        # Parse IPC from champsim.out
        lru_ipcs[trace_dir.name] = extract_ipc(trace_dir / "champsim.out")
    
    for thd in thresholds:
        # Load SRRIP
        srrip_ipcs = {}
        for trace_dir in (suite_dir / "srrip").glob("srv_*"):
            srrip_ipcs[trace_dir.name] = extract_ipc(trace_dir / "champsim.out")
        
        # Load SRRIP-Live
        live_ipcs = {}
        for trace_dir in (suite_dir / f"srrip_live_mid{thd}").glob("srv_*"):
            live_ipcs[trace_dir.name] = extract_ipc(trace_dir / "champsim.out")
        
        # Compute geomean speedup
        srrip_speedup = geometric_mean([srrip_ipcs[k] / lru_ipcs[k]
                                       for k in srrip_ipcs if k in lru_ipcs])
        srrip_live_speedup = geometric_mean([live_ipcs[k] / lru_ipcs[k]
                                            for k in live_ipcs if k in lru_ipcs])
        
        srrip_geomeans.append((srrip_speedup - 1) * 100)
        srrip_live_geomeans.append((srrip_live_speedup - 1) * 100)
    
    x = np.arange(len(thresholds))
    width = 0.35
    
    ax.bar(x - width/2, srrip_geomeans, width, label="SRRIP", color="#1f77b4")
    ax.bar(x + width/2, srrip_live_geomeans, width, label="SRRIP-Live", color="#2ca02c")
    
    ax.set_title(suite_name.upper(), fontweight="bold")
    ax.set_xlabel("DoA Threshold (θ)")
    ax.set_ylabel("Speedup (%)")
    ax.set_xticks(x)
    ax.set_xticklabels(thresholds)
    ax.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
    ax.legend()
    ax.grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig("results/plots/figure1_threshold_sensitivity.png", dpi=150, bbox_inches='tight')
```

### Step 3: Generate Per-Workload Optimal Results

These show individual workload speedups at optimal threshold (per-suite):

```python
#!/usr/bin/env python3
"""Generate Figure 2: Per-workload results at optimal thresholds."""

# Optimal thresholds from literature/prior runs:
OPTIMAL_THRESHOLDS = {
    "dpc3": 8,
    "qmm": 4,
    "google": 4,
}

# For each suite:
#   1. Find srrip_live_mid{THD} directory
#   2. Extract per-workload speedup vs lru
#   3. Sort by speedup (descending)
#   4. Plot with shortened trace names: "srv_743" → "743"

def shorten_trace_id(name):
    """Convert 'srv_743' to '743'."""
    if name.startswith("srv_"):
        return name[4:]
    return name

# Plot per-workload bars, sorted by SRRIP-Live speedup
# X-axis: shortened trace IDs
# Y-axis: speedup (%)
# Bars: SRRIP, SRRIP-Live, IPV-Live

# Include geomean as rightmost bar group
```

### Step 4: Generate Combined Policy Plots

Show LLC vs LLC+STLB (ipv_live_both) advantage:

```python
# Load from results/*_missing_policy_20260521_*/
# Policies: srrip_live_both, ipv_live_both
# Compare: LLC-only performance vs combined

# Plot shows how STLB guidance adds value when combined with IPV-Live
```

---

## Trace Name Shortening Reference

| Original | Short | Original | Short |
|----------|-------|----------|-------|
| srv_s7 | s7 | srv_743 | 743 |
| srv_526 | 526 | srv_s10 | s10 |
| arizona.0 | az0 | tahoe.2 | tah2 |
| charlie.1 | ch1 | charlie.2 | ch2 |

**Rule**: Remove "srv_" prefix; keep next 2-4 characters

---

## Plot Quality Checklist

- [ ] No `lru_mid` in any plot (removed deprecated policy)
- [ ] Trace names shortened to 2-4 characters
- [ ] Consistent use of colors:
  - Blue: SRRIP (baseline)
  - Green: SRRIP-Live
  - Orange: IPV
  - Red: IPV-Live
  - Purple: Combined
- [ ] Per-suite for threshold scaling (geomean view)
- [ ] Per-workload for optimal results (detailed view)
- [ ] Grid lines for readability
- [ ] Fonts large enough (10pt minimum for labels)
- [ ] Legend included where needed
- [ ] Title clearly states what is shown
- [ ] DPI: 150 (publication quality)

---

## Integration with Paper

Once plots are generated:

1. **Figure 1**: Rename to `srrip_live_thd_per_suite.png`
2. **Figure 2**: Rename to `srrip_live_optimal_per_workload.png`
3. **Figure 3**: Rename to `ipv_live_both_combined.png`

Update paper references:
```latex
\includegraphics[width=0.95\textwidth]{../plots/srrip_live_thd_per_suite.png}
```

---

## Data Validation

Before submitting plots, verify:

```bash
# Check that all workloads present
find results/qmm_srrip_live_thd_pc_*/srrip_live_mid4 -type d | wc -l  # Should be 45

# Verify geomeans match prior analysis
python3 << 'EOF'
from pathlib import Path
from statistics import geometric_mean

lru = {d.name: extract_ipc(d / "champsim.out") 
       for d in Path("results/qmm_srrip_live_thd_pc_*/lru").glob("*")}
sl4 = {d.name: extract_ipc(d / "champsim.out") 
       for d in Path("results/qmm_srrip_live_thd_pc_*/srrip_live_mid4").glob("*")}

speedup = geometric_mean([sl4[k] / lru[k] for k in sl4 if k in lru])
print(f"QMM SRRIP-Live THD=4: {(speedup-1)*100:.1f}% (expected 4-5%)")
EOF
```

---

## Notes

- All plots should be 150 DPI minimum for publication
- Use consistent figure width: 0.95 textwidth for single, 0.48 for side-by-side
- Shortened trace names save ~40% horizontal space vs full names
- Per-suite geomean view emphasizes algorithm effectiveness; per-workload details identify edge cases
