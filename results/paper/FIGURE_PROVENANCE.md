# Figure Provenance

Per-figure and per-table regeneration recipes for the current HPCA 2026 paper
(`results/paper/main.tex`, branch `maz-morph-unbounded`), each pinned to an exact
commit, binary, config, and the cluster commands used to produce the data. This is the
canonical reference for data status and regeneration — the paper itself carries no
inline [DATA] notes.

This supersedes, for the figures it covers, the older `results/report/DATA_PROVENANCE.md`
and `results/paper/DATA_SOURCES.md` — both predate the current paper structure and
reference branches (`liveness-replacement`, `liveness-guided-replacement`) that no
longer exist.

---

## Figure 1 — `fig:liveness` (`results/plots/liveness_per_policy.png`)

> **Updated 2026-06-19.** The paper's Figure 1 was changed from the LRU-only two-panel
> `liveness_rates.png` (LLC + STLB breakdown under LRU) to the per-policy grouped bar
> chart `liveness_per_policy.png` (LRU / SRRIP / IPV across 7 suites, LLC only). The
> old plot and its full regeneration recipe are preserved in the
> [Figure 1 — superseded LRU-only version](#figure-1--superseded-lru-only-version)
> section below. Table 1 (`tab:concentration`) draws from the same LRU runs and is
> covered there.

### What it shows

Per-block (LLC) ground-truth liveness breakdown (DoA / mostly-dead / mostly-alive)
under three baseline replacement policies — LRU, SRRIP, IPV — grouped by benchmark
suite (7 suites). Backs the "Motivation" section text: DoA dominates (51–98%),
SRRIP raises DoA relative to LRU, IPV lowers DoA but inflates mostly-dead.

### Regeneration (replot only — no cluster access needed)

Raw eviction counts are hardcoded in the `RAW` dict at the top of the script.
To regenerate the PNG from the embedded data:
```bash
python3 scripts/analysis/plot_liveness_per_policy.py
```
Output: `results/plots/liveness_per_policy.png`.

Colors: DoA = `#4C6A8A` (slate blue), mostly-dead = `#6A9E8A` (muted teal),
mostly-alive = `#C9A84C` (warm gold).

### Data sources

LRU counts come from the same runs as the superseded Figure 1 / Table 1 (see below):

| Suite | Cluster directory |
|---|---|
| DPC3 | `results/livchar_dpc3full_20260616_1251/dpc3` |
| GAP, GMS, Ligra, ML, QMM | `results/livchar_unified_20260616_1249/{suite}` |
| Google | `results/liveness_char_20260608_0006/google` |

SRRIP and IPV counts come from:

| Policy | Cluster directory |
|---|---|
| SRRIP | `results/liveness_char_policies_20260617_2220/champsim_srrip/{suite}` |
| IPV | `results/liveness_char_policies_20260617_2220/champsim_ipv/{suite}` |

Counts were extracted on the cluster via `/tmp/extract_liveness.py` (dual-format
parser: per-PC `LIVENESS_CHAR BEGIN/END` blocks for SRRIP; aggregated
`LLC LIVENESS EVICTIONS:` summary line for IPV, which was built from an older
binary that does not emit per-PC blocks).

### To regenerate counts from scratch

Re-run the LRU jobs per the [Figure 1 — superseded](#figure-1--superseded-lru-only-version)
recipe below, then additionally submit SRRIP and IPV liveness-char jobs
(`LIVENESS_CHAR=1`) using `champsim_srrip` and `champsim_ipv` binaries against
all 7 suites, run `extract_liveness.py` on the cluster, and update the `RAW`
dict in `plot_liveness_per_policy.py`.

---

## Figure 1 — superseded LRU-only version (`results/plots/liveness_rates.png`)

Classification (ground truth, by hit count at eviction):
- **DoA**: zero hits during residency.
- **Mostly-dead**: ≥1 hit, but the last hit fell in the first half of the block's
  residency (`time_til_end > lifetime/2`).
- **Mostly-alive**: ≥1 hit, last hit in the second half of residency.

### Suites and canonical data directories

All paths are on the cluster (`castillo`, under `~/ChampSim-dev/`):

| Suite | Directory | Traces | Status |
|---|---|---|---|
| GAP | `results/livchar_unified_20260616_1249/gap` | 9 | complete, verified |
| GMS | `results/livchar_unified_20260616_1249/gms` | 9 | complete, verified |
| Ligra | `results/livchar_unified_20260616_1249/ligra` | 17 | complete, verified |
| ML | `results/livchar_unified_20260616_1249/ml` | 31 | complete, verified |
| QMM | `results/livchar_unified_20260616_1249/qmm` | 45 | complete, verified |
| DPC3 | `results/livchar_dpc3full_20260616_1251/dpc3` | 95 (74 contribute LLC evictions) | complete, verified |
| Google | `results/liveness_char_20260608_0006/google` | 43 | complete, **not independently re-verified** under the current commit (see Known gaps) |

"Verified" = cross-checked bit-for-bit against `results/liveness_char_20260608_0006`,
the original run that produced the numbers currently in the paper (see Verification
table below).

### Binary and commit

- Binary: `champsim_lru_v1` (a frozen copy of `champsim_lru`, deployed under a
  distinct filename so a later in-place rebuild of `champsim_lru` on the cluster
  can't invalidate a batch that's still running against this copy).
- **No commit in this repository corresponds to the code that produced this
  data.** The build (`2026-06-16 14:58:22`) was from a dirty tree: last clean
  ancestor `a6c1c07f3c9d` (`feat: cbPred PC-only bhist mode`) plus an uncommitted
  diff that was never captured on its own (no patch file, no stash). Citing
  "`a6c1c07f3c9d`, dirty" as the provenance is meaningless as a reproduction
  recipe — dirty means the commit, by itself, does not describe what ran.
- That uncommitted diff was eventually committed as **`20e78aa0a5a6`**
  (`feat: run-config provenance dump + LRU-Live hit-promotion modes (WIP source
  snapshot)`, current HEAD of `maz-morph-unbounded`) — but **2h12m after the
  build**, and its own message flags it as a bundled "WIP source snapshot"
  covering two unrelated features. There is no basis to assume it's an exact
  capture of the build-time dirty state rather than a superset that also
  includes work done in those two hours. So `20e78aa` cannot be cited as "the"
  commit either — see Known gaps for what this means and the fix.
- Build: local (`make static -j4`), never on the cluster (Castillo's Python is
  too old for the build system).

### Embedded `run_config.txt` (verbatim, representative)

One run's provenance dump is sufficient: every trace in every suite above used
the same binary, same env, same warmup/sim instruction counts (only `trace=`
and the SGE task ID differ). Captured from
`results/livchar_unified_20260616_1249/gap/cc-13/run_config.txt`:

```
# ChampSim run configuration and build provenance
git_sha=a6c1c07f3c9d
git_dirty=dirty
build_time=Jun 16 2026 14:58:22
run_time=2026-06-16T16:45:00
hostname=ng14
cmdline=./bin/champsim_lru_v1 --warmup_instructions 50000000 --simulation_instructions 100000000 /home/users/otegby/ChampSim-dev/trace-files/gap/cc-13.trace.gz
num_cpus=1
page_size=4096
block_size=64
warmup_instructions=50000000
simulation_instructions=100000000
dram_channels=1 dram_width_bits=64 dram_io_freq_MTps=3200
# caches/TLBs: NAME sets ways line_bytes mshr fill_latency
cache cpu0_L1I sets=64 ways=8 line=64 mshr=8 fill_latency=1
cache cpu0_ITLB sets=16 ways=4 line=4096 mshr=8 fill_latency=1
cache cpu0_DTLB sets=16 ways=4 line=4096 mshr=8 fill_latency=1
cache cpu0_STLB sets=128 ways=8 line=4096 mshr=16 fill_latency=1
cache cpu0_L1D sets=64 ways=8 line=64 mshr=16 fill_latency=1
cache cpu0_L2C sets=512 ways=8 line=64 mshr=32 fill_latency=1
cache LLC sets=2048 ways=16 line=64 mshr=64 fill_latency=1
# traces
trace=/home/users/otegby/ChampSim-dev/trace-files/gap/cc-13.trace.gz
# environment knobs (value or <unset>)
env SCORING_MODE=<unset>
env THD_DOA=<unset>
env THD_DEAD=<unset>
env LLC_THD_DOA=<unset>
env LLC_THD_DEAD=<unset>
env STLB_THD_DOA=<unset>
env STLB_THD_DEAD=<unset>
env MID_THD=1
env LOW_THD=1
env BHIST_MODE=flat
env SRRIP_LIVE_TARGET=
env LRU_LIVE_HIT_INIT=0
env LIVENESS_BYPASS=<unset>
env BYPASS_THD=<unset>
env STLB_LIVENESS_BYPASS=<unset>
env STLB_BYPASS_THD=<unset>
env CBPRED=0
env DPPRED=0
env CBPRED_IDX=addr
env DPPRED_IDX=vpn_pc
env CBPRED_KEY=<unset>
env MAZ_UNBOUNDED=<unset>
env BHIST_HASH=1
env PHIST_HASH=1
env BHIST_WAYS=4096
env BHIST_PC_WAYS=256
env REPL_HIST_LLC_CAP=<unset>
env REPL_HIST_STLB_CAP=<unset>
env REPL_HIST_BUF_CAP=0
env REPL_HIST_REPL=lfu_doa
env PFQ_CAP=8
env LIVENESS_CHAR=1
env ST_SIZE=2
env JOB_ID=1406030
env SGE_TASK_ID=2
```

The only knob that actually matters for this figure is `LIVENESS_CHAR=1` (enables
the per-PC dump used by Table 1; the DoA/MD/MA eviction counts behind Figure 1 are
printed unconditionally by `src/plain_printer.cc:89-99` whenever `stats.evictions > 0`,
so they exist even on plain runs). `champsim_lru_v1` runs unguided LRU — none of
`SCORING_MODE`/`BHIST_MODE`/`CBPRED`/etc. affect replacement decisions for this binary;
their values above are wrapper-script defaults, not active levers.

### Verification: current commit vs. the 2026-06-08 paper-source run

Cross-checked against `results/liveness_char_20260608_0006` (the run cited by the
paper's current `tab:concentration` datastatus note). `n90` = number of PCs needed
to cover 90% of LLC DoA evictions, computed per trace then min/mean/max'd across the
suite; breakdown = pooled eviction counts (sum across all traces in the suite, then
fraction), matching `scripts/analysis/plot_liveness_rates.py`'s `collect()`.

| Suite | n90 (min/mean/max) | LLC DoA / MD / MA % | Match vs. 2026-06-08 |
|---|---|---|---|
| GAP | 2 / 3.4 / 7 | 74.09 / 14.30 / 11.61 | **exact** (total evictions identical) |
| GMS | 1 / 4.3 / 8 | 87.11 / 8.93 / 3.97 | **exact** |
| Ligra | 2 / 5.6 / 14 | 93.23 / 4.02 / 2.75 | **exact** |
| ML | 1 / 4.6 / 10 | 98.00 / 1.79 / 0.21 | **exact** |
| QMM | 3,090 / 4,354 / 10,504 | 68.05 / 18.91 / 13.05 | **exact** |
| DPC3 (95-trace) | 1 / 96.7 / 4,833 | 87.82 / 10.33 / 1.85 | **exact** |
| Google | (not recomputed) | (not recomputed) | not re-run; same file as paper |

GAP/GMS/Ligra/ML/QMM/DPC3 reproduce the 2026-06-08 source run **bit-for-bit**
(identical total eviction counts, not just matching percentages). This also
resolved an open question from earlier in this investigation: a suspected
discrepancy in the ML liveness numbers, hypothesized to come from the writeback-hit
liveness gate (commit `f082f78`), turned out not to exist — current code reproduces
ML exactly, and a controlled revert of that gate (branch `liveness-pregate`) makes
the match *worse* (ML n90 5.2/38, QMM 2,909/4,118/10,571), consistent with the gate
predating the 2026-06-08 run.

### Exact regeneration recipe

**1. Build** (local only — never on Castillo):
```bash
git checkout maz-morph-unbounded   # or the specific commit you're reproducing
make static -j4
scp bin/champsim_lru castillo:~/ChampSim-dev/bin/champsim_lru_v1
```

**2. Submit characterization jobs** (cluster, via `scripts/submit/run_cs.sh`):
```bash
cd ~/ChampSim-dev
W=50000000; S=100000000

qsub -t 1-9  -N rc_gap   -o logs/ -e logs/ -l h_rt=24:00:00 -l mem_free=2G -wd ~/ChampSim-dev \
  -v "WARMUP=$W,SIM=$S,TRACE_DIR=trace-files/gap,TRACE_EXT=trace.gz,RUN_LABEL=livchar_unified_YYYYMMDD_HHMM/gap,BINARY=champsim_lru_v1,LIVENESS_CHAR=1" \
  scripts/submit/run_cs.sh

qsub -t 1-11 -N rc_gms   -v "WARMUP=$W,SIM=$S,TRACE_DIR=trace-files/gms,TRACE_EXT=champsimtrace.gz,RUN_LABEL=livchar_unified_YYYYMMDD_HHMM/gms,BINARY=champsim_lru_v1,LIVENESS_CHAR=1" \
  -o logs/ -e logs/ -l h_rt=24:00:00 -l mem_free=2G -wd ~/ChampSim-dev scripts/submit/run_cs.sh

qsub -t 1-17 -N rc_ligra -v "WARMUP=$W,SIM=$S,TRACE_DIR=trace-files/ligra,TRACE_EXT=champsimtrace.xz,RUN_LABEL=livchar_unified_YYYYMMDD_HHMM/ligra,BINARY=champsim_lru_v1,LIVENESS_CHAR=1" \
  -o logs/ -e logs/ -l h_rt=24:00:00 -l mem_free=2G -wd ~/ChampSim-dev scripts/submit/run_cs.sh

qsub -t 1-31 -N rc_ml    -v "WARMUP=$W,SIM=$S,TRACE_DIR=trace-files/ml,TRACE_EXT=champsimtrace.gz,RUN_LABEL=livchar_unified_YYYYMMDD_HHMM/ml,BINARY=champsim_lru_v1,LIVENESS_CHAR=1" \
  -o logs/ -e logs/ -l h_rt=24:00:00 -l mem_free=2G -wd ~/ChampSim-dev scripts/submit/run_cs.sh

qsub -t 1-45 -N rc_qmm   -v "WARMUP=$W,SIM=$S,TRACE_DIR=trace-files/QMM,TRACE_EXT=champsimtrace.xz,RUN_LABEL=livchar_unified_YYYYMMDD_HHMM/qmm,BINARY=champsim_lru_v1,LIVENESS_CHAR=1" \
  -o logs/ -e logs/ -l h_rt=24:00:00 -l mem_free=2G -wd ~/ChampSim-dev scripts/submit/run_cs.sh

qsub -t 1-95 -N rc_dpc3  -v "WARMUP=$W,SIM=$S,TRACE_DIR=/home/users/shared/traces/dpc3_traces,TRACE_EXT=champsimtrace.xz,RUN_LABEL=livchar_dpc3full_YYYYMMDD_HHMM/dpc3,BINARY=champsim_lru_v1,LIVENESS_CHAR=1" \
  -o logs/ -e logs/ -l h_rt=24:00:00 -l mem_free=2G -wd ~/ChampSim-dev scripts/submit/run_cs.sh
```
DPC3 **must** use `/home/users/shared/traces/dpc3_traces` (the full 95-trace set),
never the local `trace-files/dpc3_llc_pressured` 35-trace subset — see
`docs/PLOT_GENERATION_GUIDE.md`-adjacent project memory `project_dpc3_traceset.md`.
Google is not re-submitted here (see Known gaps); reuse
`results/liveness_char_20260608_0006/google` as-is.

**3. Download results locally** (not yet done as of this writing — these directories
exist only on the cluster):
```bash
rsync -avz castillo:~/ChampSim-dev/results/livchar_unified_20260616_1249 results/
rsync -avz castillo:~/ChampSim-dev/results/livchar_dpc3full_20260616_1251 results/
rsync -avz castillo:~/ChampSim-dev/results/liveness_char_20260608_0006/google results/liveness_char_20260608_0006/
```
Sizes: `livchar_unified` ≈ 588 MB, `livchar_dpc3full` ≈ 39 MB, `google` ≈ 1.8 GB.
After downloading, `dvc add` + `dvc push` + commit per the standard results workflow.

**4. Generate the plot:**
```bash
python3 scripts/analysis/plot_liveness_rates.py
```
This reads exactly the `SUITES` dict at the top of that script, which has been
corrected (2026-06-16) to point at the directories in the table above. It previously
pointed at `liveness_char_20260607_2036`, whose `google` subdirectory is empty —
that edit was uncommitted and never produced a working figure.

### Known gaps

- **Google not independently re-verified.** It's sourced as-is from
  `liveness_char_20260608_0006/google` (43 traces, ≈1.8 GB), which predates the
  `run_config.txt` provenance feature, so no embedded git/commit record exists for
  it. It's the literal data behind the paper's current figure, so there's nothing
  to suspect — but unlike the other six suites, it hasn't been independently
  regenerated and bit-for-bit-checked under the current commit. Re-running it is a
  ~1.8GB-output job away if full closure is wanted.
- **There is no citable commit for the binary that produced this data**, full
  stop — not "`a6c1c07` + dirty" (dirty means it isn't `a6c1c07`), and not
  `20e78aa` either (committed 2h12m after the build, bundling unrelated work, so
  it's an unverifiable superset of the actual dirty diff, not a snapshot of it).
  The bit-for-bit match against the pre-dirty 2026-06-08 run is empirical
  evidence — not proof — that whatever was dirty didn't touch the
  liveness-classification path.
  **Verified 2026-06-16:** the files that actually feed the build (`Makefile`,
  `src/`, `inc/`, `replacement/`) have zero diff against current HEAD
  (`20e78aa`) — confirmed with `git diff --stat`. A forced rebuild
  (`make -B /…/bin/champsim_lru`) from this exact tree succeeds in ~7s with no
  cleanup needed, and the resulting binary is byte-identical across two
  independent runs on the same trace (`champsim.out` and `run_config.txt`
  diffed clean except timestamp/hostname fields) — so *content-wise* this repo
  can already rebuild the right binary.
  **But it cannot yet self-report that.** `Makefile:50` computes
  `CHAMPSIM_GIT_DIRTY` from an unscoped `git status --porcelain` — any
  uncommitted file *anywhere* in the repo, not just build inputs, flips it to
  `dirty`. The fresh rebuild above still embedded `git_dirty=dirty` in its own
  `run_config.txt`, solely because of the ~100 unrelated untracked docs,
  scripts, and result directories sitting elsewhere in the tree right now. So
  getting a binary that *correctly self-reports* clean needs the whole repo
  triaged (commit or gitignore everything currently untracked/modified), not
  just the five build-relevant files. Until that triage happens, this doc's
  data is trustworthy (verified bit-for-bit against a known run, and the build
  inputs are independently confirmed clean) but the embedded provenance string
  will keep saying "dirty" even when it isn't, for the parts that matter.
- **`scripts/submit/run_cs.sh` was out of sync with the cluster (found and fixed
  2026-06-16 while drafting this doc).** The copy that actually produced the
  verified runs above had two lines — `export LRU_LIVE_HIT_INIT=${LRU_LIVE_HIT_INIT:-0}`
  and `export CHAMPSIM_RUN_CONFIG="${RUN_DIR}/run_config.txt"` — that were edited
  directly on the cluster and never committed to this repo (`git log` showed the
  local copy's last touch was a different, earlier commit, `e16845232f8a`, and
  `git diff` showed no pending changes — the edit existed only on castillo). This
  means the "rebuild from `20e78aa`" recommendation above is not actually
  sufficient by itself: a fresh checkout's `run_cs.sh` would build and run fine,
  but would silently produce *no* `run_config.txt` and a different
  `LRU_LIVE_HIT_INIT` default. The two lines have now been pulled into the local
  file (diffed clean against the cluster copy) but **are not yet committed** —
  do so before treating this doc as trustworthy for a clean-room rebuild.
- **Prose/data mismatch, not yet resolved:** `main.tex` (Motivation section) states
  the LLC DoA fraction ranges "51–97%" across suites. The verified pooled numbers
  above (plus Google's 73.79% from the 2026-06-08 run) span 68–98%; nothing
  computed here hits 51%. This may be stale prose from an earlier suite mix —
  flagged here, not investigated further as it's outside this figure's data
  pipeline.

---

## Table 1 — `tab:concentration` (per-PC DoA concentration, "n90")

### What it shows

For each trace under plain LRU, PCs are ranked by their LLC DoA-eviction count;
`n90` is the smallest number of top-ranked PCs whose combined DoA evictions reach
90% of the trace's total. The table reports min/mean/max of `n90` across each
suite's traces. It backs the paper's "DoA evictions are concentrated in a few PCs"
claim (`main.tex` lines ~129–138) — the concentration is the empirical basis for
using a small per-PC history table rather than per-block/per-address tracking.

Seven suites. **Google added 2026-06-29** from its Figure 1 run
(`liveness_char_20260608_0006/google`, 43 traces, which carries the
`LIVENESS_CHAR=1` per-PC dump — `blocks_in_sample=2`, all 43 files have the block).
Google is the least concentrated suite (mean ~28.6k PCs, max 49,254), even more
diffuse than QMM. Published values:

| Suite | Min | Mean | Max |
|---|---|---|---|
| GAP | 2 | 3.4 | 7 |
| GMS | 1 | 4.3 | 8 |
| ML | 1 | 4.6 | 10 |
| Ligra | 2 | 5.6 | 14 |
| DPC3 | 1 | 96.7 | 4,833 |
| QMM | 3,090 | 4,354 | 10,504 |
| Google | 246 | 28,576 | 49,254 |

### Data dependency

**Identical to Figure 1** — same six directories, same runs, same binary/commit
caveats (see the Figure 1 section above; not repeated here). The only additional
requirement is that the runs have `LIVENESS_CHAR=1` set, which they all do (see
the embedded `run_config.txt` in the Figure 1 section: `env LIVENESS_CHAR=1`) —
Table 1 needs the per-PC `LLC LIVENESS_CHAR BEGIN/END` dump, not just the
unconditional summary line Figure 1 uses.

### Computation script

**`scripts/analysis/compute_n90.py`** (added 2026-06-16, while writing this doc).

Before this, no version of this computation existed anywhere in this
repository's git history (`git log --all --diff-filter=A -- '*n90*' '*concentration*'`
returns nothing) — the original 2026-06-08 numbers above were produced by some
ad-hoc, never-committed process. This script is a faithful reimplementation of
the same definition (described in the docstring), and has been verified to
reproduce the published numbers exactly (see Verification below). It is written
to run under Python 3.3 (no f-strings) so it can also run directly on Castillo,
where the result directories currently live, matching the constraint already
documented in project memory for cluster-side scripts.

Invocation (from repo root, wherever `results/` actually has the data —
currently only on the cluster):
```bash
python3 scripts/analysis/compute_n90.py
```

### Verification: script output vs. published Table 1

**Pass 1 (2026-06-16):** ran `compute_n90.py` on castillo against existing
data from Figure 1's original run directories
(`results/livchar_unified_20260616_1249/{gap,gms,ml,ligra,qmm}`,
`results/livchar_dpc3full_20260616_1251/dpc3`):

```
Suite       n      min       mean        max
--------------------------------------------
GAP         9        2        3.4          7
GMS         9        1        4.3          8
ML         31        1        4.6         10
Ligra      17        2        5.6         14
DPC3       74        1       96.7       4833
QMM        45     3090     4353.8      10504
```

Exact match to the published table on every cell (QMM mean prints as `4353.8`
here vs. `4{,}354` in the table — that's rounding for display, not a
discrepancy: $4353.8 \to 4354$).

**Pass 2 (2026-06-17): full end-to-end job-launch verification.** Freshly
submitted 6 job arrays using `champsim_lru_v3` (static build from current
HEAD, `make static`, sha256 `d0bb3dafb7d2c627971b65abce320c5e2d9d21a066f2f899512afc03ed82de06`),
results under `tab1_verify_20260616_2030/{gap,gms,ligra,ml,qmm}` and
`tab1_verify_20260616_2030_dpc3/dpc3`. Three bugs in the documented recipe
were found and corrected during this run (see Known gaps). After fixing all
three, `compute_n90.py` run locally against the freshly downloaded results:

```
Suite       n      min       mean        max
--------------------------------------------
GAP         9        2        3.4          7
GMS         9        1        4.3          8
ML         31        1        4.6         10
Ligra      17        2        5.6         14
DPC3       74        1       96.7       4833
QMM        45     3090     4353.8      10504
```

Exact match to the published table on every cell. End-to-end reproducibility
confirmed: fresh binary + fresh cluster jobs → same published numbers.

### Exact regeneration recipe

1. Generate the data: identical to Figure 1's steps 1–3 (build, submit
   `LIVENESS_CHAR=1` jobs via `run_cs.sh`, download). No separate jobs needed —
   the same runs back both the figure and this table.
2. Run the script: `python3 scripts/analysis/compute_n90.py`.
3. Paste the printed min/mean/max columns into the `tabular` block in
   `main.tex` (`\label{tab:concentration}`) — this last step is manual; the
   script does not emit LaTeX.

### Known gaps

- Everything under Figure 1's "Known gaps" applies here too (no citable clean
  commit; `git_dirty` is unscoped repo-wide rather than build-scoped; Google
  doesn't apply to this table so that specific gap is moot here).
  `scripts/submit/run_cs.sh` being out of sync was the same root cause for both.
- `compute_n90.py` is a reimplementation, not the literal script that produced
  the 2026-06-08 numbers — there is no way to verify it's *identical* to
  whatever produced those numbers originally, only that it implements the same
  documented definition and reproduces the same outputs on the same inputs.
  Treat "exact match" above as strong agreement, not literal provenance.
- The LaTeX paste step (script output → `tabular` rows) is manual and
  unchecked — nothing currently diffs the script's output against what's
  actually committed in `main.tex` to catch drift if the data is regenerated
  later.
- **Bugs found and fixed in the recipe during Pass 2 (now corrected above):**
  1. `TRACE_EXT=champsimtrace.xz` for GMS was wrong — actual files are `.gz`.
  2. `-t 1-9` for GMS was wrong — `trace-files/gms` has 11 traces; `-t 1-11`
     required. The original results dir (`livchar_unified_20260616_1249/gms`)
     had 11 subdirectories, of which 2 had zero LLC evictions (no
     LIVENESS_CHAR block) and were skipped, leaving n=9 contributing traces —
     but this was not obvious from the published table alone.
  3. The binary deployed as `champsim_lru_v2` for the first attempt was
     dynamically linked (`make bin/champsim_lru`, not `make static`) and
     crashed immediately on Castillo with GLIBC/GLIBCXX version errors.
     Always use `make static` for cluster-bound binaries.

---

## Experimental Setup — data-status caveat (`tab:config`, `tab:traces`)

The figures in the paper were generated under two different configurations:

- **Config A** (older runs): 2 MB LLC, 1536-entry STLB; results reported vs. LRU.
  Suite set: 7 suites including Google (96 traces total).
- **Config C** (current): 2 MB LLC, 1024-entry STLB; results reported vs. SRRIP.
  Suite set: 6 suites, Google excluded (148 traces total).

Not all results sections have been unified under Config C yet. The LLC-level guidance,
scoring, size, and bypass results are representative but not all from one configuration.
A unified single-config rerun (Config C, vs. SRRIP) is planned and will replace the
mixed-config data.

---

## Internal-table replacement-policy study (Section: Bounded History Tables)

Data source: QMM exemplar from `hist_repl_*` and `tiered_test_*` (current config),
plus the older all-suite `*_repl_pol_20260522` runs (Config A). Not yet rerun
all-suites at current config; QMM is representative of the qualitative finding
(TIERED only beats LRU with active ROI churn + liveness diversity; cap=256 is
degenerate).

---

## Tables `tab:llc_size` and `tab:stlb_size` — history table size sensitivity

Data source: QMM, buf=128, `θ_LLC=4` / `θ_STLB=1`. A current-config all-suite size
study (`ours_sizestudy_20260614`, caps 256–unbounded, bypass-only) was submitted but
some arrays were cancelled (jids 1405299–1405301: lfu_c4096/tier_c4096/ref); pending
relaunch before final analysis. Once complete, these QMM-only tables will be replaced
with one-configuration numbers across all suites. The QMM curve is representative of
the "LLC saturates early" finding.

---

## Table `tab:scoring_modes` — scoring mode selection

Data source: `*_scoring_modes_20260608` on 31 LLC-pressured targeted traces,
`θ_md=10` / `θ_doa=20`. **Note:** these thresholds differ from the `θ=6/10` used
in the main results; the table is representative of Mode 5 being superior, not
same-parameter. Mode 5 is the adopted scoring. A full mode sweep is available for
QMM. A same-parameter comparison at current config thresholds has not been run.

---

## Figure `fig:live_vs_base` — liveness contribution over base policy

Shows geomean IPC speedup of each guided policy (SRRIP-Live, LRU-Live, IPV-Live)
over its own unguided base, isolating the liveness contribution from the base-policy
effect.

Data status (as of 2026-06-18):
- **SRRIP-Live / SRRIP**: complete (Ligra 17/18 traces).
- **IPV-Live / IPV**: complete (Ligra 17/18 traces).
- **LRU-Live / LRU**: GAP, GMS, QMM complete; DPC3, Ligra, ML pending.

All runs: current config (Config C), Mode 5, `θ=6`. Thresholds have not yet been
retuned for Mode 5 (older runs used per-suite optima); a θ re-tune is future work.

---

## Figure `fig:combined` — combined LLC+STLB guidance (currently `\iffalse`'d)

This figure is currently disabled in the paper (`\iffalse`). Data exists only for
DPC3, Google, and QMM (Config A, vs. LRU). At current config, STLB-level guidance
has been rerun only for QMM (`qmm_thd_rebaseline_20260607`); LLC-level guidance is
current for all 6 suites (`*_thd_rebaseline_20260607`).

Missing before this figure can be re-enabled:
- STLB guidance + combined results for GAP, GMS, Ligra, ML at current config.
- A plain (non-guided) IPV baseline at current config (needed for the
  LLC+STLB × SRRIP/IPV comparison figure).
