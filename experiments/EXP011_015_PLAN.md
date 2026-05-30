# exp011–015: PC-Indexed History Table and Replacement Integration

## exp011 — Baseline with Default Threshold

**Confirm baseline design at realistic (6,6) threshold**:
- pHIST: 1024 ways + 128-entry buffer, SRRIP+buf
- bHIST: 4096 ways + 128-entry buffer, SRRIP+buf
- Threshold: (6,6) only

**4 workload variants** × 45 traces = 180 tasks

---

## exp012 — PC-Indexed bHIST for Bypass Prediction Only

**Test pure bypass prediction value**:
- PCPartitionedTable: 512 PC × 8 addr = 4096 total
- Used **only for bypass decisions** (confidence query)
- Replacement: standard LRU or SRRIP in cache, no guidance from bHIST
- pHIST: unchanged (1024 + 128buf)

**Configs** (2 thresholds) × 45 traces = 90 tasks

---

## exp013 — PC-Indexed bHIST for Replacement Guidance Only

**Test pure replacement policy value**:
- PCPartitionedTable: 512 PC × 8 addr = 4096 total
- Used **only to guide replacement** via dead_count signals
  - High dead_count → entry is often dead → prioritize eviction
  - Low dead_count → entry is often live → deprioritize eviction
- Bypass: simple heuristic (always bypass, or fixed low threshold)
- pHIST: unchanged (1024 + 128buf)
- **Per-address replacement policy**: DoA-LFU at inner (address) level

**Configs** (2 thresholds) × 45 traces = 90 tasks

---

## exp014 — PC-Indexed bHIST for Both Bypass + Replacement

**Test full integration**:
- PCPartitionedTable: 512 PC × 8 addr = 4096 total
- Used **for both bypass decisions AND replacement guidance**
- Two independent thresholds:
  - BYPASS_THD: for bypass confidence
  - REPL_THD: for replacement decisions
- **Per-address replacement policy**: DoA-LFU

**Configs** (2 thresholds) × 45 traces = 90 tasks

---

## exp015 — Address-Per-PC Allocation Study

**Characterize utility of address slots per PC**:
- Fix budget at 4096 entries, vary PC/address split
- Test configurations:
  - 512 PC × 8 addr (current)
  - 512 PC × 4 addr
  - 256 PC × 16 addr
  - 256 PC × 8 addr
- Measure: bypass accuracy, replacement guidance signal strength, overall speedup
- **Per-address replacement policy**: DoA-LFU for each configuration

**Question**: How many address slots per PC are actually useful before diminishing returns?

**Configs** (4 splits, 2 thresholds) × 45 traces = 360 tasks

---

## Key Differences from Prior Plan

1. **512 PC × 8 addr** (not 256 × 16): tests deeper PC-awareness, fewer addresses per PC
2. **Per-address replacement policy**: DoA-LFU within each PC's address table
3. **exp015 sweep**: isolates optimal PC/address trade-off
4. **All at (6,6)** (except exp015 which tests both) for realistic deployment
5. **Separate bypass/replacement** (exp012/013) before testing together (exp014)
