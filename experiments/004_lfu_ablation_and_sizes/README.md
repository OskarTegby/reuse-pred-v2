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

*(to be filled in when jobs complete)*

---

## Observations

*(to be filled in when jobs complete)*
