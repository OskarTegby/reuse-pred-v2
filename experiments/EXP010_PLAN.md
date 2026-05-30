# exp010 — Adaptive Threshold via Bypass Feedback

## Motivation

Currently the bypass threshold is static: **"if confidence > T, bypass; else fill"**. When we bypass, the counter is reset — we lose the signal about whether the bypass was correct (block never accessed again → good prediction) or wrong (block accessed → misprediction).

By tracking *bypass outcomes* (did the bypassed block actually stay dead?), we can:
1. **Adapt the threshold** based on real bypass success rate
2. **Inform the replacement policy** about which PCs/addresses are reliable bypass targets
3. **Close the feedback loop** between predictor and the hardware that uses its output

## Instrumentation Needed

### New Statistics to Track

At LLC level, for each bypass decision:
- **bypass_count**: how many times we bypassed
- **bypass_dead**: of those bypasses, how many blocks stayed dead (never re-accessed)
- **bypass_mispredicted**: blocks we bypassed but then accessed (wasted opportunity)
- **bypass_success_rate**: dead / (dead + mispredicted)

### Implementation Strategy

1. **Mark bypassed blocks** in L3 fill: add a bit to BLOCK struct or shadow table
2. **Track on eviction**: when a bypassed block evicts, check if accessed==true (misprediction) or accessed==false (correct prediction)
3. **Report per-workload**: bypass_count, bypass_dead, bypass_mispredicted at ROI boundary
4. **No threshold adaptation yet** — just instrumentation; use data to design exp011

## Experiment Scope (exp010)

- **Goal**: Establish baseline bypass feedback metrics
- **Traces**: QMM workloads (45)
- **Configs**: 
  - Flat bHIST + SRRIP+buf (best design from 005b) at (0,0)
  - Optional: repeat at (6,6) to see threshold impact on bypass success rate
- **Metrics**: bypass_count, bypass_dead, bypass_mispredicted, success_rate per workload
- **Analysis**: 
  - Are bypass predictions reliable? (high success_rate → yes; low → misprediction problem)
  - Does success_rate vary by workload? (suggests threshold should be workload-aware)
  - Correlation between bypass_success_rate and overall speedup?

## Follow-up (exp011 — future)

Once we have feedback data, design threshold adaptation strategies:
- **Per-workload threshold tuning**: adjust T based on observed success_rate
- **Dynamic threshold**: adjust within a run based on recent bypass outcomes
- **PC-specific thresholds**: different T for different PCs based on their bypass success pattern

This data also feeds into Phase 2: replacement policy can use bypass_success_rate to prioritize eviction of entries with high bypass confidence.

## Why This Matters

This is the **closure of the first feedback loop** in the liveness-driven prediction system. Instead of predicting in isolation, we're now observing outcomes and using them to improve future predictions.
