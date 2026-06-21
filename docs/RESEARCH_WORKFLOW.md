# Research Workflow

A structured process for moving from a research question to a paper result without
losing track of what was done, why, and what it showed.

---

## 1. Define the questions first

Before writing any code or submitting any jobs, write down the specific questions the
work is trying to answer. Be concrete:

> "Does PC-indexed liveness prediction improve LLC replacement for QMM?"
> "What threshold gives the best trade-off between DoA precision and recall?"

Questions live in the experiment log (see §3). Everything else — implementation,
experiments, analysis — is in service of answering them.

---

## 2. Design the experiments before implementing

For each question, write down:

- What experiment would answer it
- Which policy/binary/config variation is needed
- Which workloads and parameter values to sweep
- What the expected outcome would be if the hypothesis is correct

Only then implement. This prevents implementing something, running it, and realising
it does not actually answer the question.

---

## 3. Keep an experiment log

For every experiment, record the following **before submitting jobs**:

```
## Experiment: <short name>

**Question:** What is this trying to answer?

**Hypothesis:** What outcome would confirm or refute the hypothesis?

**Implementation:** Which files changed, and what do they do?

**Empirical test:** How was the code tested before the full sweep?
  - e.g. "ran thd=1 vs thd=8 on 5 QMM traces (25M warmup / 50M sim);
    confirmed thd=1 ≠ thd=8 and activation rate = 100%"

**Commit:** <hash>  (commit before submitting, so the hash is known)

**Config:** Which JSON build config was used? What are the key parameters?
  - LLC: sets × ways, replacement policy
  - STLB: sets × ways
  - Warmup / sim instruction counts
  - Environment variables (MID_THD, LOW_THD, BHIST_MODE, ...)

**Jobs:** Result directory, job IDs, submission timestamp

**Key result:** (fill in after results arrive)
  - Geomean speedup, optimal threshold, failure mode, etc.

**Analysis:** Why did it work or not work?
  - Connect back to the original question with a yes/no/partial answer.
```

---

## 4. Implementation rules

- Read the changed code in full before building. Diffs alone are not enough.
- Verify the compiled binary's cache config in `.csconfig/<hash>/inc/core_inst.inc`,
  not just the JSON input file. Sizes default to ChampSim built-in values for any
  field not explicitly specified.
- After building, run a single trace directly (or as a 1-task cluster job with
  25M warmup / 50M sim) and confirm the expected output is present before any sweep.
- Never submit a full sweep until a small test passes.

---

## 4b. Work in the smallest possible increments

The goal is to get signal as fast as possible and fail early rather than late.

**Sequence within any experiment:**

1. **Debug run first** — 1 trace, 25M warmup / 50M sim. Verify the binary runs,
   produces the expected output format, and the key metric is non-zero.
2. **Sample run** — 3–5 traces, 25M warmup / 50M sim, across the parameter range
   you care about (e.g. thd=1 vs thd=8). Verify direction and threshold sensitivity.
3. **One cache level at a time** — run LLC results first, analyse them, and only
   proceed to STLB once the LLC results look correct. Do not submit LLC and STLB
   simultaneously if the LLC results have not yet been validated.
4. **One suite at a time** — if the experiment is multi-suite, run one suite first.
   Results from a fast suite (e.g. GAP, 9 traces) can validate the implementation
   before committing 200+ traces to a slow suite.
5. **Full sweep last** — only after steps 1–4 pass.

The cost of a wasted full sweep is 10–20× the cost of a sample run. Every hour
spent validating a sample run saves days of waiting for a broken full sweep.

## 4c. Monitor results incrementally as jobs complete

Do not wait for all jobs to finish before looking at results. As soon as the first
policy and baseline traces are done, download them and compute partial geomeans. This:

- Catches configuration mistakes early (e.g. wrong cache size, guidance disabled)
  while most jobs are still running and can be cancelled
- Gives a preview of the direction (positive/negative speedup, threshold sensitivity)
  before committing to waiting for the full sweep
- Surfaces outlier traces immediately so they can be investigated

**In practice:** after the first batch of a policy finishes (typically 5–15 traces),
rsync just that subdirectory and run the analysis script. Re-run every 20–30 minutes
as more complete. The geomean will stabilise as N grows; large swings between updates
are a signal that something is wrong.

**What to check on each incremental update:**
1. Are the IPC values in a plausible range? (Cross-check a few traces against the LRU
   baseline immediately — same order of magnitude, same direction as expected.)
2. Is the activation rate non-zero for guided policies?
3. Does the LRU baseline match any reference run for the same config?
4. Is there threshold sensitivity (thd=1 ≠ thd=8)?

If any of these fail on the first batch, cancel the remaining jobs and investigate
before the cluster time is wasted.

---

## 5. Before submitting any sweep

Checklist:

- [ ] Small test (1–5 traces, 25M/50M) completed and key metric verified
- [ ] Code reviewed in full (not just diffed)
- [ ] Binary cache config verified against intended spec
- [ ] **Committed** — the commit hash is recorded in the experiment log
- [ ] Experiment log entry written with question, config, and commit hash

---

## 6. After results arrive

- Download results promptly; do not let them accumulate on the cluster.
- Record the key result in the experiment log entry.
- Write a brief analysis: what did it show, why, and what it means for the next step.
- If the result is negative, record that too — it is still an answer.

---

## 7. Paper data provenance

All data needed to reproduce every figure in the paper must live in
`results/paper/data/`. The directory must contain:

- The extracted plot data (JSON or CSV)
- `DATA_LOG.md` with one entry per figure: source directory, commit hash, config,
  submission date, and a one-line description of what the data shows

The paper's `main.tex` and all plot scripts reference `results/paper/data/` directly.
Regenerating a figure should require nothing more than running the plot script.
No figure should depend on data that exists only on the cluster or only in memory.

---

## 8. Naming and directory conventions

Result directories are named `<suite>_<experiment>_<YYYYMMDD>_<HHMM>/`.
The timestamp ties the directory to the experiment log entry.
Subdirectories follow the pattern `<policy>/<threshold_or_variant>/<trace>/`.

Never overwrite a result directory. If a sweep must be rerun, use a new timestamp.
The old (incorrect) directory is evidence of what went wrong — leave it and note it
in the experiment log.

---

## 8b. Additional lessons from practice

**Share preliminary results as early as possible.**
As soon as there are results from even a handful of traces, report them — even if
they are incomplete or ambiguous. A preliminary result that says "thd=1 hurts QMM"
after 5 traces saves days of waiting for a full sweep to confirm what could already
be seen. The goal is to identify wrong directions early and change course before
wasting cluster time. Never wait for the full sweep to be sure before discussing
results.

**Write the expected outcome before running.**
Before submitting any job, write one sentence stating what you expect to see and why.
If the result differs, you immediately know something surprising happened and can
investigate with the right frame of mind rather than post-hoc rationalising.

**Distinguish exploratory from validation runs.**
- Exploratory: 2–5 traces, 25M warmup / 50M sim. Checks direction and behaviour.
- Validation: full trace set, full instructions. Only after exploratory confirmed the
  implementation is correct.
Never skip exploratory and go straight to validation.

**Verify the compiled binary config, not the JSON.**
After every build, record the LLC and STLB sets×ways from
`.csconfig/<hash>/inc/core_inst.inc` in the experiment log entry alongside the
commit hash. The JSON input file is not the ground truth — the compiled config is.

**Negative results deserve the same documentation as positive ones.**
"thd=1 hurts because 86% DoA insertions produces too many false positives" is a
complete and valuable result. Record the reason in the experiment log; it prevents
revisiting the same parameter range later.

**Copy data to `results/paper/data/` before closing an experiment.**
Do it while the context is fresh. It never happens if left for later.

---

## 9. What not to lose

- The commit hash for every result.
- The exact environment variables used (captured in `run_info.txt` by `run_cs.sh`).
- The answer to the question, even if the answer is "it did not work".
- The reason why something did not work — see `ERRORS_LOG.md`.
