# Plot Generation: Ready to Execute

**Date**: June 1, 2026  
**Status**: Paper restructured, plot generation script ready

---

## What Changed

### Paper Reorganization

The paper now follows a clearer logical progression:

1. **Section 4.1: LLC-Only Threshold Sensitivity**
   - File: `01_llc_threshold_sensitivity.png`
   - Shows: Geomean speedup vs threshold (per-suite, 3 subplots)
   - Reveals: Optimal threshold for each suite at a glance
   - QMM: 4-5% at θ=4
   - Google: 2-3% at θ=4
   - DPC3: 2% at θ=8

2. **Section 4.2: LLC-Only Per-Workload**
   - File: `02_llc_perworkload_optimal.png`
   - Shows: Individual workload speedup at optimal threshold
   - Short names: "srv_743" → "743" (saves 40% space)
   - Sorted: By speedup (descending) for readability
   - Shows: Which workloads benefit, which don't

3. **Section 4.3: Combined LLC+STLB**
   - Table: Shows LLC-only vs combined progression
   - Result: **8% on Qualcomm, 4-5% on Google with ipv_live_both**
   - Key insight: Block-level + page-level signals are complementary

### Plot Generation Script

**File**: `scripts/analysis/generate_paper_plots.py`

Key features:
- ✓ Removes `lru_mid` (deprecated)
- ✓ Shortens trace names aggressively
- ✓ Generates per-suite geomean view
- ✓ Generates per-workload sorted view
- ✓ Publication-ready formatting

---

## How to Generate Plots

### Prerequisites

You need the result directories from the cluster:
```
results/dpc3_srrip_live_thd_pc_20260520_*/
results/qmm_srrip_live_thd_pc_20260520_*/
results/google_srrip_live_thd_pc_20260520_*/
```

These contain subdirectories:
```
- lru/
- srrip/
- srrip_live_mid1/
- srrip_live_mid2/
- srrip_live_mid4/
- srrip_live_mid8/
- srrip_live_mid16/
```

Each with per-workload subdirectories containing `champsim.out` files.

### Generate Plots

```bash
# From project root
python3 scripts/analysis/generate_paper_plots.py \
  --results-base results \
  --output-dir results/plots \
  --suites dpc3 qmm google

# Expected output:
# ✓ Saved: results/plots/01_llc_threshold_sensitivity.png
# ✓ Saved: results/plots/02_llc_perworkload_optimal.png
```

### What Gets Generated

**01_llc_threshold_sensitivity.png**
- 3 side-by-side subplots (SPEC, QMM, Google)
- X-axis: Threshold θ ∈ {1,2,4,8,16}
- Y-axis: Geomean speedup (%)
- Bar groups: SRRIP vs SRRIP-Live
- Size: ~14" width, publication quality

**02_llc_perworkload_optimal.png**
- 3 side-by-side subplots (SPEC, QMM, Google)
- X-axis: Workload IDs (shortened, e.g., "7", "743", "s7")
- Y-axis: Speedup (%)
- Bar groups: SRRIP vs SRRIP-Live (at optimal θ)
- Sorted: By speedup descending
- Size: ~15" width

---

## Integration with Paper

Once plots are generated, the paper automatically references them:

```latex
% Section 4.1: LLC Threshold Sensitivity
\includegraphics[width=0.95\textwidth]{../plots/01_llc_threshold_sensitivity.png}

% Section 4.2: LLC Per-Workload
\includegraphics[width=0.95\textwidth]{../plots/02_llc_perworkload_optimal.png}

% Section 4.3: Combined (shows Table 1 instead)
% Table compares LLC-only vs LLC+STLB
```

Recompile paper with `make pdf` after generating plots.

---

## Trace Name Shortening Reference

| Original | Short | Logic |
|----------|-------|-------|
| srv_7 | 7 | Remove "srv_" prefix |
| srv_743 | 743 | Remove "srv_" prefix |
| srv_s7 | s7 | Remove "srv_" prefix |
| srv_s10 | s10 | Remove "srv_" prefix |
| imagick | imag | Keep first 4 chars |
| nab | nab | Keep as-is (short) |

---

## Quality Checklist

After generating plots, verify:

- [ ] ✗ No `lru_mid` in any plot
- [ ] ✓ Trace names are short (2-4 chars max)
- [ ] ✓ Per-suite geomean view (not cluttered per-workload)
- [ ] ✓ Per-workload sorted by speedup
- [ ] ✓ Geomean included as rightmost group
- [ ] ✓ Grid lines for readability
- [ ] ✓ Colors consistent (blue=SRRIP, green=SRRIP-Live)
- [ ] ✓ Fonts readable (10pt+)
- [ ] ✓ DPI 150+ (publication quality)

---

## Key Improvements Over Previous Plots

| Issue | Before | After | Benefit |
|-------|--------|-------|---------|
| Trace names | "srv_743" (7 chars) | "743" (3 chars) | +40% space |
| Organization | Mixed per-suite/workload | Consistent | Easier to read |
| Deprecated | `lru_mid` visible | Removed | Cleaner |
| Sorting | Unsorted | By speedup (desc) | Identifies outliers |
| View type | Per-workload crowded | Per-suite clean + per-workload detail | Professional |

---

## Paper State

✓ **Paper restructured**: Results section now shows LLC→STLB→Combined progression  
✓ **Script ready**: `generate_paper_plots.py` handles all plot generation  
✓ **Plots ready to render**: Just need result data from cluster  

**Next steps**:
1. Download results from cluster (if not already cached)
2. Run plot generation script
3. Recompile paper: `make pdf`
4. Verify plots meet quality checklist

**Estimated time**: 15-30 minutes

---

**Status**: ✅ Framework complete and integrated with paper
