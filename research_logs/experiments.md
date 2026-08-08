# Experiment log

## Run

| date | experiment | result |
|---|---|---|
| 07-24 | Per-level guidance/bypass3/hybrid, all 6 non-LLC levels, 251 traces | Bypass wins at L2C/L1D only; hurts at L1I and all TLBs |
| 07-24 | L2C hybrid, 251 traces | guidance +3.69%, bypass3 +6.94%, hybrid +8.11% (best level in hierarchy) |
| 07-24 | L1D | guidance −0.06%, bypass3 +5.30%, hybrid +5.24% |
| 07-24 | LLC hybrid bypass threshold 2–10 vs thd1 | flat, ±0.3%; thd1 near-optimal |
| 07-24 | DRAM mechanism analysis (ligra, threshold sweep) | Bypass cuts writeback traffic ~99%, read row-buffer hit rate 31.6%→55.4%; saturates below ~5% write-fraction |
| 07-25 | CHAR (PACT'12) reproduction, paired CHAR-on/off, 251 traces | dpc3 final: +0.52% IPC, 2.28% MPKI vs paper's +3.8%/5.8%; google/ligra barely respond |

## Planned

| experiment | rationale |
|---|---|
| L2C guidance threshold sweep, THD_DOA ∈ {2,4,6,8} | running; find optimal guidance threshold |
| L2C bypass threshold sweep from optimal guidance threshold upward | step size TBD from curve shape |
| L2C bypass-alone threshold study | guard against greedy search missing a better joint setting |
| Split instruction/data threshold study, L2C + LLC | classifier ready on `instr-data-split`; test whether optimal thresholds differ by class, and whether instruction bypass responds differently in DRAM (instruction lines are never written back) |
| L2C dead prior, `PC_COUNTER_INIT=1`, `THD_DOA=1`, `BYPASS_THD` ∈ {2,3} | 82% of L2C evictions are DoA, so an unseen PC should default dead, not alive; a live eviction still resets to 0 and keeps MRU protection, so only the never-seen case changes |
| CHAR-PC | closest prior art to our per-PC design; paper got 12.4% miss reduction vs CHAR's 5.8% but rejected it on complexity |
| Hierarchy-wide bypass driven by L1D DoA PCs | L1D sees the DoA signal earliest; if a PC is dead there it may be dead everywhere, so bypass it at L1D, L2C and LLC from one predictor. Cross-level plumbing exists on `llc-l2c-cross-level-bypass` (`CROSS_LEVEL_SOURCE`/`CROSS_LEVEL_TARGET`), but needs an "all levels" target and re-basing off `main` |
