# Experiment Tracker
_Last updated: 2026-06-11_

This document is the single source of truth for what is running, what we want
to learn from it, and how it connects to the paper narrative. Update it whenever
a new batch is submitted or results land.

---

## Narrative thread

The paper claims that **per-PC liveness history** beats prior per-address
approaches for both replacement guidance and bypass prediction. The experiment
sequence builds this claim in three layers:

1. **Replacement guidance alone** (our system, per-PC) — baseline for our contribution
2. **Bypass prediction** (our system, per-PC) — the main performance driver
3. **Indexing comparison** (per-address, same algorithm) — shows per-PC is strictly better
4. **Mazumdar comparison** (different algorithm, per-address) — shows we beat the state of the art
5. **LLC+STLB combined** (future) — full system vs full Mazumdar

Each layer needs a srrip baseline, the mechanism under test, and ideally a
breakdown by suite so we can explain *why* one approach wins.

---

## Currently running

### IPV-Live vs plain IPV (for the liveness-contribution figure)
**Label/jids:** gms/gap `ipv_live_vs_base_20260614_2152` (1405924–1405927);
qmm/dpc3/ligra/ml `ipv_live_vs_base_20260614_2154` (1405928–1405935). Aggregate both.
**Configs:** `ipv_base` (SRRIP_LIVE_TARGET=none = plain IPV), `ipv_live`
(SRRIP_LIVE_TARGET=llc = IPV-Live, LLC-only), `SCORING_MODE=5,THD_DOA=6,THD_DEAD=10,BHIST_MODE=pc`,
**unbounded** history table (matches SRRIP-Live `repl_only`). Binary `champsim_ipv_morph`.
**Purpose:** fill the IPV series of `results/plots/live_vs_base.png` (paper Fig. live_vs_base).
SRRIP-Live/SRRIP half already have (bypass_allsuites repl_only/srrip): dpc3 +2.25, gap +2.05,
gms +1.28, ligra +1.53, ml +8.80, qmm +0.99.



### 0. `maz_morph_20260614_1813` + `ours_sizestudy_20260614_1813` (branch maz-morph-unbounded)
**Binary:** `champsim_morph` (uploaded under new name so running cb_po jobs keep using champsim_srrip_live_hrp).
**Morph ladder jids:** gms/gap `maz_morph_20260614_1813` (1405852–1405863);
qmm/dpc3/ligra/ml `maz_morph_20260614_2054` (1405876–1405899). Aggregate BOTH labels.
**Size-study jids:** gms/gap `ours_sizestudy_20260614_1813` (1405864–1405875);
qmm/dpc3/ligra/ml `ours_sizestudy_20260614_2054` (1405900–1405923). Aggregate BOTH labels.
**gms morph validated:** R4 perpc +2.11% == R5 ours +2.11% (exact suite-level convergence);
jump at R3 ungated −0.73% → R4 +2.11% (addr→PC + dead-counter→mode5). R0=R1=+0.69%.
**Baseline:** srrip from `bypass_allsuites_20260610_2312`.

**Morph rungs** (each changes ONE feature; adjacent deltas attribute the win):
- R0 maz_faithful: bounded(4096/1024)+HASHED+PFQ-gated+per-addr (+dppred)
- R1 maz_raw: bounded raw fully-assoc+gated+per-addr (+dppred) [− hash]
- R2 unbounded: +dppred, gated, per-addr [− size limit]
- R3 ungated: unbounded+UNGATED+per-addr, dppred OFF / LLC-only [− PFQ gate]
- R4 perpc: unbounded+ungated+access-PC key+mode5 [addr→PC; converges to ours]
- R5 ours: repl_hist_pc PC/mode5/thd16

**New flags (cache.cc/cache.h):** `MAZ_UNBOUNDED`, `BHIST_HASH`/`PHIST_HASH`
(hash key into log2(ways) bits via fold_xor), `BHIST_SCORING`, `CBPRED_KEY=access_pc`
(key by demand-access PC, ungated, learn every eviction).

**Validation (DPC3 602.gcc, 50M sim):** R4 IPC 0.430354 / 886,137 bypasses ≈ R5
0.430392 / 887,518 (0.01% IPC, 0.16% bypass diff) → access-PC cbPred == ours.
R1 fired 0 bypasses (6 conf hits / 864K queries) → Maz per-addr dead-counter can't bypass.

**Size study:** ours LLC bypass-only, REPL_HIST_LLC_CAP ∈ {0,4096,2048,1024,512,256}
(floor 256), REPL_HIST_BUF_CAP=0. Find the knee per suite; expect QMM (max ~35K)
to drop first, DPC3 (~5K) next, GAP/GMS/Ligra/ML hold at 256.



### 1. `addr_indexed_20260611_1806`
**jids:** 1405523–1405540 (18 arrays, 447 tasks)
**Configs:** `repl_only`, `bypass_only_thd16`, `bypass_thd16`
**Key setting:** `REPL_HIST_MODE=addr` — address-indexed HistTable, unbounded,
everything else identical to the PC-indexed runs.
**Baseline reuse:** srrip from `bypass_allsuites_20260610_2312` (same binary,
same traces).

**What we want to learn:**
- Does per-address replacement guidance beat SRRIP, and by how much vs per-PC
  (+3.03% ALL)?
- Does per-address bypass at THD=16 match per-PC bypass (+11.53% bypass_only,
  +12.17% combined)?
- How large does the address-indexed table actually get? (check `repl_hist_pc
  entries` in champsim.out stats — expect orders of magnitude more than per-PC)

**How to evaluate as it comes in:**
1. GAP (9 traces) and GMS (11 traces) finish first — analyze those immediately.
2. Compare `addr_repl_only` vs `pc_repl_only` per suite.
3. Compare `addr_bypass_thd16` vs `pc_bypass_thd16` per suite.
4. Note table size from stats output (entries used in unbounded mode).

**Connects to:**
- Past: PC-indexed results in `bypass_allsuites_20260610_2312` (the comparison point)
- Paper: Section 6 (LLC Bypass Prediction) — will add a table showing per-PC vs
  per-address for the three key configs
- Upcoming: once we see per-address numbers, decide whether a size-matched
  comparison (both bounded at same entries) is needed

---

### 2. `maz_comparison_20260611_1655` (+ relaunch)
**jids:** 1405511–1405522 (12 arrays, 298 tasks original) +
         1405559–1405565 (7 arrays, 56 tasks relaunch for missing stragglers)
**Configs:** `cbpred_dppred` (CBPRED=1+DPPRED=1), `dppred_only` (DPPRED=1)
**Key settings:** No BHIST_MODE, no SCORING_MODE — uses Mazumdar's original
address-indexed bhist with default BCONF_THD=6. cbpred_dppred runs both LLC
and STLB predictors together, as in the original paper.
**Baseline reuse:** srrip from `bypass_allsuites_20260610_2312`.
**Relaunch:** 56 missing traces re-submitted 2026-06-11 (same RUN_LABEL, results
land in the same directory). Missing suites: DPC3 (3+4), GAP (1), Ligra (7+11),
ML (19+11). QMM and GMS were fully complete.

**What we want to learn:**
- What speedup does Mazumdar's full system (cbpred+dppred) give on our 148 traces?
- What does dppred alone contribute at the STLB level?
- How does cbpred_dppred compare to our per-PC combined bypass+replacement
  (+12.17% ALL at THD=16)?

**How to evaluate as it comes in:**
1. Same per-suite analysis as addr_indexed.
2. Compare `cbpred_dppred` vs our `bypass_thd16` — the headline comparison.
3. Compare `dppred_only` vs our future `stlb_bypass_only` (pending code).

**Connects to:**
- Past: Old Mazumdar runs in `maz_pc_bypass_20260522_0101` etc. used smaller
  trace sets — those numbers are NOT comparable; this is the canonical run.
- Paper: Will become the "vs state of the art" comparison row in the results table.
- Upcoming: Once STLB liveness bypass is implemented, we run our full LLC+STLB
  system and compare directly against cbpred_dppred.

---

### 3. `maz_equiv_*` — Mazumdar at per-suite equivalent thresholds

Two runs provide the per-suite equivalent comparison for Mazumdar:

**`maz_equiv_20260612_1020`** (jids 1405602–1405613, ~298 tasks, all 6 suites)
- BCONF_THD=7, PCONF_THD=1 (equivalent to our bypass_thd=16: 8 consecutive DoA evictions)
- Correct for QMM, GAP, GMS, ML (all have optimal bypass_thd=16)
- NOT correct for DPC3 (opt=8) or Ligra (opt=32)

**`maz_equiv_persuit_20260612_1036`** (jids 1405614–1405617, 106 tasks)
- DPC3: BCONF_THD=1, PCONF_THD=1 (2 evictions ↔ our bypass_thd=8)
- Ligra: BCONF_THD=23, PCONF_THD=1 (24 evictions ↔ our bypass_thd=32)
- Both cbpred_dppred and dppred_only configs

**Derivation (SCORING_MODE=5, thd_doa=6):**
- bypass_thd=8:  2 evictions → BCONF_THD=1  (eviction1: δ=5→score=5, eviction2: δ=5→10≥8)
- bypass_thd=16: 8 evictions → BCONF_THD=7  (need δ=1 phase; DoA state δ=1 per eviction after score=10)
- bypass_thd=32: 24 evictions → BCONF_THD=23

**Per-suite optimal LLC bypass_thd:**
| Suite | opt bypass_thd | BCONF_THD | PCONF_THD | Source run |
|-------|---------------|-----------|-----------|------------|
| QMM   | 16            | 7         | 1         | maz_equiv_20260612_1020 |
| DPC3  | 8             | 1         | 1         | maz_equiv_persuit_20260612_1036 |
| GAP   | 16            | 7         | 1         | maz_equiv_20260612_1020 |
| GMS   | 16            | 7         | 1         | maz_equiv_20260612_1020 |
| Ligra | 32            | 23        | 1         | maz_equiv_persuit_20260612_1036 |
| ML    | 16            | 7         | 1         | maz_equiv_20260612_1020 |

**What we want to learn:**
- Does Mazumdar cbpred_dppred at an equivalent activation threshold match or beat
  our per-PC LLC+STLB system per suite?
- With fair threshold calibration, how much of the gap is algorithm (PC vs addr)
  vs threshold mismatch?

**Connects to:** Paper Section 6.5 "Comparison with prior work"; will replace the
uniform-threshold maz_comparison rows for DPC3 and Ligra.

---

### 4. `stlb_bypass_allsuites_20260612_0710`
**jids:** 1405566–1405577 (12 arrays, 298 tasks)
**Configs:** `stlb_bypass_only_thd16`, `llc_stlb_bypass_thd16`
**Key settings:**
- stlb_bypass_only: `STLB_LIVENESS_BYPASS=1,STLB_BYPASS_THD=16` (LLC bypass disabled)
- llc_stlb_bypass: `LIVENESS_BYPASS=1,BYPASS_THD=16,STLB_LIVENESS_BYPASS=1,STLB_BYPASS_THD=16`
Both use `SCORING_MODE=5,THD_DEAD=10,THD_DOA=6`.
**Baseline reuse:** srrip and bypass_thd16 from `bypass_allsuites_20260610_2312`.
**Mazumdar comparison:** dppred_only and cbpred_dppred from `maz_comparison_20260611_1655`.

**What we want to learn:**
- stlb_bypass_only vs dppred_only: does our PC-indexed STLB predictor beat Mazumdar's address-indexed STLB predictor?
- llc_stlb_bypass vs cbpred_dppred: does our full system (LLC+STLB) beat Mazumdar's full system?
- STLB-only contribution: difference between llc_stlb_bypass and LLC-only bypass (bypass_thd16 from prior run)

**Debug confirmed (srv_21, QMM):**
- LLC bypass only: IPC=2.07574
- LLC+STLB bypass (THD=16): IPC=2.14071 (+3.1%), 200,661 STLB bypasses + 81,951 LLC bypasses

**How to evaluate as it comes in:**
1. GAP (9 traces) and GMS (11 traces) finish first — quick sanity check
2. Compare stlb_bypass_only vs srrip (STLB-only contribution)
3. Compare llc_stlb_bypass vs bypass_thd16 (STLB marginal benefit over LLC-only)
4. Full comparison vs Mazumdar once maz_comparison relaunch is complete

**Connects to:**
- Past: `bypass_allsuites_20260610_2312` provides LLC-only baseline
- Paper: Section 6.5 "Comparison with prior work" — adds our STLB numbers vs Mazumdar
- Upcoming: Per-PC reset mechanism (BYPASS_PC_RESET_PERIOD) for lock-in — not yet submitted

---

## Recently completed (results on disk, analysis done)

### 3. `bypass_allsuites_20260610_2312`
**Configs:** `srrip`, `repl_only`, `bypass_thd4/8/16/32`
**Result:** THD=16 wins at +12.17% ALL gmean vs SRRIP. DPC3 +22.6%, Ligra
+34.9% (DRAM row-buffer effect). THD=4 risks lock-in on QMM.
**Summaries:** `repl_only_summary.txt`, `bypass_thd{4,8,16,32}_summary.txt`
**In paper:** Table~\ref{tab:repl_only}, Table~\ref{tab:bypass_sweep} (Section 6)

### 4. `bypass_only_allsuites_20260611_1200`
**Configs:** `bypass_only_thd4/8/16/32`
**Result:** Synergy analysis complete (all 6 suites, THD=16, 147 matched traces).
bypass_only=+11.53%, combined=+12.17%, repl contributes only +0.64pp on top of
bypass. Ligra THD=16 is the one case of positive synergy (+0.82%). ML synergy
strongly negative (−8.97%): bypass captures ML's near-total DoA population.
**Summaries:** `bypass_only_thd{4,8,16,32}_summary.txt`
**In paper:** Table~\ref{tab:bypass_synergy} (Section 6.4)
**Note:** QMM thd4 (32/45) and thd8 (22/45) still have stragglers — long server
traces. They do not affect the main story; the 45/45 thd16/32 data is sufficient.

### 5. `scoring_modes_20260608_2350`
**Result:** Mode 5 (decoupled, δ=5/3/1) wins on 4/6 suites, +3.4% gmean over
LRU on 31 targeted traces. Mode 3 slightly wins on GAP and QMM.
**In paper:** Table~\ref{tab:scoring_modes} (Section 5.2)

---

## Pending experiments (not yet submitted)

### A. Size study rerun
**Why needed:** Bounded HistTable runs in `size_allsuites_20260610_2312` all ran
with scoring_mode=2 (bug: `repl_hist_pc = HistTable(...)` at cache.cc:340
overwrote the scoring mode set at line 319). Fixed binary is on the cluster.
**What:** 40 arrays, 730 tasks — lfu_c*/tier_c* configs for DPC3(35), GAP(9),
GMS(11), Ligra(18). Ref and srrip rows from the old run are still valid.
**When:** Submit overnight when cluster is quiet.
**Label pattern:** `size_allsuites_rerun_YYYYMMDD_HHMM`

### B. STLB liveness bypass (code done; debug in progress 2026-06-11)
**What was done:** Added `STLB_LIVENESS_BYPASS` and `STLB_BYPASS_THD` env vars.
STLB bypass condition: `stlb_liveness_bypass && NAME == "cpu0_STLB"` + classify
against STLB's own `repl_hist_pc` (which is already populated from evictions).
Also added per-PC bypass continuation check: `BYPASS_PC_RESET_PERIOD` resets a
specific PC's score after that PC has bypassed N times without eviction feedback.
Key fix needed: STLB fills are LOAD type (not TRANSLATION) — type guard removed.
Binary: `champsim_srrip_live_hrp` (updated locally; needs cluster transfer after
maz_comparison relaunch finishes using the binary).
**Debug:** 1-trace QMM test with STLB_BYPASS_THD=6 → should see
`cpu0_STLB LIVENESS_BYPASSES: N` in output.
**Experiments after debug confirms firing:**
- `stlb_bypass_only_thd16`: LIVENESS_BYPASS=0, STLB_LIVENESS_BYPASS=1, BYPASS_THD=16
  (compare vs Mazumdar dppred_only)
- `llc_stlb_bypass_thd16`: LIVENESS_BYPASS=1, STLB_LIVENESS_BYPASS=1, BYPASS_THD=16
  (compare vs Mazumdar cbpred_dppred)
- Include per-PC reset: BYPASS_PC_RESET_PERIOD=N (sweep: 50, 200, 500)
**When:** After binary is updated on cluster (post maz_comparison relaunch).

### C. BYPASS_FIRE_RESET_PERIOD sweep
**What:** Every N bypass fires, reset all repl_hist_pc scores to prevent
indefinite lock-in. Sweep N ∈ {100, 500, 1000, 5000, 0=disabled}.
**Why:** Lock-in (score freezes once bypass fires) visibly hurts QMM at THD=4.
Understanding the recovery mechanism helps set the right threshold policy.
**When:** After the indexing comparison is done — this is an optimisation pass,
not a baseline comparison.

---

## Analysis checklist for incoming results

When a new experiment label appears on the cluster:

1. **Check completion per suite:** `grep -rl "^CPU 0 cumulative IPC" <dir> | wc -l`
   (file existence ≠ completion)
2. **Verify env vars took effect:** grep one output file for the config echo
   block — check `scoring_mode=`, `Insert mix DoA:`, `liveness_bypasses`
3. **Download only completed suites:** tar only the suites where all configs
   have a final IPC line
4. **Run matched-pair analysis:** require srrip + all experiment configs to have
   valid IPC for a trace before including it in the geomean
5. **Compare per suite first:** fast suites (GAP, GMS) land early; analyze them
   before waiting for QMM/ML
6. **Save summary files:** per-trace IPC/speedup text files in the result dir,
   following the pattern in `bypass_allsuites_20260610_2312/`
7. **Update this document** with the result and paper status

---

## Job ID reference

| Label | jids | Tasks | Status |
|---|---|---|---|
| bypass_allsuites_20260610_2312 | — | 894 | done |
| bypass_only_allsuites_20260611_1200 | 1405487–1405510 | 596 | mostly done (QMM thd4/8 stragglers) |
| maz_comparison_20260611_1655 | 1405511–1405522 | 298 | done (QMM/GMS), running (DPC3/GAP/Ligra/ML) |
| maz_comparison relaunch | 1405559–1405565 | 56 | running (missing stragglers) |
| addr_indexed_20260611_1806 | 1405523–1405540 | 447 | done |
| bypass_reset_sweep_20260611_1840 | 1405541–1405558 | 447 | CANCELLED — global reset is wrong approach |
| maz_comparison relaunch | 1405559–1405565 | 56 | running |
| stlb_bypass_allsuites_20260612_0710 | 1405566–1405577 | 298 | running |
| maz_equiv_20260612_1020 (BCONF=7, all suites) | 1405602–1405613 | ~298 | running |
| maz_equiv_persuit_20260612_1036 (DPC3 BCONF=1, Ligra BCONF=23) | 1405614–1405617 | 106 | running |
| recheck_smallsuites_20260612_1418 (GAP/GMS + Ligra × backoff/fixed; ML cancelled) | 1405618–1405625 | ~96 | running |
| bypass_noguide_allsuites_20260612_1606 (matched bypass-only, no repl guidance) | 1405626–1405631 | 149 | running |
| size_allsuites_rerun | TBD | ~730 | pending (overnight) |

## Mazumdar fairness: matched bypass-only run
The headline `ours LLC+STLB` (+13%) used SRRIP-Live replacement guidance (SRRIP_LIVE_TARGET=llc,
scoring_mode=5) — i.e. bypass + replacement, vs Mazumdar's bypass-only predictor. Replacement
adds only +0.64pp (synergy study), so bypass dominates, but for a clean bypass-vs-bypass the
matched run `bypass_noguide_allsuites_20260612_1606` repeats our LLC+STLB bypass with
SRRIP_LIVE_TARGET OMITTED (plain SRRIP replacement, Unguided=100%). Compare vs maz cbpred_dppred.
Mazumdar at equivalent threshold (maz_equiv) stays flat (~+0.2-0.6%) → gap is indexing, not threshold.

## Set-sampled predictor — branch `set-sampling` (off bypass-recheck), binary `champsim_srrip_live_hrp_sample`

Train the per-PC history on only a few fixed sampler sets (set_index % period == 0,
period = NUM_SET/count), but PREDICT (bypass) + replacement-guide for EVERY set.
Env: LLC_SAMPLE_SETS / STLB_SAMPLE_SETS (set COUNT; unset → all sets = full training).
Gate is on the eviction update() only; classify/guidance unchanged. Question: how
much performance do we lose vs full-set training?

**Cluster: sample_allsuites_20260613_1935** (jids 1405714-1405731, 447 tasks, 18 arrays)
Coarse 3-config/suite (full, per-level 64/16, 16/4). Superseded by the convergence sweep below.

**sample_conv_allsuites_20260613_2244 — CANCELLED (flawed)**: ran pre-fix binary
(sampler sets NOT policy-free + shared count). Cancelled with the coarse s_* eval.

**CORRECTED: sample_pf_allsuites_20260613_2330** (36 arrays, 894 tasks, binary
champsim_srrip_live_hrp_sample2). POLICY-FREE sampler sets (sampler sets don't bypass
→ observe full eviction stream → clean training; bypass only on non-sampler sets).
Full system. LLC-isolated: LLC_SAMPLE_SETS {4,16,64,256,1024} → full, STLB full-trained.
srv_128 local (bypass-only): policy-free curve is FLAT ~−1% with sweet spot ~256 sets
(−0.94%); does NOT converge to 0 because sampler sets forgo bypass (permanent coverage
cost) — the correct sampler behavior (the broken version spuriously hit 0%).
Residual: guidance still applies on sampler sets (minor 2nd-order bias; guidance is
near-inert when bypass is on). STLB-isolated sweep can follow.

**srv_128 (QMM) local curve — converges SLOWLY:** −4.75%@1, −3.43%@16, −2.61%@64,
−0.48%@256, −0.15%@1024 sets. Need ~256 sets (1/8 of LLC) for <0.5% loss. QMM has high
PC diversity (full table 10794 entries) → worst case for sampling. Streaming/graph suites
(few hot PCs) may converge much faster — that's what the all-suites sweep tests.

## Mazumdar→ours BRIDGE: cbPred indexing ablation — branch `stlb-llc-propagation`

Goal: incrementally morph Mazumdar's cbPred into our predictor to attribute the gap.
Step 1 = indexing granularity (all gated, BCONF=6, vs SRRIP):
- flat: per-ADDRESS bhist (Mazumdar default) = maz_thd6/cbpred_dppred (~+0.07% ALL)
- pc: per-(PC,address) PCPartitionedTable = cbpred_idx_gate/pc_gated (~+0.07% ALL — flat!)
- pconly: per-PC AGGREGATE (BHIST_MODE=pconly) = cbpred_pconly_20260614_1142 (NEW, 6 arrays)

KEY insight (verified): Mazumdar "per-PC" (pc mode) is really per-(PC,ADDRESS) — needs each
address seen dead, can't generalize to fresh addresses → flat on streaming. pconly aggregates
per-PC like ours → generalizes. srv_128 20M: pconly 306 LLC bypasses vs flat 4 (per-addr
sparsity: 470 PFQ hits, only 4 bypasses). Tests whether PC-aggregation lifts cbPred toward ours.
Next bridge steps (if pconly helps): swap dead-counter scoring → 3-class liveness; ungate; own-PC.
Anchor: Mazumdar bypass ~+0.07% ALL vs ours +13.56% (Ligra +35%, ML +11.8%).

## STLB→LLC propagation: gate granularity (PFN vs PC) — branch `stlb-llc-propagation`, binary `champsim_srrip_live_hrp_propgate`

Cross-level dead signal can gate the LLC per-PC predictor by PAGE (PFN, default) or
INSTRUCTION (PC, PROP_GATE=pc). PC-gate: STLB exports the set of PCs whose translations
it bypassed (stlb_dead_pcs); an LLC block is gated-in iff its own PC is in that set,
indexed by own PC. Tests whether STLB↔LLC deadness aligns better by page or by PC.

**srv_128 (QMM, bypass-only, vs noprop):** noprop 0 (72144 byp) | PFN-gate/prop-PC −1.01%
(19148) | PFN-gate/own-PC −0.97% (11505) | PC-gate/own-PC −1.14% (5481). PC-gate fires
(5M=0 was short-run); it's MORE restrictive (fewer PCs STLB-dead than pages) → worst on
QMM (coverage loss). Real test = Ligra (where PFN-gate helped +3.04%): does PC-gate
capture the alignment better/worse?

**Cluster: propgate_allsuites_20260614_0147** (24 arrays, 596 tasks)
4-way (noprop / PFN-gate-propPC / PFN-gate-ownPC / PC-gate-ownPC) × 6 suites, bypass-only.

## STLB→LLC PC propagation — branch `stlb-llc-propagation`, binary `champsim_srrip_live_hrp_prop`

When STLB liveness-bypasses, record PFN→(STLB PC) in an unbounded `prop_map` (idealized
oracle). LLC bypass predictor uses it. 4 versions (env on champsim_srrip_live_hrp_prop):
- noprop: own-PC LLC predictor (baseline)
- A (STLB_LLC_PROP=1): gate by PFN hit + index by STLB PC (Mazumdar-like cross-level)
- B (+STLB_LLC_PROP_HYBRID=1): no gate; STLB PC on propagated pages, own PC otherwise
- D (+STLB_LLC_PROP_OWNPC=1): gate by PFN hit + index by OWN PC (isolate gate from index)
All bypass-only (SRRIP_LIVE_TARGET=none). prop_pc stored on BLOCK (separate from cbPred dp_pc),
frozen at fill, used for eviction update (consistency).

**srv_128 (QMM) factorial — propagation does NOT help (noprop best):**
- noprop +0% (72144 LLC byp) | A −1.01% (19148) | B −0.22% (76612) | D −0.97% (11505)
- Gate hurts (D vs noprop −0.97%): STLB-dead pages ⊊ LLC-dead blocks → coverage collapse.
- STLB PC ≈ own PC as index (A≈D): propagated PC adds nothing.
- QMM is the hardest case (strong own-PC predictor, bypass-friendly).

**Cluster: prop_smallsuites_20260613_1837** (jids 1405690-1405701, 152 tasks, 12 arrays)
noprop/A/B/D on GAP/GMS/Ligra. Does propagation help where own-PC predictor is weaker?

## Bypass shadow (serve-and-reinsert) — branch `bypass-recheck`, binary `champsim_srrip_live_hrp_shadow`

Evidence-driven lock-in fix, replacing the scheduled probe. On a liveness bypass,
record the block tag+data in a small shadow (per-level size). On a re-reference
(confirmed bypass mistake): erase the offending PC's history entry AND recover the
block. STLB serves the stored translation + reinserts (skips PTW — translations
stable). LLC returns false → miss refetches fresh + reinserts (no stale-data serve).
Env: LLC_BYPASS_SHADOW_SIZE / STLB_BYPASS_SHADOW_SIZE (fallback BYPASS_SHADOW_SIZE).
Stat: LIVENESS_BYPASS_SHADOW_HITS. History table stays UNBOUNDED (shadow ≠ hist table).

**srv_128 (QMM) local grid — STLB size is the binding constraint, must be tiny:**
- LLC=16/STLB=2 → +0.36% (best); LLC=8/STLB=2 +0.35%; LLC=2/STLB=2 +0.34%
- LLC=32/STLB=2 +0.28%; LLC=64/STLB=2 +0.20% (LLC erodes slowly past 16)
- ANY STLB>=16 → negative (-0.42 to -0.50%) regardless of LLC
- Net POSITIVE on QMM (cost case) where probe (-1.05%) and penalize-only (-0.1 to -2.9%) lost.

**Cluster: shadow_allsuites_20260613_0928** (jids 1405648-1405659, 298 tasks, 12 arrays)
Configs: shadow_llc16_stlb2, shadow_llc32_stlb2 (STLB locked at 2, LLC sensitivity).
Compare vs base stlb_bypass_allsuites_20260612_0733/{suite}/llc_stlb_bypass_thd6.
KEY question: does it help Ligra (lock-in benefit) while staying >=0 on QMM (cost)?

## Bypass recheck (probe) — branch `bypass-recheck`, binary `champsim_srrip_live_hrp_recheck`

Periodic probe to break per-PC bypass lock-in. Env: BYPASS_RECHECK_MODE=fixed|backoff,
BYPASS_RECHECK_INTERVAL (base, default 32), BYPASS_RECHECK_CAP (backoff max, default 256).
Reports LIVENESS_PROBES stat. Base config reused from stlb_bypass_allsuites_20260612_0733
llc_stlb_bypass_thd6 (LLC THD16 + STLB THD6); new binary with recheck OFF is bit-identical
(verified srv_128 → 2.170 exact). srv_128 local: backoff −0.46%, fixed −1.36% (stable-DoA
trace, no lock-in to recover → pure cost; backoff < fixed as designed).
recheck_smallsuites: GAP(9)+GMS(11)+ML(31), backoff+fixed, compare vs base above.
NOTE: ML has 31 traces (medium, not small) — GAP/GMS land first.
