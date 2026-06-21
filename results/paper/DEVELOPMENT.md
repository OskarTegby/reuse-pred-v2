# Paper Development Guide

## Current Status

✅ **Complete**: 
- Main structure with introduction, methodology, pseudocode, results sections
- Five detailed algorithms (SRRIP-Live insert/hit, IPV-Live insert, bHIST update, classification)
- Bibliography framework with key references
- Experimental methodology and configuration details
- Compiled to PDF (5 pages, 242 KB)

⏳ **Awaiting Data**:
- Validation job results (jobs 1403591-1403594 on cluster)
- exp016 (512×8 bHIST) results
- exp017 (unbounded characterization) results

## How to Update the Paper

### 1. After Validation Jobs Complete

Once validation completes:

```bash
# Download results from cluster
bash scripts/download_validation.sh qmm_validate_srrip_live_20260531_1948
bash scripts/download_validation.sh qmm_baseline_srrip_live_20260531_2126

# Analyze and compare
bash scripts/analysis/validate_replacement_integration.sh \
  qmm_validate_srrip_live_20260531_1948 \
  qmm_baseline_srrip_live_20260531_2126

# Update the Results section with geomean numbers
```

### 2. Updating Figures

The paper references three main plots (referenced but not yet embedded):

**In main.tex, update these sections:**

```latex
% Line ~467: Update figure reference
\begin{figure}[t!]
\centering
\includegraphics[width=0.48\textwidth]{../plots/srrip_live_thd.png}
\caption{...}
\label{fig:srrip_thd}
\end{figure}
```

**Required plots** (publication-quality with improvements):

See `PLOT_GENERATION_GUIDE.md` in project root for detailed instructions.

**Key improvements needed**:
1. ✓ Remove `lru_mid` (deprecated policy)
2. ✓ Better space usage: shorten trace names ("srv_743" → "743")
3. ✓ Consistent organization:
   - Per-suite geomean for threshold sensitivity
   - Per-workload bars for optimal threshold results

**Plots to generate**:
1. `srrip_live_thd_per_suite.png` — Per-suite geomean vs threshold (3 subplots)
2. `srrip_live_optimal_per_workload.png` — Per-workload speedup at optimal THD (3 subplots)
3. `ipv_live_both_combined.png` — Combined policy comparison

**Generation process**:
1. Download results from cluster (instructions in PLOT_GENERATION_GUIDE.md)
2. Run: `python3 scripts/analysis/plot_paper_figures.py --result-dir results/qmm_*`
3. Or use existing symlinks: `ln -sf optimal_thd_all7_pc.png srrip_live_thd.png`
plt.legend()
plt.grid(True)
plt.savefig("results/plots/srrip_live_thd.png")
EOF
```

### 3. Updating Results Tables

Table~\ref{tab:combined} shows combined policy results. Update with actual values:

```latex
\begin{table}[t!]
\centering
\small
\caption{Combined Policy Performance (geomean speedup vs LRU baseline)}
\label{tab:combined}
\begin{tabular}{lrrr}
\toprule
\textbf{Policy} & \textbf{QMM} & \textbf{Google} & \textbf{DPC3} \\
\midrule
LRU (baseline) & 0.0\% & 0.0\% & 0.0\% \\
SRRIP & +2.1\% & +1.8\% & +3.2\% \\
SRRIP-Live (THD=4) & +8.0\% & +6.2\% & +2.8\% \\
...
\bottomrule
\end{tabular}
\end{table}
```

Replace percentages with actual validation results.

### 4. Adding Per-Workload Analysis

The paper mentions per-workload breakdown. To generate this:

```bash
python3 << 'EOF'
import json
from pathlib import Path
import matplotlib.pyplot as plt

# Read results from qmm_validate_srrip_live_20260531_1948/srrip_live_mid4/
results_dir = Path("results/qmm_validate_srrip_live_20260531_1948/srrip_live_mid4")

traces = {}
for trace_dir in sorted(results_dir.glob("srv_*")):
    stats_file = trace_dir / "stats.json"
    if stats_file.exists():
        with open(stats_file) as f:
            data = json.load(f)
            ipc = data.get("sim_IPC", 0)
            traces[trace_dir.name] = ipc

# Create bar chart
plt.figure(figsize=(12, 4))
plt.bar(range(len(traces)), list(traces.values()))
plt.xticks(range(len(traces)), list(traces.keys()), rotation=45, ha='right')
plt.ylabel("IPC")
plt.title("SRRIP-Live (THD=4) Per-Workload Results")
plt.tight_layout()
plt.savefig("results/plots/qmm_per_workload_srrip_live.png", dpi=150)
EOF
```

### 5. Expanding Sections for Camera-Ready

#### Results Section Expansion

Current structure:
- 4.1: LLC SRRIP-Live threshold sensitivity
- 4.2: STLB IPV-Live threshold sensitivity
- 4.3: Combined LLC+STLB policies
- 4.4: Per-workload breakdown
- 4.5: History table overhead

**To expand:**

- Add subsection 4.6: "Energy Efficiency Analysis"
  - Power/energy overhead of bHIST lookups
  - Energy-delay product (EDP) across configurations

- Add subsection 4.7: "Sensitivity to Configuration"
  - bHIST size variation (exp016: 512×8)
  - bHIST replacement policy (LRU vs LFU)
  - Threshold per-workload variations

- Add subsection 4.8: "Hardware Implementation Feasibility"
  - Timing analysis for lookup latency
  - Area estimates for actual silicon
  - Comparison to other overhead structures (BTB, branch history)

#### Discussion Section Expansion

Current section covers:
- Key findings
- Open questions
- Recommended next steps

**To expand:**

- Performance isolation: How does liveness guidance interact with prefetching?
- Applicability: Which workload characteristics benefit most?
- Scalability: How does this approach scale to larger caches?
- Comparison with ML-based approaches

### 6. Building and Viewing PDF

```bash
# Build paper
make pdf

# View in system default viewer
make open

# Auto-rebuild on file changes
make watch

# Clean build artifacts
make clean
```

## Key Metrics to Report

### Performance Numbers

- **QMM optimal**: 8% geomean speedup at THD=4
- **Google optimal**: 6% geomean speedup at THD=4
- **DPC3 optimal**: 2-3% geomean speedup at THD=8

### Configuration Details

- **Cache hierarchy**:
  - LLC: 8 MB, 16-way
  - STLB: 512 entries
  - DRAM: 3600 MHz, 2 channels

- **bHIST configuration (exp016)**:
  - 512 PC index entries
  - 8-way address hash
  - Total: ~48 KB overhead

- **Benchmark characterization**:
  - 45 QMM traces (server workloads)
  - 15 Google traces (data center)
  - 14 DPC3 traces (generic)

## Timeline for Final Submission

1. **2026-06-01**: Validation jobs complete
   - Download and analyze results
   - Update performance tables

2. **2026-06-02**: Create final figures
   - Generate plots from data
   - Update paper references

3. **2026-06-05**: Submit to HPCA 2026
   - Camera-ready version
   - All experimental data included

## Troubleshooting LaTeX Issues

### Float placement errors

If "Float(s) lost" error occurs:
```bash
# Increase float budget in main.tex
\setcounter{totalnumber}{8}
\renewcommand{\floatpagefraction}{0.85}
```

### Bibliography errors

If citations are undefined:
```bash
cd build
bibtex main
pdflatex main.tex
```

### Image not found

Ensure plots are in `results/plots/` with exact filenames:
- `results/plots/srrip_live_thd.png`
- `results/plots/stlb_ipv_live_thd.png`
- `results/plots/qmm_per_workload_srrip_live.png`

## Style Guidelines

- **Formatting**: Two-column HPCA format (10pt font)
- **Color scheme**: Black & white (LaTeX generated)
- **Math notation**:
  - Cache blocks: $b$
  - Program counters: $p$, $pc$
  - Thresholds: $\theta$
  - Re-Reference value: $\text{RRPV}$

## Contact Information

For questions about the paper or experiments:
- Author: Oskar Tegby (oskar.tegby@proton.me)
- Advisor: Alberto Ros

---

**Last Updated**: 2026-05-31  
**Current PDF**: main.pdf (5 pages)  
**Next Action**: Monitor validation jobs and download results
