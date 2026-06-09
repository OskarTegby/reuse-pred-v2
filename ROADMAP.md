# Research Roadmap

**Paper**: Liveness-guided cache replacement and bypass  
**Target**: HPCA 2026  
**Spine**: A per-PC/per-address dead-count history table, filtered through the prefetch queue, drives both replacement and bypass using the same indexing and the same stored data. The last step shrinks the hardware footprint by monitoring only a small set sample.

The major gains come from three things already in hand: the indexing dimension (PC vs. address depending on workload class), the replacement policy (SRRIP-Live), and the PFQ filter. Bypass is incremental — only worth including if it adds meaningful speedup without requiring a different infrastructure. Prefetching is out of scope.

---

## Phase 1 — Replacement: lock in thresholds and joint speedup (in progress)

**Scoring mode**: mode5_recal is the winner. Config: `SCORING_MODE=5,THD_DEAD=10,THD_DOA=20`.  
Overall geomean vs LRU: ~+3.4% on high-spread targeted traces (2026-06-09).

- [x] Five-way scoring mode comparison on high-spread targeted traces (6 suites)
- [x] Selected mode5_recal: wins 4/6 suites, +3.4% overall geomean vs LRU
- [ ] Full-suite sweep of mode5_recal across all ~184 LLC-pressured traces (final paper numbers)
- [ ] Investigate vit.large (−12% vs LRU, all modes) and stable-diffusion regressions
- [ ] Compute joint LLC+STLB speedup for all suites at optimal settings
- [ ] Update paper tables

**History table replacement policy** (branch `hist-repl-policy`, commit `575f4e7`):
- Weighted scoring: DoA +3, MD +1, MA −2; temporal aging; FREQ_CAP=64
- Lifespan tracking per class added to `srrip_live` final stats
- Comparison run against old policy currently running (jobs 1405041–1405052)
- **Next investigation**: calibrate δ values proportionally to observed average lifespans
  per liveness class (data from `Avg lifespan(cy)` line in final stats output)

**Decision gate**: Is joint speedup consistent and significant across suites? Does address indexing fix the graph/ML STLB regressions?

---

## Phase 2 — Filter: PFQ-gated liveness activation

**Goal**: Only record liveness observations for lines that entered via the prefetch queue. Demand fills are always needed so their liveness is uninteresting; PFQ gating focuses the history table where DoA classification is actionable and avoids polluting it with demand-fill noise.

- [ ] Gate `repl_hist` updates on a PFQ-hit flag in the LLC fill path
- [ ] Evaluate: does gating sharpen classification accuracy and improve IPC?
- [ ] Check coverage: what fraction of LLC fills are prefetch-sourced per suite?

**Decision gate**: Does PFQ gating improve over ungated replacement results?

---

## Phase 3 — Bypass + victim buffer

**Goal**: Reuse the same history table and the same index key to drive a bypass decision (DoA → skip LLC fill). Add a small victim buffer to catch false-positive bypasses. Only include in the paper if it adds meaningful speedup on top of replacement alone.

- [ ] Implement bypass: DoA classification → skip LLC insert, serve from DRAM
- [ ] Add victim buffer (4–16 entries) in LLC to absorb false positives
- [ ] Track bypass accuracy: bypasses issued vs. corrections (victim buffer hits)
- [ ] Evaluate bypass + replacement jointly on all suites
- [ ] Try small improvements: bypass confidence threshold, per-PC correction counter

**Decision gate**: Does bypass improve IPC by a meaningful margin? If not, drop it from the paper.

---

## Phase 4 — Set sampling to shrink hardware cost

**Goal**: Instead of tracking all LLC/STLB sets, monitor only a small random sample of sets to estimate the liveness distribution. This drastically reduces the history table's data requirement and makes the hardware proposal more credible.

- [ ] Implement set-sampled observation: only update history table for fills from monitored sets
- [ ] Evaluate: how small a sample suffices before accuracy degrades?
- [ ] Report final hardware cost (SRAM bits) with and without sampling

**Decision gate**: Does set sampling preserve accuracy at a fraction of the storage?

---

## Phase 5 — Write the paper

- [ ] Motivation: per-PC liveness characterization, predictability vs. workload class
- [ ] Design: history table, PFQ filter, indexing dimension choice
- [ ] Replacement results: SRRIP-Live across all suites, joint LLC+STLB
- [ ] Bypass results (if Phase 3 passed its gate)
- [ ] Hardware overhead: area, SRAM cost, set-sampling reduction
- [ ] Future work: online threshold adaptation, prefetcher guidance

---

## Parked / out of scope

- **Prefetcher guidance**: unclear implementation path; out of scope.
- **Online threshold adaptation**: empirical thresholds are defensible if they generalise; leave for future work.
- **Rate-based classifier**: more hardware cost, unclear payoff over simple dead count.
- **Merged LLC/STLB history table**: shelved — only 44.6% PC overlap.
- **IPV-Live for ML**: IPV fails at −10% for ML regardless of predictor quality; SRRIP-Live is the safe policy.

---

## Current branches

- `bypass` — main scoring mode experiments; mode5_recal selected as winner
- `hist-repl-policy` — weighted replacement policy for bounded HistTable; lifespan tracking; commit `575f4e7`
- `addr-hist` — address-based history table (REPL_HIST_MODE=addr), experiments complete
- `merged-history-table` — shelved
- Next: `pfq-gating` for Phase 2, `bypass` for Phase 3
