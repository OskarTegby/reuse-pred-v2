# Fixed-Policy vs Set-Dueling Results

Tracking doc for the liveness replacement-policy results, comparing the
**fixed-config** studies (single static insertion policy) against the
**set-dueling** studies (two insertion configs, adaptively selected per set).

All speedups are **% IPC**, SimPoint-weighted on SPEC/dpc3 traces, flat geomean
elsewhere. Last updated 2026-06-29.

---

## 1. Per-policy liveness benefit (vs own base)

Each liveness policy measured against its **own** baseline (LRU-Live/LRU,
SRRIP-Live/SRRIP, IPV-Live/IPV) — the apples-to-apples "how much does liveness
add to this substrate" view.

### 1a. Fixed-config (no dueling) — `docs/FINDINGS.md`
Source: `lru_live_vs_base_20260615`, `srrip` baseline, `ipv_live_vs_base_20260614`. mode-5, θ=6.

| suite | LRU-Live/LRU | SRRIP-Live/SRRIP | IPV-Live/IPV |
|-------|-------------|------------------|--------------|
| dpc3  | **+4.80%**  | +2.25%  | −0.55% |
| gap   | +3.82%      | +2.05%  | +6.26% |
| gms   | +0.38%      | +1.28%  | −1.29% |
| ligra | **+2.95%**  | +1.53%  | −3.02% |
| ml    | +2.37%      | **+8.80%** | **−9.77%** |
| qmm   | +1.40%      | +0.99%  | +1.75% |

**Finding:** LRU-Live and SRRIP-Live are robust (positive everywhere); IPV-Live
is **fragile** (negative on 4/6 suites, −9.77% on ML). LRU-Live beats SRRIP-Live
on dpc3 and ligra; SRRIP-Live wins big on ML.

### 1b. Set-dueling (each policy's best duel config, vs own base)
Source: `srrip_live_theta6_20260623`, `lru_live_theta6_20260624`,
`eval_theta6_fixed_20260623` (ipv `duel_lat`). θ=6.
Caveats: dpc3 is the 35-trace subset for LRU/IPV; google has no LRU/IPV base;
SRRIP/LRU duel on hit-count, IPV on miss-latency.

| policy (duel config)      | dpc3 | gap | gms | ligra | ml | qmm | ALL |
|---------------------------|------|-----|-----|-------|----|----|-----|
| SRRIP-Live duel (hit)     | +1.14 | +6.21 | +0.10 | +1.36 | +1.45 | +0.19 | +0.90 |
| LRU-Live  duel (hit)      | +2.01 | +6.85 | −1.20 | +4.12 | +2.95 | +2.83 | **+2.89** |
| IPV-Live  duel (latency)  | +3.99 | +6.04 | −0.39 | +1.30 | +1.41 | +1.47 | +1.79 |

**Finding:** with dueling the ranking is **LRU-Live > IPV-Live > SRRIP-Live**.
LRU-Live is the strongest substrate; IPV-Live is no longer fragile.

### 1c. IPV-Live ML regression — fixed by miss-latency dueling
Source: old `ipv_live_vs_base_20260614/ml` vs new `eval_theta6_fixed/duel_lat`, same IPV base, 31/31 ML traces.

| IPV-Live on ML        | vs IPV base |
|-----------------------|-------------|
| old fixed config      | **−9.77%** (reproduces FINDINGS exactly) |
| new `duel_lat`        | **+1.41%** |

The +11.2-pt swing comes from latency dueling selecting the safe arm instead of
committing to deep `ins@3` insertion that punished mispredicted-dead blocks.

### 1d. Is set dueling worth it? (duel vs fixed configs, θ=6)
Each insertion config and the duel, as speedup vs **own baseline**.
Source: `lru_live_theta6_20260624`, `srrip_live_theta6_20260623`; baselines
`lru_live_vs_base/lru_base` (6 suites, dpc3=35) and `baselines/srrip` (7 suites).

**LRU-Live vs LRU** (cfgA=2n3 gentle, cfgB=lru aggressive):

| suite | cfgA | cfgB | duel |
|-------|------|------|------|
| dpc3  | +2.82 | +1.86 | +2.01 |
| gap   | +3.97 | +7.14 | +6.85 |
| gms   | +0.15 | −1.40 | −1.20 |
| ligra | +3.01 | +2.18 | +4.12 |
| ml    | +2.36 | +3.19 | +2.95 |
| qmm   | +1.42 | +2.97 | +2.83 |

**SRRIP-Live vs SRRIP** (cfgA=ins@2 gentle, cfgB=ins@3 aggressive):

| suite | cfgA | cfgB | duel |
|-------|------|------|------|
| dpc3  | −0.07 | +0.51 | +1.14 |
| gap   | −0.87 | +6.03 | +6.21 |
| gms   | −0.21 | −0.57 | +0.10 |
| ligra | −0.26 | −1.87 | +1.36 |
| ml    | +0.06 | +1.36 | +1.45 |
| qmm   | +0.16 | +1.32 | +0.19 |
| google| +0.17 | −0.61 | +0.10 |

**Overall vs the best deployable *single global* config** (equal-weight across suites):

| config | LRU-Live | SRRIP-Live |
|--------|---------|-----------|
| cfgA everywhere | +2.28% | −0.15% |
| cfgB everywhere | +2.63% | +0.86% |
| **DUEL** | **+2.90%** | **+1.49%** |

**Finding: dueling beats the best single global config for BOTH policies** — by
+0.27 pp (LRU-Live, vs cfgB) and +0.63 pp (SRRIP-Live, vs cfgB). No single fixed
config is best on every suite (LRU: cfgA owns dpc3/gms, cfgB owns gap/ml/qmm), so
the duel's per-set selection recovers most of both groups. Dueling helps SRRIP-Live
more because its arms are more divergent: on ligra/gms **both** fixed arms trail the
baseline yet the duel is positive — only per-set selection can do that.

> ⚠ The correct non-dueling baseline is **one global config**, not a per-suite
> oracle. Comparing the duel to a "best-fixed" that switches arms per suite is not
> a realizable hardware design and understates dueling's value.

---

## 2. The 9-config aspect decomposition (SRRIP-Live)

Source: `duel_9cfg_20260626` (all 7 suites, vs SRRIP baseline). Direct controlled
contrasts isolating each design lever (% = variant vs its proper baseline):

| aspect                                    | dpc3 | gap | gms | ligra | ml | qmm | google | ALL |
|-------------------------------------------|------|-----|-----|-------|----|----|--------|-----|
| guidance only (gfix vs srrip)             | −0.03 | −0.53 | −0.17 | −0.14 | +0.07 | +0.24 | +0.31 | +0.09 |
| bypass only (bfix vs srrip)               | +8.02 | +10.15 | +0.04 | +28.50 | +2.09 | +1.75 | +1.99 | **+5.22** |
| +guidance on bypass (comb vs bfix)        | +0.33 | −1.59 | +0.12 | −0.88 | +1.75 | +0.39 | +0.72 | +0.46 |
| duel guidance, no bypass (vs gfix)        | +1.01 | +4.28 | +0.37 | +1.72 | +1.31 | +0.22 | +0.49 | +0.92 |
| duel guidance, bypass on (vs comb_fix)    | +0.13 | +1.31 | +0.02 | +0.18 | +0.08 | +0.05 | +0.05 | +0.14 |
| **duel bypass, no guidance (vs bfix)**    | −6.50 | −4.99 | +0.06 | −20.72 | +0.01 | −0.73 | −2.31 | **−3.94** |
| duel bypass, guid fixed (vs comb_fix)     | −6.76 | −3.75 | −0.06 | −19.84 | −1.37 | −0.82 | −2.32 | −4.07 |
| duel bypass, guid dueled (vs gduel_bfix)  | −6.69 | −4.23 | −0.00 | −19.70 | −1.32 | −0.74 | −2.25 | −4.02 |

**Findings:**
- **Bypass is the entire win** (+5.22%); guidance alone ≈ 0; guidance on top of
  bypass adds ~0.5% (inconsistent).
- **Bypass must be fixed-on.** Dueling the *bypass* decision costs ~4% (the duel
  mis-selects "don't bypass" on streaming workloads — ligra −20%).
- Dueling the *guidance* config helps ~+0.9% only when bypass is absent.

---

## 3. DoA-threshold sweeps (complete)

Goal: does set dueling let a policy tolerate a more **aggressive** `THD_DOA`?

**Direction (important):** a block is classified DoA when its score **≥ `THD_DOA`**,
so **low `THD_DOA` = aggressive** (more blocks become DoA) and **high = conservative**
(fewer DoA, behaves closer to the base policy). `THD_DOA=2` is the most aggressive
swept, `30` the most conservative. `THD_DEAD` = min(per-suite, `THD_DOA`) (clamped)
for LRU/SRRIP; unclamped per-suite for IPV.

All three sweeps are **complete**: 251 traces × every threshold (full dpc3=95,
google included). Values are **SimPoint-weighted geomean absolute IPC** per suite
(higher = better; ★ = best threshold for that suite). The `norm` row is the geomean
of each suite's IPC ÷ that suite's best (1.000 = best in *every* suite), giving the
deployable cross-suite optimum. Source: `{lru,srrip}_live_thd_duel_20260627`,
`ipv_thd_fixed_ins3_20260627`.

### 3a. LRU-Live (dueling, latency metric)

| suite | doa2 | doa4 | doa8 | doa16 | doa20 | doa25 | doa30 | best |
|-------|------|------|------|-------|-------|-------|-------|------|
| dpc3  | 1.331 | 1.333 | 1.331 | 1.331 | 1.331 | 1.333 | 1.334★ | 30 (flat) |
| gap   | 0.310★ | 0.310 | 0.304 | 0.302 | 0.302 | 0.301 | 0.301 | **2 (aggr)** |
| gms   | 1.156 | 1.158 | 1.165 | 1.169 | 1.169 | 1.171 | 1.172★ | 30 (cons) |
| ligra | 0.610 | 0.611★ | 0.609 | 0.605 | 0.605 | 0.605 | 0.603 | **4 (aggr)** |
| ml    | 1.842 | 1.858 | 1.859 | 1.860 | 1.860 | 1.862 | 1.863★ | 30 (cons) |
| qmm   | 1.961 | 1.959 | 1.968★ | 1.964 | 1.963 | 1.960 | 1.957 | 8 (aggr) |
| google| 0.460 | 0.462 | 0.473 | 0.480 | 0.480 | 0.480 | 0.481★ | 30 (cons) |
| **norm** | 0.989 | 0.991 | 0.993 | **0.993** | 0.993 | 0.993 | 0.993 | **→ ~16** |

### 3b. SRRIP-Live (dueling, hit-count/PSEL metric)

| suite | doa2 | doa4 | doa8 | doa16 | doa20 | doa25 | doa30 | best |
|-------|------|------|------|-------|-------|-------|-------|------|
| dpc3  | 1.345 | 1.345 | 1.346 | 1.346 | 1.347★ | 1.346 | 1.346 | 20 (flat) |
| gap   | 0.314 | 0.314 | 0.316★ | 0.311 | 0.309 | 0.307 | 0.306 | **8 (aggr)** |
| gms   | 1.183 | 1.183 | 1.186 | 1.186 | 1.187★ | 1.186 | 1.186 | 20 |
| ligra | 0.592 | 0.597 | 0.600 | 0.604 | 0.605 | 0.605 | 0.606★ | 30 (cons) |
| ml    | 1.825 | 1.826 | 1.829 | 1.828 | 1.829 | 1.827 | 1.833★ | 30 (cons) |
| qmm   | 1.965 | 1.965 | 1.968 | 1.970 | 1.970 | 1.970 | 1.971★ | 30 (cons) |
| google| 0.479 | 0.479 | 0.481 | 0.482 | 0.482 | 0.483 | 0.483★ | 30 (cons) |
| **norm** | 0.993 | 0.994 | **0.997** | 0.997 | 0.996 | 0.995 | 0.995 | **→ ~8** |

### 3c. IPV-Live (fixed ins3, **no dueling** — the sensitivity contrast)

| suite | doa2 | doa4 | doa6 | doa8 | doa16 | doa20 | doa25 | doa30 | best |
|-------|------|------|------|------|-------|-------|-------|-------|------|
| dpc3  | 1.325 | 1.332 | 1.337 | 1.339 | 1.343 | 1.344 | 1.344 | 1.346★ | 30 |
| gap   | 0.310 | 0.310 | 0.316★ | 0.316 | 0.312 | 0.311 | 0.310 | 0.309 | 6 (aggr) |
| gms   | 1.163 | 1.169 | 1.178 | 1.181 | 1.186 | 1.186 | 1.187 | 1.187★ | 30 |
| ligra | 0.571 | 0.571 | 0.580 | 0.582 | 0.587 | 0.587 | 0.591 | 0.593★ | 30 |
| ml    | 1.681 | 1.829 | 1.831 | 1.832 | 1.834 | 1.834★ | 1.831 | 1.831 | 20 |
| qmm   | 1.983 | 1.983 | 1.996 | 1.995 | 1.998★ | 1.998 | 1.997 | 1.996 | 16 |
| google| 0.470 | 0.470 | 0.480 | 0.480 | 0.488 | 0.488 | 0.490 | 0.495★ | 30 |
| **norm** | 0.966 | 0.980 | 0.990 | 0.991 | 0.994 | 0.994 | 0.995 | **0.996** | **→ 30** |

### 3d. Findings (corrected direction)

- **The optimum is moderate-to-conservative, not aggressive.** The low point of
  every curve is the *aggressive* end (`doa2`); best-on-average is LRU-Live **~16**,
  SRRIP-Live **~8**, IPV-fixed **30**.
- **Dueling de-risks aggression — the real de-sensitization result.** The penalty
  for running the most aggressive threshold (`doa2`) vs that policy's best:

  | | doa2 penalty | note |
  |---|---|---|
  | IPV-Live **fixed** (no duel) | **−3.0%** | ml collapses to 1.681 |
  | LRU-Live **dueling** | **−0.4%** | flat plateau 8–30 |

  Dueling doesn't make aggressive *better*; it makes aggressive *safe* (gentle-arm
  fallback absorbs the pain-point sets). Without dueling the aggressive end is a
  cliff; with it, ~free.
- **dpc3 is de-sensitized.** Under fixed-config dpc3 demanded a high threshold
  (+4.3% cliff at doa20); under dueling it is **flat** (1.331–1.334, argmax is
  noise-level). The earlier cliff is gone.
- **Per-suite split holds, mechanistically sensible:** streaming/graph prefer
  *aggressive* (gap 2, ligra 4, qmm 8 — genuinely dead blocks); reuse-heavy prefer
  *conservative* (gms, ml, google 30 — aggressive DoA evicts blocks they reuse).
- **For the size-study rerun:** adopt a single moderate global **THD_DOA ≈ 16**
  (LRU-Live). Dueling means leaning aggressive (down to ~8) to chase streaming/bypass
  benefit costs <0.5% — a freedom the fixed policy does not have.

> Prior §3b (speedup vs LRU base, dpc3=35-subset, google omitted) is superseded by
> the complete full-95 + google absolute-IPC curves above.

---

## 4. Result-dir provenance

| study | result dir | binary | notes |
|-------|-----------|--------|-------|
| fixed per-policy LRU | `lru_live_vs_base_20260615_{0847,0855}` | champsim_lru_live | 6 suites, dpc3=35 |
| fixed per-policy IPV | `ipv_live_vs_base_20260614_{2152,2154}` | champsim_ipv_morph | 6 suites, dpc3=35 |
| fixed LRU thd sweep | `allsuites_thd_phase{2,3}` | champsim_lru_live | THD_DOA + THD_DEAD, 7 suites |
| SRRIP-Live θ=6 duel | `srrip_live_theta6_20260623` | champsim_srrip_live | cfgA/cfgB/duel, hit metric |
| LRU-Live θ=6 duel | `lru_live_theta6_20260624` | champsim_lru_live | cfgA/cfgB/duel, latency |
| IPV-Live θ=6 duel | `eval_theta6_fixed_20260623` | champsim_ipv_live_latency | duel_lat |
| 9-config aspects | `duel_9cfg_20260626` | champsim_srrip_live | 9 configs × 7 suites |
| IPV thd sweep | `ipv_thd_sweep_v2_20260624` + `ext` | champsim_ipv_live_latency | doa{4,8,16,20,25,30}, 5 suites |

---

## 5. Threshold-sweep status (launched 2026-06-27)

| study | result dir | thresholds | status |
|-------|-----------|-----------|--------|
| LRU-Live dueling thd | `lru_live_thd_duel_20260627` | {2,4,8,16,20,25,30} | **complete** (251/thd) → §3a |
| SRRIP-Live dueling thd | `srrip_live_thd_duel_20260627` | {2,4,8,16,20,25,30} | **complete** (251/thd) → §3b |
| IPV-Live fixed-ins3 thd | `ipv_thd_fixed_ins3_20260627` | {2,4,6,8,16,20,25,30} | **complete** (251/thd) → §3c |

Scripts: `scripts/submit/{lru,srrip}_live_thd_duel.sh`, `ipv_thd_fixed_ins3.sh`.
All curves extracted via last-`cumulative IPC` per `champsim.out`, weighted with
`spec_weights.py`.

---

## 6. Caveats / asterisks

- **Duel metric differs by policy:** LRU/IPV use miss-latency, SRRIP uses
  hit-count (PSEL). Matches each policy's established config; cross-policy
  threshold comparisons carry this asterisk.
- **IPV sweep is 5 suites** (no gap/dpc3); LRU/SRRIP are 7.
- **dpc3 = 35-trace subset** wherever the LRU/IPV own-base is used (the baseline
  only ran the subset); SRRIP-Live and the dueling threshold sweeps use full 95.
- **google** has no LRU/IPV own-base — omitted from those tables.
- **THD_DEAD handling:** clamped to ≤ THD_DOA for LRU/SRRIP sweeps; unclamped
  per-suite for IPV (so it slots into the existing IPV curve).

---

## 7. Open items

- [x] Pick dueling-era optimal `THD_DOA` — §3: LRU-Live ~16, SRRIP-Live ~8 (both flat).
- [x] Confirm SRRIP/IPV de-sensitize — SRRIP-Live dueling is flat like LRU; IPV-fixed
      (no duel) is the sensitive contrast (doa2 −3%, ml cliff), quantifying dueling's value.
- [ ] Feed chosen threshold (THD_DOA ≈ 16, LRU-Live, dueling) into the size-study rerun.
- [ ] Optionally fill LRU/IPV own-base on full dpc3 (95) + google (for §1 vs-base, not §3).
