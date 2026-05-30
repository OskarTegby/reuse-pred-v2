# Research Narrative: History Tables and Liveness-Driven Prediction

## Core Idea

**History tables can be substantially improved by storing and using liveness data more effectively.** This data can then be reused to drive replacement policies, and eventually prefetchers — creating a unified system where bypass prediction informs all three subsystems.

## Execution Strategy: Three Phases

### Phase 1: Bypass Predictor Development ✓ (current)

**Goal**: Maximize bypass prediction accuracy by better capturing and using liveness data.

**Completed work**:
- ✅ Replacement policy improvements: DoA-LFU (freq increments only on dead evictions)
- ✅ Two-stage promotion buffer with re-entry (closed-loop feedback)
- ✅ PC-aware indexing infrastructure (PFQ carries PC, bHIST ready for PC indexing)

**Remaining work**:
1. **PC-indexed bHIST** (exp009+): Index by (PC, address) instead of address alone
   - Hypothesis: PC context reduces aliasing and improves prediction
   - Run on all QMM workloads to establish baseline improvement
   
2. **Threshold feedback loop** (exp010+): Replace static threshold with adaptive control
   - Current: bypass at threshold T, reset counter (wastes signal)
   - Proposed: count actual bypasses, use bypass rate to improve threshold and inform replacement
   - Benefit: closure between predictor confidence and actual bypass utility
   - Impact: better replacement policy decisions based on realized vs. mispredicted bypasses

**Exit criteria for Phase 1**: PC-indexed bHIST + adaptive threshold together outperform current design, validated on all workloads.

---

### Phase 2: Replacement Policy Assistance

**Goal**: Reuse the liveness data and predictions from Phase 1 to improve cache replacement.

**Approach**:
- Use bypass predictor output (confidence, PC context, realized bypass utility) to inform cache replacement
- Example: entries with high bypass confidence → lower eviction priority (they're likely dead); entries with low confidence → higher priority (likely live)
- Benefit: replacement policy becomes *aware* of application patterns via the predictor

**Entry criteria**: Phase 1 complete, bypass prediction robust across workloads.

---

### Phase 3: Prefetcher Assistance

**Goal**: Use accumulated liveness and pattern data to drive prefetch decisions.

**Approach**: Same philosophy as Phase 2 — prefetcher becomes aware of which blocks are persistently dead/alive via the predictor.

**Entry criteria**: Phase 2 complete, replacement + bypass working in tandem.

---

## Why This Ordering?

1. **Bypass predictor first**: Simplest feedback loop, clearest signal (bypass happened or didn't)
2. **Replacement next**: Reuses predictor design, extends scope to L3 victim selection
3. **Prefetcher last**: Most complex feedback, benefits from mature predictor + replacement

## Why This Matters for the Paper

The paper's narrative is **"better use of liveness data improves all prediction tasks."** Each phase demonstrates this:
- Phase 1: Shows that careful history-table design (DoA-LFU, buffers, PC-awareness, feedback) significantly improves bypass prediction
- Phase 2: Shows that this same data improves replacement decisions
- Phase 3: Shows that consistent application across subsystems yields compounding benefits

**Key insight**: The improvement isn't from new hardware, but from *closing feedback loops* and *reusing signals across subsystems*. One unified view of liveness (from STLB via PFQ, accumulated in predictors, fed back to replacement) drives the entire system.

---

## Current State

- **Phase 1 status**: 85% complete
  - ✅ DoA-LFU, buffers, SRRIP (with fix) validated at (0,0) and (6,6)
  - ⏳ PC-indexed bHIST: design ready, needs experiments (exp009+)
  - ⏳ Adaptive threshold: design needed, requires bypass-rate instrumentation

- **Next immediate step**: Implement and test PC-indexed bHIST on all workloads
