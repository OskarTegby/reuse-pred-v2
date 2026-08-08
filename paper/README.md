# HPCA 2026 Paper: Liveness-Guided Replacement Policies

This directory contains the paper submission for HPCA 2026 on liveness-guided cache replacement policies (SRRIP-Live and IPV-Live).

## Structure

- **main.tex** — Main paper source
  - Introduction and motivation for liveness-guided replacement
  - Detailed pseudocode for SRRIP-Live, IPV-Live, and bHIST operations
  - Experimental methodology and results
  - Related work and discussion

- **Makefile** — Build automation
  - `make pdf` — Compile PDF from LaTeX source
  - `make watch` — Watch for file changes and recompile automatically
  - `make clean` — Remove build artifacts
  - `make open` — Compile and open PDF

- **build/** — Build directory (generated)
  - Intermediate compilation files
  
- **main.pdf** — Compiled paper (generated)

## Key Contributions

1. **SRRIP-Live**: SRRIP replacement policy guided by per-PC dead-on-arrival statistics
   - Dead-on-arrival (DoA) blocks inserted with maxRRPV (immediate eviction candidates)
   - Mostly-alive blocks inserted with standard SRRIP strategy (maxRRPV - 1)
   - Threshold parameter θ controls classification boundary

2. **IPV-Live**: Insertion Policy Version extended with liveness guidance
   - Similar liveness classification to SRRIP-Live
   - Adds load type awareness (prefetch vs demand)
   - Applicable to both LLC and STLB

3. **PC-Indexed History Table (bHIST)**: Lightweight tracking of per-PC liveness
   - Stores dead-on-arrival count and total eviction count per PC
   - Set-associative lookup with LRU/LFU replacement for overflow
   - <0.6% storage overhead vs LLC size

## Building the Paper

### Prerequisites
```bash
# Ubuntu/Debian
sudo apt-get install texlive-latex-base texlive-fonts-recommended texlive-latex-extra

# macOS (with Homebrew)
brew install basictex
tlmgr install booktabs multirow algorithm
```

### Compilation
```bash
# Single compilation
pdflatex -interaction=nonstopmode -output-directory=build main.tex

# Full build with Makefile
make pdf

# Watch for changes and auto-recompile
make watch

# Clean build artifacts
make clean
```

## Figures and Results

The paper references plots from completed experiments:

- **srrip_live_thd.png** — LLC SRRIP-Live threshold sensitivity (exp010)
  - Shows geomean IPC across QMM, Google, DPC3 for θ ∈ {1,2,4,8,16}
  
- **stlb_ipv_live_thd.png** — STLB IPV-Live threshold sensitivity
  - Page-level liveness guidance results
  
- **qmm_per_workload_srrip_live.png** — Per-trace breakdown on Qualcomm
  - Shows which applications benefit most from liveness guidance

### Linking Plots
Update `main.tex` references to point to actual plot locations once available:
```
\includegraphics[width=0.48\textwidth]{../plots/srrip_live_thd.png}
```

## Experimental Details

### Benchmark Suites
- **Qualcomm (QMM)**: 45 traces, real platform workloads (8% peak speedup)
- **Google**: 15 traces, data center workloads (6% peak speedup)
- **DPC3**: 14 traces, prefetch championship (2-3% speedup)

### Simulation Configuration
- 50M warmup + 100M simulation cycles per trace
- ChampSim simulator with configurable replacement policies
- LLC: 8 MB, 16-way; STLB: 512 entries
- Metric: IPC relative to LRU baseline

### Threshold Selection
- exp016: Fixed 512×8 bHIST budget
- exp017: Unbounded characterization for analysis
- Optimal thresholds: θ=4 (QMM/Google), θ=8 (DPC3)

## Validation Status

Current validation pipeline (as of 2026-05-31):

- **Job IDs**: 1403591-1403594 (on Castillo cluster)
- **Status**: Queued, awaiting resource availability
- **Expected runtime**: ~1-2 hours (180 total tasks: 90 validation + 90 baseline)
- **Comparison**: liveness-guided-replacement vs liveness-replacement baseline
- **Next step**: Download results and run validate_replacement_integration.sh

Once validation completes, results will be incorporated into the paper's
performance tables and figures.

## Citation Format

For referencing specific results:
- SRRIP-Live (LLC, THD=4): "8% geomean speedup on Qualcomm"
- IPV-Live (STLB, THD=4): "2-3% geomean speedup on server workloads"
- Combined (LLC + STLB): "11% on Qualcomm, 9% on Google"

## Authorship

- Oskar Tegby (primary author)
- Alberto Ros (advisor)

## Submission Information

- **Conference**: HPCA 2026
- **Template**: Two-column HPCA format
- **Page limit**: Typical HPCA limit (10 pages in conference style)
- **Deadline**: TBD

## Notes for Future Revisions

### Data Still Being Collected
- Validation jobs running on cluster (jobs 1403591-1403594)
- exp016 and exp017 submissions pending validation success
- Per-workload breakdowns will be updated with final results

### Sections That May Expand
- **Results**: Will include full validation comparison table
- **Related Work**: May need additional citations from concurrent MICRO/ISCA papers
- **Appendix**: Can include per-trace tables if space allows

### Review Comments to Address (placeholder)
- [ ] Hardware implementation feasibility
- [ ] Comparison with adaptive/ML-based approaches
- [ ] Energy overhead of history table lookups
- [ ] Scalability to larger history tables

---

**Last Updated**: 2026-05-31  
**Status**: In preparation — awaiting final validation results
