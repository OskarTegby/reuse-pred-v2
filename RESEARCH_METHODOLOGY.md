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
