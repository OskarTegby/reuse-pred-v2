# Documentation Guide: How to Navigate the Data and Research

This guide explains the documentation system created to track experimental data, provenance, and results for the liveness-guided replacement policy research.

---

## Quick Start: Which Document to Read?

### If you want to...

**...understand the 8% and 4% speedup numbers**
→ Read: `SPEEDUP_SUMMARY.md` (this file explains what config produced those numbers)

**...reproduce the experiments**
→ Read: `results/report/DATA_PROVENANCE.md` (contains commit hashes, job IDs, scripts)

**...understand the paper's data sources**
→ Read: `results/paper/DATA_SOURCES.md` (maps figures to experiments and configurations)

**...see the complete research roadmap**
→ Read: `EXPERIMENT_INDEX.md` (master index of all phases and work)

**...develop the paper further**
→ Read: `results/paper/DEVELOPMENT.md` (how to update with final results)

**...see available simulation results on disk**
→ Read: `results/report/DATA_PROVENANCE.md` section "Cluster Job Submissions"

---

## Documentation Structure

```
reuse-pred/
├── DOCUMENTATION_GUIDE.md          ← You are here
├── EXPERIMENT_INDEX.md              ← Master roadmap, all experiments
├── SPEEDUP_SUMMARY.md               ← Key numbers explained (8%, 4%, etc)
│
├── results/
│   ├── report/
│   │   ├── DATA_PROVENANCE.md       ← Detailed figure-to-data mapping
│   │   ├── build/report.pdf         ← Comprehensive technical report
│   │   └── src/notes.md             ← Figure design decisions
│   │
│   ├── paper/
│   │   ├── main.tex                 ← HPCA 2026 paper
│   │   ├── main.pdf                 ← Compiled paper
│   │   ├── DATA_SOURCES.md          ← Paper-specific data sources
│   │   ├── DEVELOPMENT.md           ← How to update paper with final results
│   │   ├── references.bib           ← Bibliography
│   │   └── Makefile                 ← Build automation
│   │
│   └── plots/                       ← Generated figures
│       ├── srrip_live_thd.png
│       ├── optimal_thd_all7_pc.png
│       └── ...
│
└── .claude/projects/*/memory/       ← Persistent memory (used by Claude Code)
    ├── paper_structure.md           ← Paper framework notes
    ├── project_status.md            ← Current branch and work status
    └── ...
```

---

## The Four Core Documentation Files

### 1. SPEEDUP_SUMMARY.md (This Repository Root)

**Purpose**: Quick reference for the key performance numbers  
**Audience**: Anyone asking "what speedup did you get?" or "why 8% for Qualcomm?"  
**Key sections**:
- Best case results (8% QMM, 4-5% Google)
- Alternative configurations and comparison
- Why 3-way liveness matters
- LLC-STLB correlation as explanatory variable
- Recommended deployment configuration

**When to use**:
- First document to read if you just want the headline numbers
- Go here before diving into DATA_PROVENANCE.md
- Explains the "why" behind the numbers

---

### 2. DATA_SOURCES.md (results/paper/)

**Purpose**: Map figures/numbers in HPCA paper to experimental configurations  
**Audience**: Paper authors, reviewers, anyone reproducing HPCA results  
**Key sections**:
- Table: Figure → Data Source → Commit → Parameters
- Code details (algorithms for SRRIP-Live, IPV-Live)
- Experimental methodology (50M warmup, 100M sim, etc.)
- Benchmark suite breakdown
- How to recreate results (build, run, generate figures)

**When to use**:
- You're working on the HPCA 2026 paper
- You need to cite where a specific result came from
- You want to regenerate a figure

---

### 3. DATA_PROVENANCE.md (results/report/)

**Purpose**: Complete provenance documentation for all experimental data  
**Audience**: Reproducibility focus, detailed technical documentation  
**Key sections**:
- Figure-by-figure mapping to data, scripts, commits, parameters
- Complete simulation setup (cache config, memory config, etc.)
- Threshold sweep parameters and classification rules
- Script reference (submission, analysis, plotting)
- Cluster job submissions with dates and job IDs
- Git commit hash reference with descriptions
- Reproducibility checklist

**When to use**:
- You need to reproduce exact results from 2026-05-13 or 2026-05-20 runs
- You're writing detailed methods section
- You need commit hashes for specific features
- You want to know the exact cluster job IDs that produced results

---

### 4. EXPERIMENT_INDEX.md (This Repository Root)

**Purpose**: Master roadmap and taxonomy of all research phases  
**Audience**: Project managers, researchers understanding full scope  
**Key sections**:
- Data organization by branch
- Experiment taxonomy (Phase 1 characterization → Phase 2 replacement → Phase 3 validation)
- Quick results table
- Parameter reference
- Next steps and roadmap
- Known limitations and caveats

**When to use**:
- You're new to the project and need an overview
- You need to understand which phase is which
- You want to see what experiments were done and their status
- You need context on validation job status

---

## How They Work Together

### Scenario 1: "What's the 8% speedup from?"

1. Start: `SPEEDUP_SUMMARY.md` → "Best Case Results" section
2. Learn: ipv_live_both on Qualcomm with 3-way liveness
3. Want details? → `DATA_SOURCES.md` → "Speedup Numbers" table
4. Want to reproduce? → `DATA_PROVENANCE.md` → "Combined LLC+STLB Replacement" figure
5. Want context? → `EXPERIMENT_INDEX.md` → "Phase 2: Replacement Policy Development" table

### Scenario 2: "How do I regenerate Figure 11 for the paper?"

1. Start: `DEVELOPMENT.md` (results/paper/) → "Updating Results Tables"
2. Learn: Which scripts generate the figure
3. Find: `DATA_SOURCES.md` → "Figure Generation Scripts" section
4. Exact details: `DATA_PROVENANCE.md` → "Figures 7-8, 12-13" section
5. Execute: Follow "How to Recreate Results" in `DATA_SOURCES.md`

### Scenario 3: "I need to write a reproducibility statement for a journal"

1. Core info: `DATA_PROVENANCE.md` → "Reproducibility Checklist"
2. Benchmark details: `DATA_SOURCES.md` → "Experimental Methodology"
3. Results directory: `DATA_PROVENANCE.md` → "Cluster Job Submissions"
4. Code availability: `DATA_PROVENANCE.md` → "Appendix: Git Commit Hash Reference"

---

## Information Flow Diagram

```
SPEEDUP_SUMMARY.md
     ↓
  "I want context"
     ↓
EXPERIMENT_INDEX.md
     ↓
  "I need to reproduce"
     ↓
DATA_SOURCES.md (for paper) OR
DATA_PROVENANCE.md (for full details)
     ↓
  "I have all the info I need"
     ↓
scripts/analysis/*.py (generate figures)
scripts/submit/*.sh (run experiments)
```

---

## Key Concepts Explained Across Documents

### The "8% on Qualcomm" Number

| Aspect | Explained in | Details |
|--------|-------------|---------|
| What it is | SPEEDUP_SUMMARY.md | ipv_live_both (combined LLC+STLB) |
| Why it works | SPEEDUP_SUMMARY.md | 3-way liveness + learned vectors |
| How it was measured | DATA_SOURCES.md | Commit hashes, benchmark suite, parameters |
| Exact reproduction | DATA_PROVENANCE.md | Job IDs, scripts, result directories |
| Research context | EXPERIMENT_INDEX.md | Part of Phase 2, combined policy testing |

### 3-Way Liveness Classification

| Aspect | Explained in | Details |
|--------|-------------|---------|
| Overview | SPEEDUP_SUMMARY.md | DoA vs mostly-dead vs mostly-alive |
| Algorithm | DATA_SOURCES.md | Code snippet of behavior |
| Why it matters | SPEEDUP_SUMMARY.md | Mostly-dead hits get full promotion |
| Implementation | DATA_PROVENANCE.md | Commit 24fe4735adcf |
| Validation plan | EXPERIMENT_INDEX.md | Phase 3 jobs 1403591-1403594 |

---

## Keeping Documentation Updated

### When you complete validation jobs:

1. Update `EXPERIMENT_INDEX.md` section "Phase 3: Integration and Validation"
   - Change status from "⏳ Queued" to "✓ Complete"
   - Add actual geomean numbers

2. Update `SPEEDUP_SUMMARY.md` if numbers differ
   - Update "Best Case Results" section
   - Add footnote about validation confirmation

3. Document in memory system (`.claude/projects/*/memory/`)
   - Create memory file with validated speedup numbers
   - Link to experiment IDs and result directories

### When you run new experiments:

1. Add entry to `EXPERIMENT_INDEX.md` taxonomy table
2. Create new section in `DATA_PROVENANCE.md` if major new experiment
3. Update `SPEEDUP_SUMMARY.md` if results change the headline numbers

### When you update the paper:

1. Update `DATA_SOURCES.md` with new figures/tables
2. Update `DEVELOPMENT.md` "Data Still Being Collected" section as needed
3. Keep `main.tex` and `main.pdf` in sync

---

## Cross-References

### Git Commits

Key commits appear in:
- `DATA_PROVENANCE.md` - Appendix, detailed with commit messages
- `DATA_SOURCES.md` - In tables, linked to specific features
- `SPEEDUP_SUMMARY.md` - Listed under "Source:" for key results

### Benchmark Suites

Defined consistently in:
- `DATA_PROVENANCE.md` - "Experimental Setup" section
- `DATA_SOURCES.md` - "Experimental Methodology"
- `EXPERIMENT_INDEX.md` - "Results Summary" table

### Cluster Locations

Found in:
- `DATA_PROVENANCE.md` - "Cluster Job Submissions" section
- `SPEEDUP_SUMMARY.md` - "Data Validation Notes"
- `DEVELOPMENT.md` - "Building and Viewing PDF" section

---

## FAQ

**Q: Where can I find the actual experimental results on disk?**  
A: `results/report/DATA_PROVENANCE.md` → "Cluster Job Submissions" section lists exact directory paths

**Q: How do I know which commit has the 8% speedup?**  
A: `SPEEDUP_SUMMARY.md` → "Best Case Results" → "Source" line lists commits. Detailed mapping in `DATA_SOURCES.md`

**Q: Can I regenerate the paper figures?**  
A: Yes! `DEVELOPMENT.md` section "Updating Figures" explains how. Scripts listed in `DATA_SOURCES.md`

**Q: What if I want to cite this research?**  
A: Cite the liveness-replacement branch commits (listed in `DATA_PROVENANCE.md` appendix) and paper location (`results/paper/main.pdf`)

**Q: Are all results validated?**  
A: Phase 1-2 complete and published. Phase 3 validation in progress (check `EXPERIMENT_INDEX.md` for current status)

---

## Maintenance Schedule

### Monthly:
- [ ] Review `EXPERIMENT_INDEX.md` for status changes
- [ ] Update validation job status in Phase 3 section

### Before submission:
- [ ] Verify all figures mapped in `DATA_SOURCES.md`
- [ ] Cross-check commit hashes in `DATA_PROVENANCE.md`
- [ ] Ensure reproducibility checklist complete

### Before publication:
- [ ] Lock down all commit hashes
- [ ] Finalize cluster result directories (archive old ones)
- [ ] Confirm all plots match paper

---

## Document Versions

| Document | Version | Last Updated | Status |
|----------|---------|--------------|--------|
| SPEEDUP_SUMMARY.md | 1.0 | 2026-05-31 | Complete |
| DATA_SOURCES.md | 1.0 | 2026-05-31 | Complete |
| DATA_PROVENANCE.md | 1.0 | 2026-05-31 | Complete |
| EXPERIMENT_INDEX.md | 1.0 | 2026-05-31 | Complete, Phase 3 pending |
| DEVELOPMENT.md | 1.0 | 2026-05-31 | Complete |

---

**Last Updated**: May 31, 2026  
**By**: Oskar Tegby, Alberto Ros  
**Project**: Cache Liveness Prediction: Replacement Policies and Bypass  
**Status**: Documentation system complete for Phases 1-2, Phase 3 validation in progress
