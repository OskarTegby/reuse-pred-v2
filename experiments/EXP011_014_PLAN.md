# exp011–014: Budget Trade-offs and Integration Study

## Motivation

**Central question**: For a realistic hardware budget, should we prioritize bypass prediction or replacement policy assistance?

Current best design uses separate tables for bypass (pHIST 1024/4096, buffer 128) and replacement guidance (later). We want to:
1. **Test shrinking tables** to use larger buffers (mechanism vs capacity)
2. **Unify indexing** to PC-aware (reduce aliasing, serve both bypass + replacement)
3. **Isolate value** of bypass vs replacement guidance at same budget
4. **Guide paper scope**: inclusion decision for bypassing vs replacement

---

## exp011 — Shrunk Tables with Larger Buffers

**Hypothesis**: Buffers are mechanism-driven. Shrinking main tables and increasing buffers (total capacity constant) should maintain performance.

**Configs**:
| Config | pHIST | pBuf | bHIST | bBuf | Total | Threshold |
|---|---|---|---|---|---|---|
| pbuf_sm_256 | 512 | 512 | 2048 | 2048 | same | (0,0) |
| pbuf_sm_256_default | 512 | 512 | 2048 | 2048 | same | (6,6) |

**Expected**: Similar performance to baseline (buffers prove their mechanism value).

---

## exp012 — PC-Indexed bHIST for Bypass Prediction Only

**Design**: PCPartitionedTable (256 PC × 16 addr = 4096 entries)
- Tracks dead evictions like current bypass predictor
- Used for **bypass decisions only** (confidence query)
- **Not used** for replacement guidance

**Question**: Does PC-aware indexing (reduced aliasing) improve bypass prediction?

**Configs**:
| Config | bHIST Mode | PC Ways | Addr Ways | Used For | Threshold |
|---|---|---|---|---|---|
| pc_bypass_only | pc | 256 | 16 | bypass | (0,0) |
| pc_bypass_only_default | pc | 256 | 16 | bypass | (6,6) |

---

## exp013 — PC-Indexed bHIST for Replacement Guidance Only

**Design**: Same PCPartitionedTable (256 PC × 16 addr)
- Tracks dead evictions
- Used to **guide replacement decisions only** (which blocks are likely dead?)
- **Not used** for bypass (use simple bypass heuristic: always bypass, or bypass at fixed low confidence)
- Tells replacement policy: "high dead_count entries are worth keeping, low ones can be evicted"

**Question**: How much speedup from replacement guidance alone?

**Configs**:
| Config | bHIST Mode | PC Ways | Addr Ways | Used For | Bypass Method | Threshold |
|---|---|---|---|---|---|---|
| pc_replacement_only | pc | 256 | 16 | replacement | always bypass | (0,0) |
| pc_replacement_only_default | pc | 256 | 16 | replacement | always bypass | (6,6) |

---

## exp014 — PC-Indexed bHIST for Both Bypass + Replacement (Full Integration)

**Design**: Same PCPartitionedTable (256 PC × 16 addr)
- Tracks dead evictions
- Used for **both bypass decisions AND replacement guidance**
- Full closed-loop integration

**Question**: Do bypass and replacement benefit compound, or is there contention?

**Configs**:
| Config | bHIST Mode | PC Ways | Addr Ways | Used For | Threshold |
|---|---|---|---|---|---|
| pc_both_integrated | pc | 256 | 16 | bypass + replacement | (0,0) |
| pc_both_integrated_default | pc | 256 | 16 | bypass + replacement | (6,6) |

---

## Analysis & Paper Decision

**Comparison matrix** (all at same 4096-entry budget for bHIST):

| Experiment | Config | Budget | Used For | (0,0) Speedup | (6,6) Speedup |
|---|---|---|---|---|---|
| 008 (baseline) | flat SRRIP+buf | 4096 | bypass | +14.94% | +9.89% |
| 012 | PC indexed | 4096 | bypass only | ? | ? |
| 013 | PC indexed | 4096 | replacement only | ? | ? |
| 014 | PC indexed | 4096 | both | ? | ? |

**Metrics to extract**:
- Pure bypass value: exp012 vs flat baseline
- Pure replacement value: exp013 vs flat baseline (no bypass improvement)
- Integration synergy: exp014 vs (exp012 + exp013)
- Budget efficiency: which subsystem (bypass vs replacement) yields more speedup per entry?

**Decision rule for paper**:
- If exp013 > exp012 by >2pp: replacement guidance is more valuable → focus on Phase 2
- If exp012 > exp013 by >2pp: bypass prediction is more valuable → keep Phase 1 in paper
- If similar: include both, show complementarity

---

## Implementation Notes

- **exp011**: Direct drop-in, same replacement policy (SRRIP+buf both tables)
- **exp012**: Use existing PCPartitionedTable for bypass, ignore replacement signals
- **exp013**: Use PCPartitionedTable for replacement guidance via dead_count signals; bypass via simple heuristic
- **exp014**: Full integration — both bypass and replacement use the same PC-indexed table
- All at (0,0) and (6,6) thresholds for realistic comparison
