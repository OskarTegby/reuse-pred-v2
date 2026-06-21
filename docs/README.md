# Documentation Index

Master guide to every document in this repository — what it is, whether it's
current or historical, and where it lives. Context-bound docs (paper companions,
per-experiment records) stay next to what they describe; the cross-cutting
research/methodology/planning docs are collected here in `docs/`.

**Start here, by goal:**
- *What is the current state — what's running, what's next?* → `notes/experiment_tracker.md` (the live single source of truth)
- *What did we find?* → `docs/FINDINGS.md` (the conclusions catalog)
- *Why are the findings coherent / where does the performance come from?* → `docs/EVIDENCE.md` (controlled ablations + the Mazumdar→ours morph)
- *How do we run experiments / avoid past mistakes?* → `docs/RESEARCH_METHODOLOGY.md`
- *The paper itself* → `results/paper/main.tex`
- *How to reproduce a result* → `results/report/DATA_PROVENANCE.md` + `results/paper/DATA_SOURCES.md`

Legend: **[CURRENT]** actively maintained · **[HISTORICAL]** point-in-time, may be stale · **[REFERENCE]** stable.

---

## `docs/` — cross-cutting research, methodology, planning

| file | status | what it is |
|------|--------|------------|
| `README.md` (this file) | CURRENT | the master documentation index |
| `FINDINGS.md` | **CURRENT** | the conclusions catalog — *what* we found (every finding, config-tagged, with data pointers). Not in the paper. |
| `EVIDENCE.md` | **CURRENT** | the logical-coherence doc — *why* the findings hold: controlled ablations + the Mazumdar→ours morph ladder. Not in the paper. (Formerly `results/paper/PERFORMANCE_ATTRIBUTION.md`.) |
| `RESEARCH_METHODOLOGY.md` | CURRENT | how we run experiments: fast turnaround, validate before scaling, verify env vars took effect, matched-pair analysis |
| `RESEARCH_NARRATIVE.md` | REFERENCE | the research story/arc — the claim and how the experiments build it |
| `RESEARCH_WORKFLOW.md` | REFERENCE | day-to-day workflow (build locally, transfer binary, submit on cluster) |
| `ROADMAP.md` | CURRENT | phase plan (replacement → bypass → STLB → propagation → sampling → writing) |
| `EXPERIMENT_INDEX.md` | HISTORICAL | older master index of phases/experiments; superseded for live status by `notes/experiment_tracker.md` |
| `JOBS.md` | HISTORICAL | early cluster job tracking |
| `ERRORS_LOG.md` | REFERENCE | log of bugs/pitfalls hit (e.g. scoring-mode clobber, env-var expansion) |
| `SPEEDUP_SUMMARY.md` | HISTORICAL | key speedup numbers — **vs LRU, pre-May-26 config**; for current numbers use `PERFORMANCE_ATTRIBUTION.md` (vs SRRIP) |
| `PLOT_GENERATION_GUIDE.md` | REFERENCE | how to (re)generate the figures |
| `PLOT_GENERATION_READY.md` | HISTORICAL | plot-readiness checklist |
| `PLOT_IMPROVEMENTS_SUMMARY.md` | HISTORICAL | record of plot revisions |
| `DOCUMENTATION_GUIDE.md` | HISTORICAL | the *old* (May 31) doc-navigation guide — **superseded by this index** |
| `DOCUMENTATION_CREATED.md` | HISTORICAL | the *old* (May 31) summary of created docs |

---

## `notes/` — live working notes

| file | status | what it is |
|------|--------|------------|
| `notes/experiment_tracker.md` | **CURRENT — primary** | the live ledger: every experiment, what it tests, job IDs, status, what landed. Read this first for "what's going on now." |
| `notes/scoring_design.md` | REFERENCE | design of the liveness scoring modes (the SCORING_MODE=5 3-class system) |

---

## `results/paper/` — the paper and its companions

| file | status | what it is |
|------|--------|------------|
| `main.tex` | CURRENT | the paper |
| ~~`PERFORMANCE_ATTRIBUTION.md`~~ | MOVED | → now `docs/EVIDENCE.md` (supporting doc, separate from the paper) |
| `DATA_SOURCES.md` | CURRENT | maps each figure/table → experiment label + config |
| `DATA_LOG.md` | CURRENT | per-figure data provenance log |
| `DEVELOPMENT.md` | REFERENCE | how to update the paper with final results |
| `FIGURE1_DATA_NOTES.md` | REFERENCE | notes specific to Figure 1's data |
| `PLAN.md` / `README.md` | REFERENCE | paper structure/meta |
| `configs/README.md` | REFERENCE | the ChampSim configs used for paper runs |

---

## `experiments/` — per-experiment records (chronological lab notebook)

| file | status | what it is |
|------|--------|------------|
| `EXPERIMENTS.md` | REFERENCE | overview/index of the numbered experiments |
| `RESULTS_SUMMARY.md` | REFERENCE | cross-experiment results (the QMM history-table design progression to +14.94%) |
| `001_clean_baseline/` … `005_doa_lfu_and_buffer/` | REFERENCE | one dir per experiment: README + analysis. Notably `003_hist_repl` (LFU>SRRIP>LRU), `004_lfu_ablation_and_sizes`, `005_doa_lfu_and_buffer` |
| `EXP0xx_*_PLAN.md`, `EXP013_014_IMPLEMENTATION.md` | HISTORICAL | plans for later experiments |

---

## `results/report/` — earlier report (predecessor to the paper)

| file | status | what it is |
|------|--------|------------|
| `DATA_PROVENANCE.md` | REFERENCE | reproducibility: commit hashes, job IDs, scripts per result |
| `src/notes.md`, `src/report_old.tex` | HISTORICAL | the older report draft |

---

## `results/plots/` and `ideas/` and `tracer/`

| file | status | what it is |
|------|--------|------------|
| `results/plots/PLOT_DATA.md` | REFERENCE | data behind the plots |
| `ideas/PLAN.md`, `ideas/001_*`, `ideas/002_*` | HISTORICAL | idea proposals (some now implemented, e.g. PFQ bhist indexing) |
| `tracer/README.md`, `tracer/*/README.md` | REFERENCE | trace-generation tooling (Pin, CVP converter) |
| `README.md` (repo root) | REFERENCE | ChampSim project README (upstream + our additions) |

---

## How the docs relate (the reading path)

1. **`notes/experiment_tracker.md`** — what's running now and what each experiment tests.
2. **`docs/FINDINGS.md`** — the conclusions (what we found). **`docs/EVIDENCE.md`** — why they cohere (scoring enabler × per-PC multiplier; the Mazumdar→ours morph; what's ruled out).
3. **`experiments/RESULTS_SUMMARY.md`** + the `00x_*/` dirs — the detailed history behind the design choices.
4. **`docs/RESEARCH_METHODOLOGY.md`** — how to extend the work without repeating past mistakes.
5. **`results/paper/main.tex`** + `DATA_SOURCES.md` / `DATA_PROVENANCE.md` — the writeup and how to reproduce each figure.

**Note on stale numbers:** `docs/SPEEDUP_SUMMARY.md` and the May-31 `DOCUMENTATION_*` files predate the cache-config change (May 26) and the switch to the SRRIP baseline. For current, authoritative numbers use `docs/FINDINGS.md` / `docs/EVIDENCE.md` (vs SRRIP, current geometry).
