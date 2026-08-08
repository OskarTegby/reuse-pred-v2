# Paper data provenance

All plots in the paper can be regenerated from the JSON files in `data/`
by running the plot scripts from the repo root:

```
python3 scripts/analysis/plot_liveness_rates.py
python3 scripts/analysis/plot_llc_threshold_combined.py
python3 scripts/analysis/plot_stlb_threshold_combined.py
python3 scripts/analysis/plot_combined_threshold.py
```

The JSON files were extracted from the original cluster output by:

```
python3 scripts/analysis/extract_paper_data.py
```

---

## Figure 1 — Liveness breakdown (liveness_rates.png)

**Data files:** `data/llc_lru_{suite}.json` for all 7 suites

**Source directories:** `results/{suite}_repl_pol_20260522_0722/lru_baseline/`

**Cluster run date:** 2026-05-22

**Config:** 2 MB LLC (2048×16), 1,024-entry STLB (128×8), LRU replacement,
BHIST_MODE not set (flat address-indexed bHIST for liveness tracking),
50 M warmup + 100 M sim instructions per trace.

**What it shows:** Fraction of cache evictions classified as DoA, mostly-dead,
or mostly-alive at the LLC and STLB under LRU. Counts aggregated over all
traces in each suite before computing fractions (not geomean of per-trace
percentages — the two are not equivalent).

**Branch at submission:** `liveness-guided-replacement`

**Relevant commits:**
- `cb96843f` — integrate liveness-guided SRRIP and IPV replacement policies
- `b954ec9e` — submit threshold sweeps for all 7 suites (exp-001)

---

## Figure 2 — LLC threshold sensitivity (llc_threshold_combined.png)

**Data files:**
- `data/llc_lru_{suite}.json` — LRU baseline (same run as Figure 1)
- `data/llc_srrip_{suite}_thd{N}.json` — SRRIP-Live at thresholds 1,2,4,8,16
- `data/llc_ipv_{suite}_thd{N}.json` — IPV-Live at thresholds 1,2,4,8,16

**Source directories (SRRIP-Live):**

| Suite  | Directory                                  | Date       |
|--------|--------------------------------------------|------------|
| DPC3   | dpc3_srrip_live_thd_pc_20260513_0055       | 2026-05-13 |
| QMM    | qmm_srrip_live_thd_pc_20260513_0056        | 2026-05-13 |
| Google | google_srrip_live_thd_pc_20260513_0056     | 2026-05-13 |
| GAP    | gap_srrip_live_thd_pc_20260520_0059        | 2026-05-20 |
| GMS    | gms_srrip_live_thd_pc_20260520_0128        | 2026-05-20 |
| Ligra  | ligra_srrip_live_thd_pc_20260520_0059      | 2026-05-20 |
| ML     | ml_srrip_live_thd_pc_20260520_0059         | 2026-05-20 |

**Source directories (IPV-Live):**

| Suite  | Location | Directory                               | Date       |
|--------|----------|-----------------------------------------|------------|
| DPC3   | cluster/ | dpc3_ipv_live_thd_addr_20260514_1432    | 2026-05-14 |
| QMM    | cluster/ | qmm_ipv_live_thd_pc_20260514_1432      | 2026-05-14 |
| Google | cluster/ | google_ipv_live_thd_pc_20260514_1432   | 2026-05-14 |
| GAP    | results/ | gap_ipv_live_thd_pc_20260520_0819      | 2026-05-20 |
| GMS    | results/ | gms_ipv_live_thd_pc_20260520_0819      | 2026-05-20 |
| Ligra  | results/ | ligra_ipv_live_thd_pc_20260520_0819    | 2026-05-20 |
| ML     | results/ | ml_ipv_live_thd_pc_20260520_0819       | 2026-05-20 |

**Config:** BHIST_MODE=pc, MID_THD swept over {1,2,4,8,16}, LLC replacement
changed to srrip_live / ipv_live respectively, STLB uses LRU.

**Note (DPC3 IPV-Live):** uses address-indexed bHIST (BHIST_MODE=addr) rather
than PC-indexed — found to be more effective for SPEC workloads.

**Relevant commits:**
- `a09a980b` — add BHIST_MODE=pc to SRRIP-Live submissions
- `5a783cd3` — implement ipv_live

---

## Figure 3 — STLB threshold sensitivity (stlb_threshold_combined.png)

**Data files:**
- `data/stlb_lru_{suite}.json` — LRU baseline (separate STLB-policy run)
- `data/stlb_srrip_{suite}_thd{N}.json` — SRRIP-Live in STLB only
- `data/stlb_ipv_{suite}_thd{N}.json` — IPV-Live in STLB only

**Source directories (SRRIP-Live):**

| Suite  | Directory                             | Date       |
|--------|---------------------------------------|------------|
| DPC3   | dpc3_stlb_thd_pc_20260514_0025        | 2026-05-14 |
| QMM    | qmm_stlb_thd_pc_20260514_0025         | 2026-05-14 |
| Google | google_stlb_thd_pc_20260514_0025      | 2026-05-14 |
| GAP    | gap_stlb_thd_pc_20260520_0826         | 2026-05-20 |
| GMS    | gms_stlb_thd_pc_20260520_0826         | 2026-05-20 |
| Ligra  | ligra_stlb_thd_pc_20260520_0826       | 2026-05-20 |
| ML     | ml_stlb_thd_pc_20260520_0826          | 2026-05-20 |

**Source directories (IPV-Live):**

| Suite  | Directory                                    | Date       |
|--------|----------------------------------------------|------------|
| DPC3   | dpc3_stlb_ipv_live_thd_pc_20260524_0142      | 2026-05-24 |
| QMM    | qmm_stlb_ipv_live_thd_pc_20260516_0902       | 2026-05-16 |
| Google | google_stlb_ipv_live_thd_pc_20260516_0902    | 2026-05-16 |
| GAP    | gap_stlb_ipv_live_thd_pc_20260520_0827       | 2026-05-20 |
| GMS    | gms_stlb_ipv_live_thd_pc_20260520_0827       | 2026-05-20 |
| Ligra  | ligra_stlb_ipv_live_thd_pc_20260520_0827     | 2026-05-20 |
| ML     | ml_stlb_ipv_live_thd_pc_20260520_0827        | 2026-05-20 |

**STLB LRU baselines:**

| Suite  | Directory                              | Date       |
|--------|----------------------------------------|------------|
| DPC3   | dpc3_stlb_policy_pc_20260513_0916/lru  | 2026-05-13 |
| QMM    | qmm_stlb_policy_pc_20260513_0916/lru   | 2026-05-13 |
| Google | google_stlb_policy_pc_20260513_0916/lru| 2026-05-13 |
| GAP    | gap_stlb_policy_pc_20260523_1529/lru   | 2026-05-23 |
| GMS    | gms_stlb_policy_pc_20260523_1529/lru   | 2026-05-23 |
| Ligra  | ligra_stlb_policy_pc_20260523_1529/lru | 2026-05-23 |
| ML     | ml_stlb_policy_pc_20260523_1529/lru    | 2026-05-23 |

**Config:** BHIST_MODE=pc, SRRIP_LIVE_TARGET=stlb, MID_THD swept over
{1,2,4,8,16}, LLC uses LRU.

---

## Figure 4 — Combined LLC+STLB (combined_llc_stlb_comparison.png)

**Data files:** `data/combined_{suite}_{config}.json`
where config ∈ {lru, llc_srrip, stlb_srrip, both_srrip, both_ipv}

**Source directories:**

| Suite  | Config      | Directory (under cluster/ unless noted)              | Threshold |
|--------|-------------|------------------------------------------------------|-----------|
| DPC3   | llc_srrip   | results/dpc3_srrip_live_thd_pc_20260513_0055         | thd8      |
| DPC3   | stlb_srrip  | results/dpc3_stlb_thd_pc_20260514_0025               | thd16     |
| DPC3   | both_srrip  | dpc3_srrip_live_both_thd_addr_20260514_2018          | thd16     |
| DPC3   | both_ipv    | dpc3_ipv_live_both_thd_addr_20260517_2217            | thd16     |
| Google | llc_srrip   | results/google_srrip_live_thd_pc_20260513_0056       | thd8      |
| Google | stlb_srrip  | results/google_stlb_thd_pc_20260514_0025             | thd16     |
| Google | both_srrip  | google_srrip_live_both_thd_pc_20260514_2018          | thd8      |
| Google | both_ipv    | google_ipv_live_both_thd_pc_20260517_2218            | thd8      |
| QMM    | llc_srrip   | results/qmm_srrip_live_thd_pc_20260513_0056          | thd4      |
| QMM    | stlb_srrip  | results/qmm_stlb_thd_pc_20260514_0025                | thd1      |
| QMM    | both_srrip  | qmm_srrip_live_both_thd_pc_20260514_2018             | thd4      |
| QMM    | both_ipv    | qmm_ipv_live_both_thd_pc_20260517_2218               | thd2      |

**Config:** SRRIP_LIVE_TARGET=both (for combined runs), BHIST_MODE=pc,
threshold per suite as shown above.

**Note:** Thresholds used here are the best found from Figures 2 and 3
separately — not a joint optimisation. Combined results for GAP, GMS, Ligra,
and ML are not available (not run).

---

## Hardware configuration (all experiments)

| Component | Setting                          |
|-----------|----------------------------------|
| LLC       | 2 MB, 2048 sets × 16 ways        |
| STLB      | 1,024 entries, 128 sets × 8 ways |
| L2C       | 256 KB, 512 sets × 8 ways        |
| L1D / L1I | 32 KB, 64 sets × 8 ways          |
| Warmup    | 50 M instructions                |
| Sim       | 100 M instructions               |
| Simulator | ChampSim (branch: liveness-guided-replacement) |

Config file: `champsim_config.json` (2 MB LLC version) at commit `cbc12a70`
(current HEAD of liveness-guided-replacement at time of last submission).

---

---

## Configs snapshot

All config files, submission scripts, and replacement policy source files for
the 2026-06-02 runs are snapshotted at `configs/`. See `configs/README.md`
for a full description of each file. These copies are from commit `0443feaae590`.

---

## Implementation note — corrected 3-class liveness (2026-06-02)

All runs from 2026-06-02 onward use a corrected implementation of the
liveness predictor. The key differences from the earlier runs (Figures 2–4
above) are:

- `accessed` bit now set unconditionally for all LLC/STLB hits (previously
  gated on `way->dp`, which is only true with cbpred enabled — effectively
  making every block appear DoA).
- `last_hit_cycle` initialised to `current_cycle` at fill (not 0).
- Halflife boundary uses `<=` not `<`.
- Per-PC counters are `uint64_t` with no saturation (old: `uint8_t` capped at
  15, preventing thd=16 from ever being reached).
- `LOW_THD` now defaults to `MID_THD` (old default 0 disabled mostly-dead).
- Hit promotion uses the class stored at insertion time, not re-classification
  (prevents a live block losing its promotion if its PC accumulates DoA history
  while it sits in the cache).

The practical effect: the mostly-dead classification is now active. At thd=4
on QMM this shifts the insert mix from ~100% DoA to roughly DoA=26%,
mostly-dead=21%, mostly-alive=53%. Peak geomean speedup (LLC, QMM, thd=4)
changes from +3.83% (old) to +3.56% (SRRIP-Live) and +4.23% (old) to +4.51%
(IPV-Live) — both within ±0.3 pp, with the mostly-dead path now contributing.

**Commit at first corrected run:** `0443feaae590`
(fix: restore correct hit-promotion and fix SRRIP_LIVE_TARGET env-var handling)

---

## Validation run — qmm_validate_20260602_1053

**Purpose:** Verify corrected implementation reproduces Figure 2 results
before launching full threshold sweep.

**Cluster label:** `qmm_validate_20260602_1053` (on Castillo:
`~/ChampSim-dev/results/qmm_validate_20260602_1053/`)

**Submitted:** 2026-06-02

**Traces:** 10 QMM traces (tasks 1–10 from QMM trace list)

**Policies:** SRRIP-Live (thd=4) + LRU baseline

**Config:** `champsim_maz_policies.json`, BHIST_MODE=pc, MID_THD=4, LOW_THD=4,
50 M warmup + 100 M sim instructions.

**Result:** LRU-normalised geomean = +4.37% (vs +3.96% in old Figure 2 at
thd=4 over the same 10 traces). Difference explained by active mostly-dead
path. Accepted as validation of corrected implementation.

**Job arrays:** 1403838 (SRRIP-Live), 1403839 (LRU)

---

## New QMM LLC sweep — qmm_maz_thd_20260602_1118

**Purpose:** Full LLC threshold sensitivity study on all 45 QMM traces with
corrected implementation. Replaces the QMM entries from Figure 2 above.

**Cluster label:** `qmm_maz_thd_20260602_1118` (on Castillo:
`~/ChampSim-dev/results/qmm_maz_thd_20260602_1118/`)

**Submitted:** 2026-06-02  **Completed:** 2026-06-02

**Traces:** 45 QMM traces, all tasks 1–45

**Config:** `champsim_maz_policies.json`, BHIST_MODE=pc,
50 M warmup + 100 M sim instructions.

**Policies and subdirectories:**

| Subdir | Binary | MID_THD | LOW_THD | Job array |
|--------|--------|---------|---------|-----------|
| `lru/` | champsim_lru | — | — | 1404022 |
| `srrip/` | champsim_srrip | — | — | 1404023 |
| `llc_srrip_live/thd1/` | champsim_srrip_live | 1 | 1 | 1404024 |
| `llc_srrip_live/thd2/` | champsim_srrip_live | 2 | 2 | 1404025 |
| `llc_srrip_live/thd4/` | champsim_srrip_live | 4 | 4 | 1404026 |
| `llc_srrip_live/thd8/` | champsim_srrip_live | 8 | 8 | 1404027 |
| `llc_srrip_live/thd16/` | champsim_srrip_live | 16 | 16 | 1404028 |
| `llc_ipv_live/thd1/` | champsim_ipv_live | 1 | 1 | 1404029 |
| `llc_ipv_live/thd2/` | champsim_ipv_live | 2 | 2 | 1404030 |
| `llc_ipv_live/thd4/` | champsim_ipv_live | 4 | 4 | 1404031 |
| `llc_ipv_live/thd8/` | champsim_ipv_live | 8 | 8 | 1404032 |
| `llc_ipv_live/thd16/` | champsim_ipv_live | 16 | 16 | 1404033 |

**Results (geomean speedup vs LRU, 45 traces):**

| Policy | thd=1 | thd=2 | thd=4 | thd=8 | thd=16 |
|--------|-------|-------|-------|-------|--------|
| SRRIP (no liveness) | — | — | +1.35% | — | — |
| SRRIP-Live | +2.54% | +3.30% | +3.56% | +3.48% | +3.23% |
| IPV-Live   | +2.56% | +4.22% | +4.51% | +4.15% | +3.52% |

**To extract to paper/data/:** run `scripts/analysis/extract_paper_data.py`
pointing at this directory. Expected output files:
`data/llc_lru_qmm_v2.json`, `data/llc_srrip_qmm_v2_thd{N}.json`,
`data/llc_ipv_qmm_v2_thd{N}.json`.

**Commit:** `0443feaae590`

---

## LRU-Live LLC threshold sweep — qmm_lru_live_thd_20260602_1535

**Purpose:** Threshold sensitivity for LRU-Live on QMM LLC. Used to extend
the policy comparison (LRU → LRU-Live → SRRIP → SRRIP-Live → IPV-Live).

**Cluster label:** `qmm_lru_live_thd_20260602_1535` (on Castillo:
`~/ChampSim-dev/results/qmm_lru_live_thd_20260602_1535/`)

**Submitted:** 2026-06-02  **Completed:** pending

**Traces:** 45 QMM traces, all tasks 1–45

**Config:** `champsim_maz_policies.json`, BHIST_MODE=pc,
50 M warmup + 100 M sim instructions.

**Policy:** LRU-Live — inserts DoA blocks at rank ⌊2N/3⌋ from MRU (position 10
for N=16), mostly-dead at ⌊N/3⌋ from MRU (position 5), mostly-alive at MRU.
All hits promote to MRU. Liveness table same as SRRIP-Live.

**Subdirectories and job arrays:**

| Subdir | Binary | MID_THD | LOW_THD | Job array |
|--------|--------|---------|---------|-----------|
| `thd1/` | champsim_lru_live | 1 | 1 | 1404036 |
| `thd2/` | champsim_lru_live | 2 | 2 | 1404037 |
| `thd4/` | champsim_lru_live | 4 | 4 | 1404038 |
| `thd8/` | champsim_lru_live | 8 | 8 | 1404039 |
| `thd16/` | champsim_lru_live | 16 | 16 | 1404040 |

**LRU baseline:** reuse `qmm_maz_thd_20260602_1118/lru/` (same binary and
config, no need to re-run).

**Early result (5 traces, 50 M sim):** geomean +0.63% at thd=4. All traces
positive. Hit rate ordering confirmed: DoA=17%, mostly-dead=42%, alive=1577%.

**To extract to paper/data/:** `data/llc_lru_live_qmm_thd{N}.json`.

**Commit:** `0443feaae590`

---

## QMM STLB threshold sweep — qmm_stlb_thd_20260602_1537

**Purpose:** STLB-only threshold sensitivity on all 45 QMM traces with
corrected implementation. Replaces the QMM entries from Figure 3 above.

**Cluster label:** `qmm_stlb_thd_20260602_1537` (on Castillo:
`~/ChampSim-dev/results/qmm_stlb_thd_20260602_1537/`)

**Submitted:** 2026-06-02  **Completed:** pending

**Traces:** 45 QMM traces, all tasks 1–45

**Config:** `champsim_maz_policies.json`, BHIST_MODE=pc, SRRIP_LIVE_TARGET=stlb
(guidance applied to STLB only; LLC uses LRU), 50 M warmup + 100 M sim.

**Policies and subdirectories:**

| Subdir | Binary | MID_THD | LOW_THD | Job array |
|--------|--------|---------|---------|-----------|
| `stlb_srrip_live/thd1/` | champsim_stlb_srrip_live | 1 | 1 | 1404041 |
| `stlb_srrip_live/thd2/` | champsim_stlb_srrip_live | 2 | 2 | 1404042 |
| `stlb_srrip_live/thd4/` | champsim_stlb_srrip_live | 4 | 4 | 1404043 |
| `stlb_srrip_live/thd8/` | champsim_stlb_srrip_live | 8 | 8 | 1404044 |
| `stlb_srrip_live/thd16/` | champsim_stlb_srrip_live | 16 | 16 | 1404045 |
| `stlb_ipv_live/thd1/` | champsim_stlb_ipv_live | 1 | 1 | 1404046 |
| `stlb_ipv_live/thd2/` | champsim_stlb_ipv_live | 2 | 2 | 1404047 |
| `stlb_ipv_live/thd4/` | champsim_stlb_ipv_live | 4 | 4 | 1404048 |
| `stlb_ipv_live/thd8/` | champsim_stlb_ipv_live | 8 | 8 | 1404049 |
| `stlb_ipv_live/thd16/` | champsim_stlb_ipv_live | 16 | 16 | 1404050 |

**LRU baseline:** reuse `qmm_maz_thd_20260602_1118/lru/` (same binary and
config, no need to re-run).

**To extract to paper/data/:** `data/stlb_srrip_qmm_v2_thd{N}.json`,
`data/stlb_ipv_qmm_v2_thd{N}.json`.

**Commit:** `0443feaae590`

---

## How to recreate all new (v2) QMM results from scratch

```bash
# 1. Ensure binaries are built and transferred to Castillo
./config.sh champsim_maz_policies.json
make static
scp bin/champsim_{lru,srrip,srrip_live,ipv_live,lru_live,stlb_srrip_live,stlb_ipv_live} \
    castillo:~/ChampSim-dev/bin/

# 2. LLC + baselines sweep
bash scripts/submit/sweep_mazumdar_threshold.sh qmm --llc-only

# 3. LRU-Live sweep (reuses LRU baseline from step 2)
#    Submit manually with thresholds 1,2,4,8,16 using champsim_lru_live

# 4. STLB sweep (reuses LRU baseline from step 2)
#    Submit manually with thresholds 1,2,4,8,16 using champsim_stlb_{srrip,ipv}_live
#    with SRRIP_LIVE_TARGET=stlb

# 5. Extract results to paper/data/
python3 scripts/analysis/extract_paper_data.py
```

All runs: 45 QMM traces, 50 M warmup + 100 M sim, Mazumdar config
(2 MB LLC 2048×16, STLB 128×8), BHIST_MODE=pc, commit `0443feaae590`.

---

## CORRECTION (2026-06-04) — write-hit promotion artifact; results re-baselined

**Discovery:** The `srrip_live`/`ipv_live`/`lru_live` modules carried a
`if (hit && type == WRITE) return;` guard absent from the plain baselines, so
write-hit (writeback) blocks were not promoted. This is unrelated to liveness
but was miscredited to it because we compared against plain SRRIP/LRU.

**Impact on prior numbers:** All "vs SRRIP" / "vs LRU" liveness speedups from
runs before 2026-06-04 are inflated by ~0.8–1.2 pp (threshold-dependent). The
optimal LLC threshold (thd=4) is unchanged, but magnitudes were overstated
(~+2.18% → honest +1.40% at thd=4, unbounded). Affected: qmm_maz_thd_20260602_1118,
qmm_stlb_thd_20260602_1537, all qmm_size_* and qmm_buf_size_* runs.

**Corrected runs (fixed binary, honest SRRIP baseline = srrip_live cap=0):**
- `qmm_srrip_thd_llc_fixed_20260604_1851` — LLC threshold sweep, thd 1/2/4/8/16.
  vs SRRIP: thd1 −0.04%, thd2 +0.92%, thd4 +1.40%, thd8 +1.31%, thd16 +0.97%.
- `qmm_srrip_size_llc_fixed_20260604_1720` — LLC size sweep, buf=128.
  vs SRRIP: cap256 ~+0.05%, cap512 +0.58%, cap1024 +0.72%, cap2048 +0.82%,
  cap4096 +0.94%; unbounded ceiling pending.

**New knob:** `ACCESSED_ON_WRITE` (default 1). When 0, writeback hits do not set
the Accessed bit, so write-back-only blocks are labeled DoA — a cleaner training
signal for the liveness predictor. Under evaluation.

**Baseline rule going forward:** report liveness speedup vs the SAME module with
liveness disabled (cap=0 / TARGET=none), never vs plain srrip/lru, so write-hit
handling is held constant. cap=0 must equal the plain baseline exactly — verify
on one trace before trusting any number.

## 2026-06-05 — Threshold rerun after writeback fixes (qmm_thd_rebaseline_20260604_2307)

Unbounded history. All fixes applied: baseline SRRIP/IPV skip writeback-hit
promotion (match LRU); liveness labels exclude writebacks (Accessed bit +
last_hit_cycle gated on type!=WRITE). 45 QMM traces, warmup 50M / sim 100M.
IPC parsed from final `CPU 0 cumulative IPC:` line.

Baselines (geomean vs LRU): SRRIP +2.63%, IPV +2.63% (IPV unguided == SRRIP).

SRRIP-Live LLC (vs SRRIP / vs LRU):
  thd1 -0.09/+2.54  thd2 +0.65/+3.30  thd4 +0.90/+3.56  thd8 +0.82/+3.48  thd16 +0.58/+3.23
SRRIP-Live STLB (vs SRRIP / vs LRU):
  thd1 +2.44/+5.13  thd2 +1.93/+4.61  thd4 +1.13/+3.79  thd8 +0.29/+2.92  thd16 -0.58/+2.04
IPV-Live LLC (vs IPV / vs LRU):
  thd1 -0.07/+2.56  thd2 +1.55/+4.22  thd4 +1.83/+4.51  thd8 +1.48/+4.15  thd16 +0.86/+3.52
IPV-Live STLB (vs IPV / vs LRU):
  thd1 +2.54/+5.24  thd2 +2.46/+5.16  thd4 +1.82/+4.50  thd8 +0.85/+3.51  thd16 -0.18/+2.45

Per-level optima: LLC thd=4, STLB thd=1 (both policies). IPV-Live > SRRIP-Live
at LLC (+1.83 vs +0.90); roughly tied at STLB (+2.54 vs +2.44). STLB is the
bigger lever. Honest LLC gains ~half the old textbook-baseline figures
(+1.40/+2.18) as expected post writeback-skip correction.

NOTE: tab:llc_size rerun complete (qmm_size_combined_20260605_0757); paper updated
2026-06-05 with new both-guided methodology and correct post-fix numbers.

## 2026-06-05 — Combined + size studies (qmm_size_combined_20260605_0757)

Both levels guided (LLC thd=4, STLB thd=1) via champsim_both_{srrip,ipv}_live.
Requires per-level-cap-independence fix (cache.cc ~278). Baselines reuse
qmm_thd_rebaseline (lru/srrip/ipv; ipv==srrip byte-identical per trace).

COMBINED (both unbounded), apples-to-apples vs OWN base / vs LRU:
  SRRIP-Live vs SRRIP: +5.59% / +8.37%   (n=45)  -> SUPER-additive (parts sum ~+3.3%)
  IPV-Live   vs IPV:   +4.47% / +7.22%   (n=45)  -> additive (parts sum ~+4.4%)
Synergy reverses per-level ranking: IPV-Live leads each level alone but
SRRIP-Live wins combined.

LLC size study (SRRIP-Live both-guided, STLB unbounded, buf=128) vs SRRIP / vs LRU:
  256  +4.85% / +7.61%   (n=45)
  512  +5.01% / +7.77%   (n=45)
  1024 +5.13% / +7.89%   (n=45)
  2048 +5.31% / +8.08%   (n=45)
  4096 +5.46% / +8.24%   (n=45)
  unbounded +5.59% / +8.37%  (= combined srrip_live)
  Key finding: remarkably FLAT. 256 entries = 87% of combined gain.

STLB size study (SRRIP-Live both-guided, LLC unbounded, buf=128) vs SRRIP / vs LRU:
  256  +3.35% / +6.07%   (n=45)   [60% of combined gain]
  512  +4.04% / +6.77%   (n=45)   [72%]
  1024 +5.06% / +7.82%   (n=45)   [90%]
  unbounded +5.59% / +8.37%  (= combined srrip_live)
  Key finding: STEEP. STLB needs ~1024 entries for near-full gain.

COMPLETE as of 2026-06-05. Paper updated: tab:llc_size rewritten (new methodology,
new numbers), tab:stlb_size added, sec:llcsize narrative updated (flat vs steep
asymmetry, both-guided methodology). combined paragraph: "remaining suites" note
removed, IPV baseline clarified to SRRIP.
