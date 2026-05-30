# 004 — LFU ablation and history table size sweep

**Date**: 2026-05-28
**Branch**: bypass-predictor-reevaluation
**Commit**: ce965b5b8310 (jobs submitted from this state)
**Jobs**: 1403458–1403469  (540 tasks, `qmm_lfu_study_20260528`)

---

## Motivation

Experiment 003 showed LFU outperforming LRU and SRRIP, but the results were
confounded: pHIST structure changed simultaneously (2D VPN×PC → 1D PC-only).
This experiment isolates the two effects and asks how much capacity each table
actually needs.

---

## Questions this experiment is designed to answer

**Ablation (Group 1)**

1. Does LFU in pHIST improve on the old fold-XOR pHIST for dpPred alone?
   Compare: `lfu_dppred` vs exp 001 `dppred_only` (+2.12% / +0.60%).

2. How much does cbPred with LFU bHIST add on top of LFU dpPred?
   Compare: `lfu_full` vs `lfu_dppred`.

3. What is the combined benefit of LFU in both tables over the fold-XOR baseline?
   Compare: `lfu_full` vs exp 001 full predictor (+7.56% / +0.95%).

**pHIST size sweep (Group 2, bHIST fixed at 4096 LFU)**

4. How sensitive is performance to pHIST capacity? At what size does
   shrinking the number of tracked PCs hurt dpPred?

5. Is the default 1024-entry pHIST overprovisioned for QMM workloads,
   or is the full capacity being used?

**bHIST size sweep (Group 3, pHIST fixed at 1024 LFU)**

6. How sensitive is performance to bHIST capacity? Does bHIST degrade
   faster than pHIST as capacity is reduced (expected, given the wider
   address key space)?

7. What is the minimum bHIST capacity that retains most of the performance
   benefit, and does LFU's eviction policy allow it to stay useful at
   smaller sizes?

**Cross-cutting**

8. If performance is flat across size reductions, the table is overprovisioned
   and the promotion buffer (idea 001) may allow us to shrink further by
   filtering noise before entries reach the main table.
   If performance drops sharply, capacity is the binding constraint and
   the promotion buffer alone won't help — we need both filtering and
   sufficient capacity.

---

## Configs

All configs: QMM 45 traces, 1MB LLC, LRU replacement policy, HIST_REPL=lfu,
50M warmup + 100M simulation instructions.

| Config | DPPRED | CBPRED | THD | PHIST_WAYS | BHIST_WAYS |
|---|---|---|---|---|---|
| lfu_dppred_opt | 1 | 0 | (0,0) | 1024 | 4096 |
| lfu_dppred_default | 1 | 0 | (6,6) | 1024 | 4096 |
| lfu_full_opt | 1 | 1 | (0,0) | 1024 | 4096 |
| lfu_full_default | 1 | 1 | (6,6) | 1024 | 4096 |
| phist_512 | 1 | 1 | (0,0) | 512 | 4096 |
| phist_256 | 1 | 1 | (0,0) | 256 | 4096 |
| phist_128 | 1 | 1 | (0,0) | 128 | 4096 |
| bhist_2048 | 1 | 1 | (0,0) | 1024 | 2048 |
| bhist_1024 | 1 | 1 | (0,0) | 1024 | 1024 |
| bhist_512 | 1 | 1 | (0,0) | 1024 | 512 |
| bhist_256 | 1 | 1 | (0,0) | 1024 | 256 |
| bhist_128 | 1 | 1 | (0,0) | 1024 | 128 |

**Note**: the non-varied table in each size sweep is held at its default
capacity and also uses LFU — there is no fold-XOR control held fixed.
Both tables use LFU throughout.

---

## Results

All 45 QMM traces, 1MB LLC, vs `qmm_1mb_20260527_1543/baseline` (no predictor).

### Group 1 — Ablation

| Config | Geomean speedup | Delta vs prior |
|---|---|---|
| exp001 dppred_only (fold-XOR, (6,6)) | +0.60% | — |
| exp001 optimal_bypass (fold-XOR, (0,0)) | +7.56% | — |
| exp001 default_bypass (fold-XOR, (6,6)) | +0.95% | — |
| lfu_dppred_opt (LFU, (0,0)) | +3.51% | +2.91pp vs exp001 dppred_only |
| lfu_dppred_default (LFU, (6,6)) | +4.26% | +3.66pp vs exp001 dppred_only |
| lfu_full_opt (LFU, (0,0)) | +7.27% | +3.76pp vs lfu_dppred_opt |
| lfu_full_default (LFU, (6,6)) | +6.12% | +1.86pp vs lfu_dppred_default |

### Group 2 — pHIST size sweep (bHIST fixed at 4096 LFU, both DPPRED+CBPRED on, THD=(0,0))

| pHIST ways | Geomean speedup | Delta vs 1024 |
|---|---|---|
| 1024 (reference) | +7.27% | — |
| 512 | +4.54% | −2.73pp |
| 256 | +3.74% | −3.53pp |
| 128 | +2.73% | −4.54pp |

### Group 3 — bHIST size sweep (pHIST fixed at 1024 LFU, both DPPRED+CBPRED on, THD=(0,0))

| bHIST ways | Geomean speedup | Delta vs 4096 |
|---|---|---|
| 4096 (reference) | +7.27% | — |
| 2048 | +6.53% | −0.74pp |
| 1024 | +5.49% | −1.78pp |
| 512 | +4.64% | −2.63pp |
| 256 | +4.25% | −3.02pp |
| 128 | +4.09% | −3.18pp |

---

## Observations

### Q1 — LFU pHIST vs fold-XOR pHIST for dpPred alone

LFU dpPred at (0,0) gives +3.51% vs fold-XOR dpPred at (6,6) giving +0.60% —
a +2.91pp lift. More strikingly, **LFU dpPred at (6,6) outperforms (0,0)**
(+4.26% vs +3.51%). With fold-XOR, (0,0) was required to extract meaningful
dpPred speedup because aliasing blurred confidence across many PCs, so
thresholding was counter-productive. With LFU, the confidence counters
accumulate on clean PC-indexed entries, and the (6,6) threshold acts as a noise
filter that improves precision: entries with count ≤ 6 are genuinely uncertain
and suppressing them helps.

### Q2 — cbPred increment on top of LFU dpPred

Adding cbPred (bHIST, 4096 LFU entries) on top of LFU dpPred adds **+3.76pp at
(0,0)** and +1.86pp at (6,6). The asymmetry is expected: at (0,0) cbPred fires
aggressively on any positive bHIST entry; at (6,6) both pHIST and bHIST must
accumulate 6 confirmations before firing, so cbPred is limited to its most
confident bypasses only.

### Q3 — LFU full predictor vs fold-XOR full predictor

At (0,0): LFU +7.27% vs fold-XOR +7.56% — essentially a tie (−0.28pp). The
bounded LFU tables (1024 pHIST + 4096 bHIST) match the performance of the
unbounded fold-XOR maps at the optimal threshold.

At (6,6): LFU +6.12% vs fold-XOR +0.95% — **+5.17pp improvement**. This is the
headline result of the experiment. Aliasing in the fold-XOR maps caused counter
interference that prevented most entries from reaching the (6,6) threshold. The
LFU tables, with unique per-PC and per-address entries and frequency-based
eviction, accumulate clean confidence and make the default threshold practical
for the first time.

### Q4–Q5 — pHIST size sensitivity

pHIST is highly capacity-sensitive. Going from 1024→512 entries costs −2.73pp,
and −4.54pp at 128. The degradation is steep because pHIST controls not only
dpPred bypass rate but also the PFQ fill rate — a smaller pHIST means fewer PFQ
pushes, which starves cbPred's PFQ gate as well. **1024 entries is not
overprovisioned**: the table is actively used across QMM workloads, and
increasing it further may yield additional benefit.

### Q6–Q7 — bHIST size sensitivity and minimum viable capacity

bHIST degrades more gracefully than pHIST. At 128 entries (32× smaller than
the 4096 default) the geomean is +4.09%, compared to +3.51% from dpPred alone —
so **even 128 bHIST entries provide +0.58pp of cbPred benefit**. The degradation
curve flattens sharply below 256 entries (~+4.25%), suggesting a floor near the
dpPred-only level. LFU preferentially retains the most frequently dead block
addresses (from the highest-traffic pages), which dominate bypass decisions and
fit in even a small table.

### Q8 — Promotion buffer implications

pHIST shows a sharp cliff: 1024 is not overprovisioned, so a promotion buffer
cannot recover performance by allowing a smaller main table. For bHIST, however,
the long tail of diminishing returns below 1024 entries is precisely the regime
where a promotion buffer could help: entries that survive warmup in a small
staging buffer before entering the main LFU table would reduce the rate at which
fresh (uncertain) entries displace confirmed dead addresses. **The promotion
buffer is worth implementing for bHIST specifically.**
