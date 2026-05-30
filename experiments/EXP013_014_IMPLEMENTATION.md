# exp013–014: Implementation Notes

These experiments require **Phase 2 implementation** — integrating liveness signals into replacement policy.

## exp013 — PC-Indexed bHIST for Replacement Guidance Only

**What needs to be added to cache.cc:**

1. **Query the bHIST during replacement victim selection**:
   - Instead of `victim_slot()` selecting purely on RRPV/freq/ts, consult `bhist_pc.get(pc, address)`
   - High `dead_count` in bHIST → entry is often dead → prioritize eviction (good victim)
   - Low `dead_count` → entry often accessed → deprioritize eviction (keep it)

2. **Integrate into `victim_slot()` logic**:
   ```
   For each entry E in cache:
     score = base_replacement_priority(E)  // SRRIP rrpv or LFU freq
     dead_hint = bhist_pc.get(E.pc, E.address)
     if dead_hint > threshold:
       score += boost  // penalize (make it a better victim)
     return entry with highest score
   ```

3. **Bypass decision**: Set to always bypass or use fixed low threshold (e.g., BCONF_THD=1000)
   - Goal: isolate replacement guidance value by removing bypass benefit

## exp014 — PC-Indexed bHIST for Both Bypass + Replacement

**What needs to be added:**

1. Use `bhist_pc.get(pc, address)` for **both**:
   - Bypass decision: `if dead_count > BCONF_THD, bypass`
   - Replacement guidance: `if dead_count > REPL_THD, prioritize eviction`

2. Two independent thresholds:
   - `BCONF_THD`: bypass confidence threshold
   - `REPL_THD`: replacement guidance threshold (can be same or different)

3. May need environment variables:
   - `REPL_GUIDANCE=1/0`: enable/disable replacement guidance
   - `REPL_THD=N`: threshold for replacement decisions

---

## Staged Implementation

**Phase A (current work)**:
- ✅ exp011: shrunk tables (mechanism test, no code changes)
- ✅ exp012: PC-indexed bypass (already supported by existing PCPartitionedTable)
- ⏳ exp013: replacement guidance (needs ~20 lines in victim_slot())
- ⏳ exp014: both (exp013 + exp012 combined)

**Recommended order**:
1. Submit exp011 and exp012 now (straightforward)
2. Implement replacement guidance for exp013
3. Combine for exp014
4. Analyze to answer: "bypass or replacement?"

---

## Expected Insights

- **exp013**: Pure replacement policy value at 4096-entry budget
- **exp012**: Pure bypass prediction value at 4096-entry budget
- **exp014**: Integration benefit (synergy or contention?)

This answers: **"For the paper, should we focus on bypass prediction (Phase 1) or replacement policy assistance (Phase 2)?"**
