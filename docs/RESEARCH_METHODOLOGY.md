# Research Methodology: Lessons Learned

## Experiment Turnaround and Iterative Validation

**Key Principle:** Fast turnaround on experiments is critical to research productivity. The speed at which you can validate or invalidate hypotheses directly determines how quickly you can uncover errors and move toward correct results.

### Best Practices

1. **Run smaller experiments first**
   - Instead of launching full 45-trace suite experiments, start with 2-10 traces to validate the setup
   - For threshold sweeps, test a few representative thresholds before a full sweep
   - For size studies, test a few key sizes before the full range

2. **Evaluate incrementally, not in batch**
   - Do NOT run both LLC and STLB experiments together and evaluate both at the end
   - Instead: run LLC experiments → evaluate results → decide on STLB strategy → run STLB experiments
   - This allows you to catch methodology errors after the first set, before investing in the second
   - Example from this project: should have evaluated the 4096-entry table performance before shrinking to 256, 128, etc.

3. **Debug runs catch errors early**
   - A single-trace debug run that reveals a fundamental bug (like `unbounded_=true` not being set) is worth 10× the cost
   - After each major code change, run a quick validation on 1-2 traces before submitting large jobs
   - This session: running cap=0 vs cap=256 single-trace tests caught the `unbounded_=true` initialization bug that invalidated weeks of experiments

4. **Validate assumptions before scaling**
   - Before submitting 315-job experiments (promotion buffer sweep), verify the basic mechanism works
   - Check that env vars are actually being applied by examining output stats (occupancy, classification breakdown)
   - Verify that code paths are being executed as intended

### Cost of Validation Errors

In this session:
- **Cost of not validating early**: ~1 week of compute time on invalid size study experiments (all results with `unbounded_=true` when bounded mode was intended)
- **Cost of validating early**: ~2 hours on debug runs to catch the bug before submitting large batches
- **Ratio**: ~84:1 in favor of early validation

### Single-trace existence checks

To determine merely *whether a configuration changes behavior at all* (e.g. does
enabling a feature, or changing a size, alter IPC / insert mix / activation
counts?), one trace is enough. A difference on a single trace proves the knob is
wired and doing something; identical output on a single trace is strong evidence
it is inert (modulo trace-specific luck). Only escalate to many traces once you
need the *magnitude* of an effect averaged across workloads — never to answer the
binary "does this do anything?" question. This keeps the debug loop seconds-long
instead of minutes-long.

### Workflow Pattern

For any new experiment type:
1. **Hypothesis validation** (1-2 traces) — does the code even run?
2. **Mechanism validation** (2-10 traces) — are the right env vars applied? Are stats printed correctly?
3. **Baseline comparison** (10-20 traces) — does the mechanism produce the expected direction of results?
4. **Full experiment** (45+ traces) — only after steps 1-3 confirm the approach is sound

5. **Zero-size sanity check for any size parameter**
   - Before testing a range of sizes, first verify that setting the size to zero
     disables the technique entirely and falls back to the baseline behavior.
   - If size=0 does NOT produce the same result as the disabled baseline, the
     size parameter is not properly guarding the mechanism — the technique may
     be active through a different code path regardless of the size setting.
   - Example: `REPL_HIST_LLC_CAP=0` does NOT disable liveness guidance — it
     leaves `repl_hist_pc` in unbounded mode. So "zero" is not "off" here.
     The correct zero-size test is to set `SRRIP_LIVE_TARGET=none` and verify
     that result matches plain SRRIP/IPV exactly. Only once that is confirmed
     can you trust that non-zero sizes are measuring the right thing.
   - This check costs one extra job and can save weeks of misinterpretation.

### Apply to Current and Future Work

- Before submitting aggressive size sweeps (8-4096 entries), verify a single intermediate size (256) works correctly
- Before running promotion buffer sweeps, validate that each buffer size is actually being used (check instrumentation output)
- Before combining LLC and STLB in the same run, verify each level individually first

This principle has proven itself in this session: the `unbounded_=true` bug would have remained hidden for much longer without the cap=0 vs cap=256 comparison test. Early, small validation runs are not overhead — they are the highest-ROI use of compute time in experimental research.

---

## Cutting Time Between Experiments: Advanced Techniques

### 6. Submit one array per (suite, config) — analyze per suite as it finishes

Never submit one monolithic job array covering all suites and configs together.
Instead, submit each (suite, config) combination as its own independent array.
This means that when QMM finishes all three configs, you can analyze QMM
immediately — you do not have to wait for DPC3, Ligra, or ML.

**Why it matters:** Suite completion times are highly uneven. GAP (9 traces) and
GMS (11 traces) finish in a fraction of the time that QMM (45 traces) or ML (31
traces) do. With tandem-per-suite submission, fast suites yield actionable
results within minutes; slow suites arrive later without blocking analysis of
the fast ones.

**How to apply:** In every submit script, the inner loop iterates over suites and
submits one `qsub -t 1-N` call per (suite, config) pair. Each call becomes one
job array. The result directories are labelled `<label>/<suite>/<config>/`.
Analysis scripts then operate per-suite and aggregate across whichever suites
have finished.

### 7. Partial analysis with matched-pair filtering

When some traces within a suite are still running, do not skip the suite —
analyze the completed subset. Filter to only traces where all configs have a
valid final IPC line (`^CPU 0 cumulative IPC:`). This gives a valid, unbiased
geomean for the completed fraction.

**Pitfall to avoid:** Counting files with `find ... -name champsim.out | wc -l`
reports file *existence*, not simulation *completion*. Jobs write output files
as they start, but the final IPC line only appears when the simulation finishes.
Always check for the IPC line, not just file presence.

### 8. Run baselines once, keep them in a dedicated directory

A baseline (SRRIP, LRU — any non-guided reference policy) does not change between
experiments. **Run it exactly once per (policy, binary, trace set, sim window) and
store it in a single canonical place that is never overwritten, never re-run, and
never confused with a sweep point.** Re-run a baseline only when the binary or the
trace set genuinely changes — and when that happens, create a new dated baseline,
do not silently replace the old one.

**Canonical location:**
- Cluster: `~/ChampSim-dev/results/baselines/{srrip,lru,ipv}/{suite}/{trace}/`
- Local mirror: `results/baselines/{srrip,lru,ipv}/{suite}/{trace}/`
- The shared `PROVENANCE.txt` records, per policy, the binary, scoring_mode,
  warmup/sim window, suite/trace coverage, source run, and date.

As of 2026-06-20 the canonical set is `srrip` (`champsim_srrip`, pure SRRIP — the
primary baseline), `lru` (`champsim_lru`), and `ipv` (`champsim_ipv`, baseline for
IPV-Live), each 251 traces across all 7 suites at 50M/100M. These binaries
hard-disable liveness guidance: verified that `SCORING_MODE`, `THD_DOA`, and
`SRRIP_LIVE_TARGET` have zero effect on IPC. `run_info.txt` still echoes
`scoring_mode=2` / `thd_doa=1` as inert env-var defaults, and the output still
prints DoA/MOSTLY_DEAD/MOSTLY_ALIVE characterization counters — neither means a
feature is on. A baseline has no features enabled; ignore those fields. srrip/lru came from `allsuites_thd_phase1_20260617_0020`; the pure-IPV
runs were never batched together, so ipv was assembled per-suite from the
`*_missing_policy_*` dirs (see PROVENANCE.txt for the exact source per suite).
Caveat: some ipv suites carry a `.champsimtrace` suffix on trace dir names while
srrip/lru do not — normalise (strip a trailing `.champsim[s]trace`) when matching
trace names across policies.

**A baseline is defined by four things — pin all of them:** the policy, the exact
binary, the trace set, and the warmup/simulation window. Two "SRRIP" runs that
differ in any of these are not the same baseline. Speedups computed against the
wrong one are silently wrong by the size of the baseline gap.

**Cautionary tale (why this section exists):** an earlier threshold table divided
by `bypass_allsuites_20260610_2312/*/srrip`, which *looked* like a SRRIP baseline
but was built with `champsim_srrip_live_hrp` — the liveness binary with
hit-promotion machinery, ~4% faster than pure SRRIP. It also covered only the
35-trace DPC3 subset and was missing Google entirely. Dividing by it deflated
every speedup and flipped GAP from "+6% win" to "−1% loss." The fix was to divide
by the co-located pure-SRRIP run. **Always confirm the baseline's binary and
config before trusting it:** `grep -E '^binary=|^scoring_mode=' run_info.txt`
should show the pure policy, not a `_live`/`_hrp` variant. DO NOT use
`bypass_allsuites_20260610_2312/*/srrip` as a SRRIP baseline.

### 9. Verify env vars took effect before reading results

After every new experiment type, grep one output file for the config echo line
before pulling down all results. The binary prints applied env vars at startup.
If `scoring_mode=2` appears when you expected `scoring_mode=5`, the run is
invalid and should be re-queued — not analyzed.

**Example bug caught this way:** Bounded HistTable runs (`REPL_HIST_LLC_CAP > 0`)
reconstructed `repl_hist_pc` after `set_scoring_mode()` was called, silently
resetting the scoring mode to the default (2). This was caught by inspecting the
Insert mix stat (`DoA: 0.0%` instead of `DoA: 62%`) before downloading 730
result files.

### 10. Download results by streaming tarballs, not rsync

Use `ssh castillo 'tar czf - <dirs>'` piped locally rather than rsync with a
ProxyJump host. Rsync through a two-hop SSH chain requires agent forwarding at
both hops and fails silently on permission errors. The tarball approach is one
command, works reliably, and transfers only what you explicitly name.

```bash
ssh -A abdet "ssh -A castillo 'cd ~/results && tar czf - suite1/config suite2/config'" \
  > /tmp/results.tar.gz
tar xzf /tmp/results.tar.gz -C local/results/
```

### Summary: Time-Cutting Checklist

Before every new batch of experiments:
1. One-trace sanity check — does the mechanism activate? Are env vars applied?
2. Submit per (suite, config), not one big array
3. Reuse the canonical baselines in `results/baselines/{srrip,lru,ipv}` — never re-run a baseline (and verify its binary with `grep '^binary=' run_info.txt` before trusting it)
4. Check IPC line (not file existence) to determine completion
5. Analyze fast suites (GAP, GMS) immediately; don't wait for slow ones (QMM, ML)
6. Grep config echo in one output file before downloading everything

---

## AI-Assisted Development: Code Quality and Testing

Using an LLM to edit the simulator code speeds up implementation but introduces a
specific failure mode: the assistant edits what it can see and reason about locally,
without necessarily understanding the full invariant space of the system. Two
concrete bugs from this project illustrate the pattern.

**The `cap_score` bug** — the bounded history table had a clamping lambda that
prevented scores from crossing `thd_doa` upward. The fix was correct in isolation,
but the underlying issue (that the bounded table used a single score to represent
what is semantically two independent counters) was missed entirely. The assistant
fixed the symptom without diagnosing the cause.

**The bounded-table mode-5 bug** — the bounded table's update path used
`score_delta()` (+1/0/−1) for all scoring modes, ignoring the state-dependent
inverted weights (5/3/1) and two-counter semantics of mode 5. The unbounded path
had been updated to implement mode 5 correctly; the bounded path had not. This went
undetected for weeks because the bounded table still produced non-zero DoA
classifications (the score did cross `thd_doa`), just via a different mechanism.
Only direct comparison of `Insert mix` stats between bounded and unbounded runs
revealed the discrepancy.

### Lessons

1. **Read every AI-generated code change — not just skim the diff.**
   The goal is not only to catch bugs but to maintain comprehension of the
   codebase. If you do not read and understand a change, you lose track of what
   the code is actually doing. Once that happens, you cannot meaningfully verify
   the next change either, because you no longer have a mental model to check it
   against. The effect compounds: unread AI code makes every subsequent edit
   harder to reason about, and the code gradually becomes effectively unreadable
   to its own author. At that point you are no longer doing research — you are
   operating a black box.

   Read the change. If you cannot explain what it does and why, it is not ready
   to run. Pay particular attention to: (a) changes that touch multiple code paths
   where only one path is being tested, (b) data structure changes (adding a field
   requires updating every init, reset, copy, and serialisation site), and (c)
   any place where the assistant assumes which branch of a conditional "matters."

2. **Do not use AI for changes you can write yourself in a few minutes.**
   AI assistance is most valuable for boilerplate-heavy or structurally repetitive
   edits. For a small, well-understood change — fixing an off-by-one, adjusting a
   threshold, adding a single printf — writing it by hand is faster, forces you
   to read the surrounding code, and keeps you in contact with the implementation.
   Reaching for the assistant by default, even when it is unnecessary, erodes that
   contact over time.

3. **Write a blackbox test for every implemented feature.**
   A blackbox test here means a one-trace simulation whose output is fully
   deterministic and whose key statistics can be checked automatically against
   expected values. Concretely, for each scoring mode / bounded-vs-unbounded
   combination, there should be a reference output file capturing: IPC, Insert mix
   (DoA%, Dead%, Alive%), RRPV@evict DoA, and `repl_hist` transition counts. Any
   subsequent change to `cache.h` or `cache.cc` should be followed by re-running
   these reference traces and diffing the stats. A regression in DoA% or Dead%
   immediately flags a broken update path, a broken classify path, or a missing
   counter reset — before any cluster time is spent.

   The cost of writing the reference test is one trace run (~5 minutes). The cost
   of not having it is weeks of invalid results and multi-session debugging.

4. **Treat parallel code paths as independent features that each need a test.**
   The unbounded and bounded code paths in `HistTable::update()` implement the same
   logical operation but in different ways. A test that only exercises the unbounded
   path gives no information about the bounded path, and vice versa. Every scoring
   mode must be tested in both the bounded and unbounded cases explicitly.
