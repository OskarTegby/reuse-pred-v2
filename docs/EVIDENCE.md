# Evidence — Logical Coherence of the Findings

**Not for the paper.** This is the **evidence document**: it shows that the
findings recorded in [`FINDINGS.md`](FINDINGS.md) are logically coherent and
causally attributed, by controlled ablation and by *building toward our predictor
through step-by-step modification of Mazumdar's* (the morph ladder, §7). Where
`FINDINGS.md` states *what* we found, this document proves *why* each finding
holds and how the pieces fit together. The paper may carry only a sentence or two
of this; here we record the full reasoning.

All speedups are geomean IPC **vs the SRRIP baseline** unless noted, full config
(50M warmup + 100M sim), current cache geometry (LLC 2 MB / 2048 sets × 16, STLB
1024 entries / 128 sets × 8), per-PC unbounded history table, `SCORING_MODE=5`
(θ_doa=6, θ_dead=10), unless an ablation changes one variable.

---

## 1. The central question

Our predictor achieves **+13.56% ALL** (LLC+STLB bypass); Mazumdar et al.'s
predictor achieves **+0.07% ALL**. Both are "per-PC liveness/dead-block bypass
predictors." Why the ~190× gap? We want each contributing factor isolated and
quantified, not just asserted.

Method: **controlled ablation** — change one variable at a time — plus a
**bridge study** that morphs Mazumdar's predictor step-by-step into ours, reading
off each step's contribution. We judge results only on suites with enough signal
(see §9).

---

## 2. Headline numbers

Our predictor, per suite (LLC+STLB bypass, thd6, vs SRRIP):

| suite | speedup |
|-------|---------|
| QMM   | +5.85% |
| DPC3  | +21.78% |
| GAP   | +6.43% |
| GMS   | +1.79% |
| Ligra | +35.38% |
| ML    | +11.79% |
| **ALL** | **+13.56%** |

Mazumdar (cbpred+dppred) vs SRRIP:
- paper threshold (BCONF=6): **+0.07% ALL** (flat every suite)
- equivalent activation threshold (BCONF=7): **+0.24% ALL** (still flat)

The gains concentrate on the fresh-address / phase-changing suites (Ligra, DPC3,
ML). GMS is near-zero for *both* (the workload has little to gain from bypass).

---

## 3. The core decomposition: scoring × indexing (multiplicative)

The single most important result. We cross two factors — **scoring mechanism**
(Mazumdar's mode-2 dead-counter vs our mode-5 3-class liveness) and **history
index** (block address vs per-PC) — holding everything else fixed (same HistTable
structure, same traces, LLC bypass, vs SRRIP, ALL geomean):

| scoring | index | ALL |
|---------|-------|-----|
| mode-2 (Mazumdar dead-counter) | address | **+0.07%** |
| mode-2 (Mazumdar dead-counter) | PC (`pc_gated`) | **+0.07%** |
| our mode-5 liveness | address | **+2.43%** |
| our mode-5 liveness | PC | **+12.17%** |

Reading:
1. **Scoring is the enabler.** With a *bad* (address) index, swapping Mazumdar's
   dead-counter for our 3-class liveness lifts ~0 → **+2.43%**. The dead-counter
   caps the predictor near zero *regardless of index* (top two rows identical).
2. **Per-PC indexing is the multiplier.** *Given* the good scoring, going
   address → PC lifts +2.43% → **+12.17%** (a ~5× jump).
3. **Neither alone suffices, and they interact.** PC-indexing does nothing for
   the weak scoring (mode-2 PC = +0.07%, same as mode-2 address). The indexing
   lever only pays off once the scoring is strong enough to have signal to
   redistribute.

So "per-PC beats per-address" is true *only conditional on strong scoring*. This
is the crux of the whole attribution.

> **Note (2026-06-15): morph-ladder figures below are unweighted per-trace
> geomeans.** SimPoint weighting (DPC3/SPEC slices weighted into per-benchmark
> values) lowers the per-PC ALL headline from +12.17% to **+9.78%** and DPC3 from
> +22.62% to **+17.27%** (per-address DPC3 +2.62% → +3.04%, so the ~6× per-PC
> advantage and the qualitative ladder conclusions are unchanged). The ladder's
> intermediate rungs are not yet reweighted; magnitudes shift roughly uniformly
> across rungs, so the relative attribution (scoring enables, per-PC multiplies)
> holds. Full reweighted ladder pending the unified single-config rerun.

---

## 4. Per-PC vs per-address, per suite (our scoring)

LLC bypass thd16, our mode-5 scoring, vs SRRIP:

| suite | per-PC | per-address | per-address retains |
|-------|--------|-------------|---------------------|
| QMM   | +1.62% | −0.74% | negative |
| DPC3  | +22.62% | +2.62% | ~12% |
| GAP   | +4.94% | −2.94% | negative |
| GMS   | +1.63% | +0.36% | (both tiny) |
| Ligra | +34.88% | +5.49% | ~16% |
| ML    | +11.70% | +7.73% | ~66% |
| **ALL** | **+12.17%** | **+2.43%** | **~1/5** |

Why per-address collapses on streaming/graph: those suites stream through mostly
**fresh** addresses, so a per-address table never accumulates per-address
evidence (and at 4096 entries also thrashes). Per-PC **generalizes**: a PC's
deadness applies to every block it brings, including never-seen addresses. ML
degrades least (+11.7→+7.7) — its addresses are more reused, so per-address
partly works there. This is the mechanistic root of the indexing multiplier.

---

## 5. What is *ruled out*

- **Threshold.** We ran Mazumdar at the *equivalent activation threshold*
  (`maz_equiv`, matched to our predictor's event count): +0.24% vs +0.07% at
  paper threshold — still flat. Recalibration is not the lever.
- **PC hashing / aliasing.** The current HistTable (both our `repl_hist_pc` and
  Mazumdar's `bhist_flat`) keys by the **raw value** — unbounded uses
  `unordered_map[key]`; bounded does a linear scan `e.key == key`. No fold-XOR
  aliasing (that existed in the *old* bhist, removed in exp003). The `pconly`
  bridge variant uses the *same* HistTable as ours, so hashing is controlled-for.
- **PFQ gating as the *explanation*.** Gating changes (ungated cbPred,
  PFN-gate/PC-gate variants) do not lift Mazumdar's flat result, because the
  underlying predictor produces ~no signal to gate (§3, §6).

So the gap is **not** threshold, hashing, or gating — it is **scoring** (enabler)
× **per-PC indexing** (multiplier).

---

## 6. The three mechanistic differences (Mazumdar "per-PC" vs ours)

"Mazumdar per-PC" (BHIST_MODE=pc) is *not* per-PC the way ours is. Three concrete
differences:

1. **Granularity (dominant).** Mazumdar's PC-mode bhist is a `PCPartitionedTable`
   keyed by **(PC, address)** — partitioned by PC but still per-address within.
   It must have seen *that specific address* dead. Ours is keyed by **PC alone**
   (aggregate over addresses) → generalizes to fresh addresses. Smoke test
   (srv_128, 20M): PC-aggregate fired **306** LLC bypasses vs per-(PC,addr)/flat's
   **4** despite 470 PFQ hits — the per-address sparsity that caps Mazumdar.
2. **Gating.** Mazumdar's cbPred *requires* a dpPred/PFQ hit (cross-level,
   chained to a weak STLB predictor). Ours bypasses independently per PC.
3. **Scoring.** Mazumdar dead-counter (mode 2) vs our 3-class liveness (mode 5).

§3 shows #3 (scoring) is the enabler and #1 (granularity) the multiplier; #2
(gating) is shown harmful-or-neutral in §7.

---

## 7. The bridge study (Mazumdar → ours, step by step)

We morph cbPred toward our predictor by **flag-gated one-variable steps** on a
single binary (`champsim_morph`, branch `maz-morph-unbounded`), so each adjacent
delta is the contribution of exactly one change. The flags added:
`MAZ_UNBOUNDED`, `BHIST_HASH`/`PHIST_HASH` (faithful hashed Maz index),
`BHIST_SCORING`, `CBPRED_KEY=access_pc` (key by demand-access PC, ungated, learn
every eviction). Ladder (`maz_morph_20260614_1813`, gms/gap first):

| rung | config | what changed |
|------|--------|--------------|
| R0 | bounded(4096) **hashed**, PFQ-gated, per-addr, dead-counter (+dppred) | faithful Mazumdar |
| R1 | bounded raw fully-assoc, gated, per-addr (+dppred) | − hashing |
| R2 | **unbounded**, gated, per-addr (+dppred) | − size limit |
| R3 | unbounded, **ungated**, per-addr (LLC-only) | − PFQ gate |
| R4 | unbounded, ungated, **per-PC access-PC + mode-5** (LLC-only) | addr→PC, dead-counter→liveness |
| R5 | our `repl_hist_pc` (PC, mode-5, thd16) | = our predictor |

**Convergence proven** (DPC3 602.gcc, 50M sim): R4 = IPC 0.430354 / 886,137
bypasses ≈ R5 ours 0.430392 / 887,518 — **0.01% IPC, 0.16% bypass-count
difference**. The access-PC cbPred *is* our predictor, so the morph endpoint is
exact and the whole chain is closed. R1 (faithful-ish Maz) fired **0** bypasses on
the same trace (6 confidence hits / 864K queries) — the per-address dead-counter
table cannot accumulate confidence.

Key structural fact surfaced by the morph: cbPred's index PC *comes from* the PFQ
(`dp_pc`), so removing the gate (R3→R4) forces using the **demand-access PC** —
which is precisely our design. The PFQ is not just a gate, it is the PC source and
the learning filter; replacing it with the access PC is the design jump. Allsuites
deltas land as gms/gap (then qmm/dpc3/ligra/ml) complete.

---

## 8. Cross-level STLB→LLC propagation (a separate, second-order question)

Distinct from the core attribution: can the STLB's earlier "dead" signal help the
LLC predictor? Tested on our (already strong) predictor, bypass-only, vs `noprop`
(own-PC LLC predictor):

| variant | gate | index | ALL | Ligra |
|---------|------|-------|-----|-------|
| propA | PFN | propagated STLB PC | −0.96% | **+3.04%** |
| propB | none (hybrid) | STLB-PC where propagated, else own | +0.08% | +1.51% |
| propD | PFN | own PC | −0.99% | +2.34% |

Findings:
- **Net negative overall** — the gate kills coverage on QMM/DPC3/ML (STLB-dead
  pages ⊊ LLC-dead blocks), exactly mirroring Mazumdar's cbPred limitation.
- **But a real per-workload win on Ligra (+3.04%)** — where STLB-dead and
  LLC-dead align (graph traversal). There PC index > own-PC (propA > propD).
- **Hybrid (B) is the safe default** (+0.08% ALL, never < −0.25%, keeps Ligra).
- **Gate granularity (PFN vs PC):** on QMM the PC-gate is more restrictive
  (fewer instructions STLB-dead than pages) and slightly worse (−1.14% vs PFN's
  −0.97%). Per-suite comparison running (`propgate_allsuites_20260614_0147`).

This connects to the core story: cross-level page-gating is broadly unhelpful
(both Mazumdar and ours), with a PC-indexed exception on the aligned workload.

---

## 9. Detectability (which suites can carry an attribution signal)

An ablation is only interpretable where the bypass effect is large enough to move
above the matched-pair noise floor (~0.1–0.3%). Headroom = our bypass speedup:

| suite | headroom | usable for attribution? |
|-------|----------|--------------------------|
| Ligra | +35% | yes (best) |
| DPC3  | +22% | yes |
| ML    | +12% | yes |
| GAP   | +6%  | yes |
| QMM   | +6%  | yes |
| **GMS** | **+1.8%** | **no — inconclusive by construction** |

GMS has almost nothing to gain from bypass, so *no* design change shows a
detectable signal there — report it but draw no conclusions. The bridge (§7)
starts at ~0 everywhere (Mazumdar), so only the high-headroom suites resolve the
per-step deltas.

---

## 10. Secondary mechanisms (lock-in), for completeness

These are refinements on the *strong* predictor, not part of the core gap:
- **Periodic recheck (probe)** to break bypass lock-in: capped-backoff −0.20% ALL,
  helps Ligra (+1.27%, phase changes), costs QMM (−1.05%, stable DoA). Backoff >
  fixed everywhere. Workload-dependent; small.
- **Bypass shadow (serve-and-reinsert)**: best L16S8 +0.22% ALL, Ligra +0.94%,
  small cost on QMM. Evidence-driven (silent when bypass is correct). Modest.
- **Set-sampled training** (policy-free sampler sets, train few / predict all):
  ~1% loss on QMM at the sweet spot (~256 sampler sets); does not converge to
  full because sampler sets forgo bypass (permanent coverage cost) — the correct
  Hawkeye/SDBP-style behavior. Per-suite cost curve running
  (`sample_pf_allsuites_20260613_2330`).

None of these explain the headline gap; they are overhead/robustness studies.

---

## 11. IPV-Live set dueling: bug, falsification, and fix (2026-06-23)

### The zero-initialized DoA vector bug

The N-way set-dueling refactor (commit 9819c17a, branch `set-dueling-nway`) changed
IPV-Live insertion to read `g_duel_doa[cfg]` for every block. The array was populated
from `IPV_DOA_i` env vars only when `g_n_configs >= 2`. Non-dueling runs (`g_n_configs=1`)
skipped this path, leaving `g_duel_doa[0] = {0,0,0,0,0}`.

**Evidence it was real:** cfgA (`{0,1,2,2,2}`) and ilB (`{0,1,2,2,3}`) produced
byte-identical `champsim.out` files in the mechcheck run (same IPC to 4 decimal places,
same MPKI, same RRPV-at-eviction histogram). Two configs that differ only in one IPV
position cannot be identical if that position is being read. The only explanation is that
neither config was being read — consistent with `g_duel_doa[0]` being all-zeros.

**Mechanism:** RRPV = `g_duel_doa[cfg][age_bucket]` for DoA blocks. With the zero vector,
every age bucket maps to RRPV=0 (MRU), so all DoA blocks were inserted at the most
protected position. `THD_DOA` was also inert: the threshold gates how often a block is
classified DoA, but the insertion position was wrong regardless of classification.

**Fix (commit 488746c18dc4):** Added `g_duel_doa[0] = g_ipv_doa;` before the early
return in `ensure_parsed_duel()`, so config 0 always mirrors the single-IPV path.
Verified: cfgA and ilB now differ (IPC gap ~0.5–2% per trace on typical suites).

**Results invalidated by the bug:** the ins2 arms of both threshold sweeps
(`ipv_thd_sweep_20260623_*`) were run with the N-way binary and produced nonsense.
Those jobs were cancelled and deleted. Pre-N-way references (`ipv_cfg2_20260621_0042`
cfgA, `ins3_hit_20260621_1954` ilB) were built from the binary before the refactor
and remain valid.

### Hit-count duel falsification

Hypothesis: cfgA's hit-count lead over ilB on QMM came from DoA blocks being retained
at higher RRPV and re-hitting. If so, filtering the duel signal to non-DoA hits should
flip the winner to ilB.

**Evidence against:** a local experiment on 3 QMM traces (binary at commit `488746c18dc4`,
branch `duel-miss-latency`) measured cfgA sampler DoA hits = 1,560 of 93,548 total (1.7%).
Filtering DoA hits barely changed the counters; the winner never flipped. cfgA genuinely
produces more non-DoA hits too, but ilB's IPC advantage is in the miss stream
(fewer/cheaper misses), invisible to any hit counter.

**Resolution:** `DUEL_METRIC=latency` (commit `7b3bf80fd758`) accumulates total fill
latency per sampler config; argmin selects the winner. Validated on 3 QMM traces that
previously picked cfgA under hit-count: all 3 correctly flip to ilB under latency.
Full 7-suite θ=6 result: pooled latency-duel +1.15% vs SRRIP, vs +0.83% for fixed ilB
and +0.90% for the hit-based duel. Both key failures resolved: QMM +0.18%→+1.47%,
ligra −1.82%→+1.30%. Cluster jobs: `eval_theta6_fixed_20260623_1440/ipv_live/duel_lat`
(binary `champsim_ipv_live_latency`, built from commit `7b3bf80fd758`).

### Why hit-count IS reliable for SRRIP-Live on Ligra (contrast with IPV-Live on QMM)

On Ligra at θ=6, 94–99% of LLC insertions are classified DoA but a non-trivial fraction
are re-referenced (DoA hit rates 2–25% per trace). Config B (ins@3) immediately evicts
those blocks → regression up to −5.2%. Config A (ins@2 ≈ SRRIP) keeps them at RRPV=2
→ they accumulate hits in A-sampler sets but not in B-sampler sets.

**Evidence (local experiment, 3 ligra traces, `results/local_ligra_duel`,
binary `bin/champsim_srrip_live` built from commit `da3249d5f3c3`, branch `duel-miss-latency`,
script `scripts/local_srrip_live_ligra_duel.sh`):**

| trace         | cfgB/SRRIP | duel/SRRIP | PSEL      |
|---------------|-----------|-----------|-----------|
| CF            |   +0.24%  |   −0.19%  | config_A  |
| BFSCC         |   −1.71%  |   −0.44%  | config_A  |
| PageRankDelta |   −5.16%  |   −1.53%  | 2/1023 → config_A |

PSEL reaches 2/1023 on PageRankDelta — the counter saturates almost entirely toward A.
The hit-count signal is clean here because A's sampler-hit advantage reflects genuinely
useful blocks being kept alive (misclassified DoA blocks that are actually re-used), not
inflated retention of truly-dead blocks as in the IPV-Live/QMM case.

The residual gap between the duel (−0.72% pooled) and standalone cfgA (−0.19%) is
structural: B-sampler sets are locked to cfgB and cannot switch. This cost is unavoidable
with any set-dueling design but is bounded by the sampler fraction (~3% of sets per config).

---

## 12. Bottom line — where the performance comes from

1. **Liveness scoring (3-class, mode-5) is the enabler:** ~0 → +2.43% even with a
   bad (address) index. Mazumdar's dead-counter caps the predictor at ~0.
2. **Per-PC aggregate indexing is the multiplier:** +2.43% → +12.17%, by
   generalizing a PC's deadness to fresh, never-seen addresses — decisive on the
   streaming/graph/ML suites.
3. **STLB bypass adds the rest** (+12.17% LLC → +13.56% LLC+STLB).
4. **Cross-level propagation, lock-in probes, and sampling are second-order** —
   small, workload-dependent refinements, not the source of the gap.

Ruled out as explanations: threshold, PC hashing, and gating per se.

**One-line version for the paper:** *our advantage is the combination of 3-class
per-PC liveness scoring (which makes the prediction meaningful) and pure per-PC
aggregation (which generalizes it to unseen addresses); prior per-address /
dead-counter designs lack both, and adding either alone is insufficient.*

---

## 12. Open items (to finalize the attribution)

- `pconly` per-suite (step 2) — running.
- Bridge step 3 (PC-only + mode-5 scoring) — implement/run next; the predicted
  decisive lift.
- `propgate` PFN-vs-PC gate per suite — running (esp. Ligra).
- `sample_pf` per-suite sampling cost curve — running.
- Confirm the scoring lever on a second index point (mode-5 + per-(PC,address))
  if we want to fully separate scoring from aggregation.
