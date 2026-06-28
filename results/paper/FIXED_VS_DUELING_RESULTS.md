# Fixed-Policy vs Set-Dueling Results

Tracking doc for the liveness replacement-policy results, comparing the
**fixed-config** studies (single static insertion policy) against the
**set-dueling** studies (two insertion configs, adaptively selected per set).

All speedups are **% IPC**, SimPoint-weighted on SPEC/dpc3 traces, flat geomean
elsewhere. Last updated 2026-06-27.

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

## 3. Dueling DoA-threshold sweeps

Goal: does set dueling let a policy use a more aggressive `THD_DOA` than the
fixed-config optimum (because the duel falls back to gentle insertion on the
pain-point sets)? `THD_DEAD` = min(per-suite, `THD_DOA`) (clamped) for LRU/SRRIP;
unclamped per-suite for IPV (matches its existing sweep).

### 3a. Fixed-config LRU-Live threshold optima (reference)
Source: `allsuites_thd_phase2_20260617` + `phase3_20260618` (single config). Best `THD_DOA` per suite:

| dpc3 | gap | gms | ligra | ml | qmm | google |
|------|-----|-----|-------|----|----|--------|
| **20** | 2 | 30 | 2 | 2 | 2 | 6 |

dpc3 has a sharp +4.3% peak at doa20 that forces the global optimum high.

### 3b. LRU-Live dueling threshold sweep — speedup vs LRU base
Source: `lru_live_thd_duel_20260627` (+ doa6 anchor from `lru_live_theta6/duel`).
dpc3 = 35-subset; google omitted (no LRU base). doa25/30 still completing.

| suite | doa2 | doa4 | doa6 | doa8 | doa16 | doa20 |
|-------|------|------|------|------|-------|-------|
| dpc3  | +2.60 | **+2.84** | +2.01 | +2.22 | +2.12 | +2.16 |
| gap   | **+8.84** | +8.54 | +6.85 | +6.65 | +5.84 | +5.78 |
| gms   | −1.74 | −1.55 | −1.20 | −1.03 | −0.64 | −0.63 |
| ligra | +4.77 | **+4.95** | +4.12 | +4.63 | +4.02 | +3.98 |
| ml    | +2.08 | +2.97 | +2.95 | +3.04 | **+3.13** | +3.10 |
| qmm   | +2.42 | +2.32 | **+2.83** | +2.76 | +2.54 | +2.53 |

**Key finding — dueling de-sensitizes dpc3:** under fixed-config dpc3 demanded
doa20 (+4.3% cliff); under dueling it is **flat across all thresholds** (+2.0 to
+2.8%, best at the *aggressive* doa4). The per-set duel telemetry confirms the
mechanism: cfgA (gentle `2n3`) wins on dpc3's sensitive SPEC traces, cfgB
(aggressive `lru`) wins on streaming. gap stays strongly aggressive; gms has no
headroom (negative); google (not shown here) resists aggressive thresholds.

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

## 5. In-flight (launched 2026-06-27)

| study | result dir | thresholds | tasks | status |
|-------|-----------|-----------|-------|--------|
| LRU-Live dueling thd | `lru_live_thd_duel_20260627` | {2,4,8,16,20,25,30} | 1,764 | doa25/30 tail |
| SRRIP-Live dueling thd | `srrip_live_thd_duel_20260627` | {2,4,8,16,20,25,30} | 1,764 | running |
| IPV-Live doa2 fill | `ipv_thd_doa2_20260627` | {2} | 148 | running |

Scripts: `scripts/submit/{lru,srrip}_live_thd_duel.sh`, `ipv_thd_doa2.sh`.

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

- [ ] Pick dueling-era optimal `THD_DOA` per suite once 3a–3c complete (all policies).
- [ ] Confirm whether SRRIP/IPV de-sensitize like LRU-Live's dpc3.
- [ ] Optionally fill LRU/IPV own-base on full dpc3 (95) + google.
- [ ] Feed chosen thresholds into the size-study rerun (clean binary + dueling).
