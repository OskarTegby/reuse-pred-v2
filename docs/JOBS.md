# Jobs Log

All cluster results live under `~/ChampSim-dev/results/` on Castillo.
Download with: `ssh -A otegby@abdet.inf.um.es "ssh otegby@castillo.inf.um.es 'cd ~/ChampSim-dev/results && tar czf - <dirs>'" | tar xzf - -C results/`

Suites: **DPC3** (SPEC), **Google**, **Qualcomm (QMM)**, **GAP**, **GMS**, **Ligra**, **ML**, **Mazumdar (MAZ)**

---

## Paper Workload Selection (`--selected`)

All sweep scripts that accept `--selected` restrict to the **top-4 benchmarks per suite by combined LLC+STLB dead fraction** (matching `workload_table.tex` and Figs 1–2). Mazumdar is never submitted.

**To resubmit any sweep for paper workloads only:**
```bash
ssh -A otegby@abdet.inf.um.es "ssh otegby@castillo.inf.um.es 'cd ~/ChampSim-dev && \
  for suite in dpc3 google qmm gap gms ligra ml; do \
    bash scripts/submit/<sweep_script>.sh \$suite --selected; \
  done'"
```

**Per-suite filters** (grep -E patterns on trace file paths):

| Suite | Selected benchmarks | Filter pattern |
|---|---|---|
| DPC3 | bwaves, lbm, imagick, fotonik3d | `603\.bwaves_s\|619\.lbm_s\|638\.imagick_s\|649\.fotonik3d_s` |
| GAP | bfs-14, bfs-10, sssp-10, sssp-14 | `bfs-14\.trace\|bfs-10\.trace\|sssp-10\.trace\|sssp-14\.trace` |
| Ligra | CF, PageRankDelta, BFSCC, BellmanFord | `ligra_CF\.\|ligra_PageRankDelta\.\|ligra_BFSCC\.\|ligra_BellmanFord\.` |
| QMM | srv_s7, srv_743, srv_526, srv_s10 | `srv_s7\.\|srv_743\.\|srv_526\.\|srv_s10\.` |
| Google | arizona.0, tahoe.2, charlie.1, charlie.2 | `arizona_0000\|tahoe_0002\|charlie_0001\|charlie_0002` |
| GMS | tri_cnt.137, tri_cnt.117, tri_cnt.360, kclique_star.1291 | `triangle_count.*slice-137\|triangle_count.*slice-117\|triangle_count.*slice-360\|k_clique_star.*slice-1291` |
| ML | bark.1, clip.1, whisper.1, whisper.3 | `coarse_token_gen\.1\.\|clip_trace_1\.\|whisper_trace_1\.\|whisper_trace_3\.` |

Note: DPC3 and Ligra have multiple slices per benchmark; all slices of the selected benchmarks are run (19 and 8 traces respectively). This matches what Figs 1–2 display.

Scripts that support `--selected`: `sweep_pfq_gating.sh`. Add the same `SELECTED_FILTER` + `--selected` logic to other scripts as needed.

---

## LLC Replacement Policy Comparison (`pol`)

**Script:** `scripts/submit/sweep_policy.sh`
**Purpose:** Compare replacement policies (LRU, SRRIP, SRRIP-live, LRU-mid, IPV-live, PACIPV, etc.) on the LLC, using the bypass predictor where applicable.
**Configs (0045 run):** `lru`, `lru_dp_only`, `lru_mid`, `lru_mid_pred`, `lru_pred`, `srrip`, `srrip_live`, `srrip_pred`, `ipv_live`, `pacipv`
**Configs (1545 run):** same but with `drrip`, `drrip_pred` instead of `ipv_live`, `pacipv`

| Suite | Launch | Cluster dir | Status | Notes |
|---|---|---|---|---|
| DPC3, Google, QMM | 2026-05-11 | `{suite}_pol_20260511_1545` | ✅ complete | 10 configs, in `results/cluster/` |
| DPC3, Google, QMM | 2026-05-19 | `{suite}_pol_20260519_0136` | ✅ complete | 1 config only (`lru_pred`), in `results/cluster/` |
| GAP, Ligra, ML | 2026-05-19 | `{suite}_pol_20260519_2343` | ✅ complete | 6 configs, in `results/cluster/` |
| GAP, Ligra, ML | 2026-05-20 | `{suite}_pol_20260520_0821` | ✅ complete | 1 config (`srrip`) per suite, in `results/cluster/` |
| GMS | 2026-05-20 | `gms_pol_20260520_0128` | ✅ complete | 10 configs, in `results/cluster/` |
| All 7 | 2026-05-21 | `{suite}_pol_20260521_0045` | ❌ empty | Jobs failed; dirs exist but no output |

**Best data per suite:**
- DPC3/Google/QMM: `{suite}_pol_20260511_1545` (10 configs)
- GAP/Ligra/ML: `{suite}_pol_20260519_2343` + `{suite}_pol_20260520_0821` (6+1 configs)
- GMS: `gms_pol_20260520_0128` (10 configs)

**Plot command:**
```bash
python3 scripts/analysis/plot_policy_comparison.py results/cluster/{suite}_pol_YYYYMMDD_HHMM \
    --baseline lru --out results/plots/pol/{suite}_policy
```

---

## LLC srrip_live Threshold Sweep (`srrip_live_thd`)

**Script:** `scripts/submit/sweep_srrip_live_thd.sh`
**Purpose:** Find the optimal liveness threshold (mid_thd) for srrip_live on the LLC. Two modes: addr-keyed and PC-keyed history.
**Configs:** `srrip_live_thd1`, `thd2`, `thd4`, `thd8`, `thd16`

| Suite | Launch | Cluster dir | Mode | Status |
|---|---|---|---|---|
| DPC3, Google, QMM | 2026-05-11 | `{suite}_srrip_live_thd_20260511_2218` | addr | ✅ in `results/cluster/` |
| DPC3, Google, QMM | 2026-05-13 | `{suite}_srrip_live_thd_pc_20260513_005*` | PC | ✅ in `results/cluster/` |
| DPC3 | 2026-05-14 | `dpc3_srrip_live_thd_addr_20260514_1507` | addr | ✅ in `results/cluster/` |
| GAP, Ligra, ML | 2026-05-20 | `{suite}_srrip_live_thd_addr_20260520_0059` | addr | ✅ in `results/cluster/` |
| GAP, Ligra, ML | 2026-05-20 | `{suite}_srrip_live_thd_pc_20260520_0059` | PC | ✅ in `results/cluster/` |
| GMS | 2026-05-20 | `gms_srrip_live_thd_addr_20260520_0128` | addr | ✅ in `results/cluster/` |
| GMS | 2026-05-20 | `gms_srrip_live_thd_pc_20260520_0128` | PC | ✅ in `results/cluster/` |
| MAZ | 2026-05-23 | `maz_srrip_live_thd_pc_20260523_1346` | PC | ⏳ running |

**Plot command (combined addr, 7 suites):**
```bash
python3 scripts/analysis/plot_srrip_live_thd.py \
  --thd-dirs results/cluster/dpc3_srrip_live_thd_20260511_2218 \
             results/cluster/gap_srrip_live_thd_addr_20260520_0059 \
             results/cluster/gms_srrip_live_thd_addr_20260520_0128 \
             results/cluster/google_srrip_live_thd_20260511_2218 \
             results/cluster/ligra_srrip_live_thd_addr_20260520_0059 \
             results/cluster/ml_srrip_live_thd_addr_20260520_0059 \
             results/cluster/qmm_srrip_live_thd_20260511_2218 \
  --pol-dirs results/cluster/dpc3_pol_20260511_1545 \
             results/cluster/gap_pol_20260519_2343 \
             results/cluster/gms_pol_20260520_0128 \
             results/cluster/google_pol_20260511_1545 \
             results/cluster/ligra_pol_20260519_2343 \
             results/cluster/ml_pol_20260519_2343 \
             results/cluster/qmm_pol_20260511_1545 \
  --labels "SPEC (DPC3)" GAP GMS Google Ligra ML Qualcomm \
  --out results/plots/srrip_live_thd_all_addr.png
```
Same pattern for PC mode using `*_pc_*` dirs. Once MAZ finishes, add it.

---

## LLC ipv_live Threshold Sweep (`ipv_live_thd`)

**Script:** `scripts/submit/sweep_srrip_live_thd.sh` (same script, different binary/prefix)
**Purpose:** Find optimal liveness threshold for IPV-live on the LLC.
**Configs:** `ipv_live_thd1`, `thd2`, `thd4`, `thd8`, `thd16`

| Suite | Launch | Cluster dir | Mode | Status |
|---|---|---|---|---|
| DPC3 | 2026-05-14 | `dpc3_ipv_live_thd_addr_20260514_1432` | addr | ✅ in `results/cluster/` |
| DPC3 | 2026-05-16 | `dpc3_ipv_live_thd_addr_20260516_0902` | addr | ✅ in `results/cluster/` |
| Google, QMM | 2026-05-14 | `{suite}_ipv_live_thd_pc_20260514_1432` | PC | ✅ in `results/cluster/` |
| Google, QMM | 2026-05-16 | `{suite}_ipv_live_thd_pc_20260516_0902` | PC | ✅ in `results/cluster/` |
| GAP, GMS, Ligra, ML | 2026-05-20 | `{suite}_ipv_live_thd_addr_20260520_0819` | addr | ✅ in `results/cluster/` (and `results/`) |
| GAP, GMS, Ligra, ML | 2026-05-20 | `{suite}_ipv_live_thd_pc_20260520_0819` | PC | ✅ in `results/cluster/` |

**Plot command:**
```bash
python3 scripts/analysis/plot_srrip_live_thd.py --thd-prefix ipv_live \
  --thd-dirs <ipv_live_thd dirs per suite> \
  --pol-dirs <pol dirs per suite> \
  --labels <suite labels> \
  --out results/plots/ipv_live_thd_addr_all.png
```

---

## LLC+STLB Combined Policy Comparison (`missing_policy`)

**Script:** `scripts/submit/sweep_missing_policy.sh`
**Purpose:** Test all combinations of running liveness policies simultaneously in both LLC and STLB (e.g., IPV-live in both, SRRIP in both).
**Configs:** `srrip_live_both`, `ipv`, `ipv_live`, `stlb_ipv_live`, `ipv_live_both`, `srrip_both`, `stlb_ipv`, `ipv_both`

| Suite | Launch | Cluster dir | Mode | Status |
|---|---|---|---|---|
| DPC3 | 2026-05-15 | `dpc3_missing_policy_20260515_0136` | addr | ✅ in `results/cluster/` |
| Google, QMM | 2026-05-15 | `{suite}_missing_policy_pc_20260515_0136` | PC | ✅ in `results/cluster/` |
| GMS | 2026-05-20 | `gms_missing_policy_pc_20260520_0134` | PC | ✅ in `results/cluster/` |
| GAP, Ligra, ML | 2026-05-20 | `{suite}_missing_policy_pc_20260520_0819` | PC | ✅ in `results/` |
| GAP, Ligra, ML | 2026-05-23 | `{suite}_missing_policy_20260523_1346` | addr | ⏳ running |
| GMS | — | — | addr | ❌ not yet submitted |

**Plot command (per suite, vs srrip_live_both baseline):**
```bash
python3 scripts/analysis/plot_policy_comparison.py <missing_policy_dir> \
    --baseline srrip_live_both --out results/plots/pol/{suite}_missing_policy
```

---

## LLC srrip_live + Bypass Combined (`srrip_live_bypass`)

**Script:** `scripts/submit/sweep_srrip_live_bypass.sh`
**Purpose:** Tests whether the bypass predictor stacks on top of srrip_live or whether their effects overlap.

| Suite | Launch | Cluster dir | Status |
|---|---|---|---|
| DPC3, Google, QMM | 2026-05-15 | `{suite}_srrip_live_bypass_20260515_2158` | ✅ in `results/cluster/` |
| DPC3, Google, QMM | 2026-05-21 | `{suite}_srrip_live_bypass_20260521_0046` | ✅ in `results/cluster/` |

**Plot command:** Use `plot_policy_comparison.py` or `plot_srrip_live_thd.py`.

---

## LLC at Half Size (`llc_half`, `llc_half_nopfq`)

**Purpose:** Check if results change when LLC is halved. `nopfq` variant removes the PFQ gate.

| Suite | Launch | Cluster dir | Status |
|---|---|---|---|
| DPC3, Google, QMM | 2026-05-16 | `{suite}_llc_half_20260516_23**` | ✅ in `results/cluster/` |
| DPC3, Google, QMM | 2026-05-17 | `{suite}_llc_half_nopfq_20260517_2148` | ✅ in `results/cluster/` |
| DPC3, Google, QMM | 2026-05-21 | `{suite}_llc_half_20260521_0046` | ✅ in `results/cluster/` |

**Plot command:** `plot_bypass_cfg_comparison.py` with `--2mb-dirs` and `--1mb-dirs`.

---

## LRU + Mid-Insertion Both LLC and STLB (`lru_mid_both`)

**Purpose:** Tests mid-insertion policy applied to both LLC and STLB simultaneously.

| Suite | Launch | Cluster dir | Status |
|---|---|---|---|
| DPC3, Google, QMM | 2026-05-15 | `{suite}_lru_mid_both_20260515_0737` | ✅ in `results/cluster/` |

---

## srrip_live_both Threshold (`srrip_live_both_thd`)

**Purpose:** Sweeps threshold for srrip_live applied to both LLC and STLB simultaneously.

| Suite | Launch | Cluster dir | Mode | Status |
|---|---|---|---|---|
| DPC3 | 2026-05-14 | `dpc3_srrip_live_both_thd_addr_20260514_1932` | addr | ✅ in `results/cluster/` |
| Google, QMM | 2026-05-14 | `{suite}_srrip_live_both_thd_pc_20260514_1932` | PC | ✅ in `results/cluster/` |
| DPC3 | 2026-05-14 | `dpc3_srrip_live_both_thd_addr_20260514_2018` | addr | ✅ in `results/cluster/` |
| Google, QMM | 2026-05-14 | `{suite}_srrip_live_both_thd_pc_20260514_2018` | PC | ✅ in `results/cluster/` |

**Note:** Multiple runs; use the most recent (2018) ones.

---

## ipv_live_both Threshold (`ipv_live_both_thd`)

**Purpose:** Sweeps threshold for ipv_live applied to both LLC and STLB simultaneously.

| Suite | Launch | Cluster dir | Mode | Status |
|---|---|---|---|---|
| DPC3 | 2026-05-17 | `dpc3_ipv_live_both_thd_addr_20260517_2217` | addr | ✅ in `results/cluster/` |
| Google, QMM | 2026-05-17 | `{suite}_ipv_live_both_thd_pc_20260517_2218` | PC | ✅ in `results/cluster/` |

**Plot command:** `plot_srrip_live_thd.py --thd-prefix ipv_live_both`

---

## STLB Replacement Policy (`stlb_policy`)

**Script:** `scripts/submit/sweep_stlb_policy.sh`
**Purpose:** Apply liveness-aware replacement policies to the STLB.
**Configs:** `lru`, `stlb_lru_mid`, `stlb_srrip`, `stlb_srrip_live`

| Suite | Launch | Cluster dir | Mode | Status |
|---|---|---|---|---|
| DPC3, Google, QMM | 2026-05-13 | `{suite}_stlb_policy_20260513_0915` | addr | ✅ in `results/` |
| DPC3, Google, QMM | 2026-05-13 | `{suite}_stlb_policy_pc_20260513_0916` | PC | ✅ in `results/` |
| GAP, GMS, Ligra, ML | 2026-05-23 | `{suite}_stlb_policy_20260523_1345` | addr | ✅ complete (ML pending) |
| DPC3 | 2026-05-23 | `dpc3_stlb_policy_20260523_1346` | addr | ⏳ still running |
| GAP, GMS, Ligra, ML | 2026-05-23 | `{suite}_stlb_policy_pc_20260523_1529` | PC | ⏳ running (jids 1402937–1952) |

**Plot command (combined):**
```bash
python3 scripts/analysis/plot_srrip_live_thd.py \
  --stlb-dirs <stlb_policy dirs per suite> \
  --labels <suite labels> \
  --out results/plots/stlb_policy/stlb_policy_all.png
```

---

## STLB srrip_live Threshold Sweep (`stlb_thd`)

**Script:** `scripts/submit/sweep_stlb_thd.sh`
**Purpose:** Find optimal liveness threshold for srrip_live on the STLB.
**Configs:** `stlb_srrip_live_thd1`, `thd2`, `thd4`, `thd8`, `thd16`

| Suite | Launch | Cluster dir | Mode | Status |
|---|---|---|---|---|
| DPC3, Google, QMM | 2026-05-14 | `{suite}_stlb_thd_20260514_0025` | addr | ✅ in `results/` |
| DPC3, Google, QMM | 2026-05-14 | `{suite}_stlb_thd_pc_20260514_0025` | PC | ✅ in `results/` |
| GAP, GMS, Ligra, ML | 2026-05-20 | `{suite}_stlb_thd_20260520_0826` | addr | ✅ in `results/` |
| GAP, GMS, Ligra, ML | 2026-05-20 | `{suite}_stlb_thd_pc_20260520_0826` | PC | ✅ in `results/` |
| GAP, GMS, Ligra, ML | 2026-05-23 | `{suite}_stlb_thd_20260523_1345` | addr | ⏳ running (supersedes 0520) |
| GAP, GMS, Ligra, ML | — | — | PC | ❌ not yet submitted |

**Plot command (combined addr):**
```bash
python3 scripts/analysis/plot_srrip_live_thd.py \
  --stlb-thd-dirs <stlb_thd dirs per suite> \
  --stlb-pol-dirs <stlb_policy dirs per suite> \
  --labels <suite labels> \
  --out results/plots/stlb_thd/stlb_thd_all_addr.png
```

---

## STLB ipv_live Threshold Sweep (`stlb_ipv_live_thd`)

**Script:** `scripts/submit/sweep_srrip_live_thd.sh` with `--stlb-thd-prefix` / different binary
**Purpose:** Find optimal threshold for ipv_live on the STLB.
**Configs:** `stlb_ipv_live_thd1`, `thd2`, `thd4`, `thd8`, `thd16`

| Suite | Launch | Cluster dir | Mode | Status |
|---|---|---|---|---|
| DPC3 | 2026-05-16 | `dpc3_stlb_ipv_live_thd_addr_20260516_0902` | addr | ✅ in `results/` |
| Google, QMM | 2026-05-16 | `{suite}_stlb_ipv_live_thd_pc_20260516_0902` | PC | ✅ in `results/` |
| GAP, GMS, Ligra, ML | 2026-05-20 | `{suite}_stlb_ipv_live_thd_addr_20260520_0827` | addr | ✅ in `results/` |
| GAP, GMS, Ligra, ML | 2026-05-20 | `{suite}_stlb_ipv_live_thd_pc_20260520_0827` | PC | ✅ in `results/` |

**Plot command:**
```bash
python3 scripts/analysis/plot_srrip_live_thd.py --thd-prefix stlb_ipv_live \
  --stlb-thd-dirs <stlb_ipv_live_thd dirs> \
  --stlb-pol-dirs <stlb_policy dirs> \
  --labels <suite labels> \
  --out results/plots/stlb_ipv_live_thd/stlb_ipv_live_thd_addr_all.png
```

---

## PC-Indexed and Merged Bypass Prediction (`pc_bypass`)

**Script:** `scripts/submit/sweep_pc_bypass.sh`
**Purpose:** Compare addr-indexed, PC-indexed, and merged (STLB+LLC) bypass history tables.
**Configs:** `lru_baseline`, `addr_pred`, `pc_pred`, `merged_pred`

| Suite | Launch | Cluster dir | Status |
|---|---|---|---|
| DPC3, GAP, Google, ML, MAZ, QMM | 2026-05-22 | `{suite}_pc_bypass_20260522_0101` | ✅ in `results/` |
| GMS, Ligra | 2026-05-22 | `{suite}_pc_bypass_20260522_1958` | ✅ in `results/` |

**Plot command:**
```bash
python3 scripts/analysis/plot_pc_bypass.py \
  results/{suite}_pc_bypass_20260522_0101 ... \
  --labels <suite labels> --out results/plots/pc_bypass/pc_bypass.png
```

---

## PFQ Gate Role (`pfq_gating`)

**Script:** `scripts/submit/sweep_pfq_gating.sh`
**Purpose:** Study whether requiring a PFQ hit to activate cbPred helps. Three conditions: gate always on, no gate (bconf alone), EMA-adaptive gate.
**Configs:** `lru_pred`, `lru_pred_no_pfq`, `lru_pred_adaptive`

| Suite | Launch | Cluster dir | Status | Notes |
|---|---|---|---|---|
| DPC3 | 2026-05-21 | `dpc3_pfq_gating_20260521_0014` | ✅ in `results/` | THD=30, all traces |
| Google, QMM, GAP, GMS, Ligra, ML | 2026-05-21 | `{suite}_pfq_gating_20260521_0015` | ✅ in `results/` | THD=30, all traces |
| All 7 | 2026-05-25 | `{suite}_pfq_gating_20260525_0247` | ✅ in `results/` | THD=50, all traces, jids 1403008–1403028 |
| All 7 | 2026-05-25 | `{suite}_pfq_gating_20260525_0940_sel` | ⏳ running | THD=5 (low-rate drop), --selected (paper workloads only), jids 1403029–1403049 |

**Note:** Mazumdar not submitted. THD=5 run uses `--selected` (top-4 workloads per suite matching paper Figs 1–2). Use `_sel` dirs once complete.

**Plot command:** No dedicated script yet. Use:
```bash
python3 scripts/analysis/plot_policy_comparison.py <pfq_gating_dir> \
    --baseline lru_pred --out results/plots/pfq_gating/{suite}_pfq_gating
```

---

## LRU vs LFU History Tables (`repl_pol`)

**Script:** `scripts/submit/sweep_repl_pol.sh`
**Purpose:** Compare full-key LRU vs LFU replacement in the bypass predictor history tables, with and without the PFQ gate, vs. the hashed-table baseline.
**Configs:** `lru_baseline`, `hash_pred`, `lru_pred`, `lfu_pred`, `lru_pred_no_pfq`, `lfu_pred_no_pfq`

| Suite | Launch | Cluster dir | Status |
|---|---|---|---|
| All 8 suites | 2026-05-22 | `{suite}_repl_pol_20260522_0722` | ✅ in `results/` |

**Note:** Earlier runs (0954, 0102) are superseded by 0722.

**Plot command:**
```bash
python3 scripts/analysis/plot_policy_comparison.py results/{suite}_repl_pol_20260522_0722 \
    --baseline lru_baseline --out results/plots/repl_pol/{suite}_repl_pol
```

---

## PFQ Size Scaling (`queue_size`)

**Script:** `scripts/submit/sweep_queue_size.sh`
**Purpose:** Study how PFQ capacity affects bypass rates and IPC.
**Configs:** `baseline`, `pfq_8`, `pfq_64`, `pfq_inf`

| Suite | Launch | Cluster dir | Status | Notes |
|---|---|---|---|---|
| DPC3, Google, QMM | 2026-05-15 | `{suite}_queue_size_20260515_0145` | ✅ in `results/cluster/` | 39 configs (large sweep) |
| DPC3, QMM | 2026-05-15 | `{suite}_queue_size_20260515_1405` | ✅ in `results/cluster/` | 25 configs |
| Google | 2026-05-16 | `google_queue_size_20260516_0912` | ✅ in `results/cluster/` | 25 configs |
| DPC3, Google, QMM, GAP, GMS, Ligra, ML | 2026-05-21 | `{suite}_queue_size_20260521_0106` | ✅ in `results/` | 4 configs (baseline/pfq_8/pfq_64/pfq_inf) |
| GAP, GMS, Ligra, ML | 2026-05-23 | `{suite}_queue_size_20260523_1346` | ⏳ running | 4 configs (pfq_inf pending) |

**Plot command:**
```bash
python3 scripts/analysis/plot_queue_size_sweep.py results/{suite}_queue_size_YYYYMMDD_HHMM \
    --out-dir results/plots/queue_size/
```

---

## Cache and TLB Size Sensitivity (`cache_size`)

**Script:** `scripts/submit/sweep_cache_size.sh`
**Purpose:** Check liveness distribution and DoA/STLB correlation with LLC, L2C, STLB, DTLB, ITLB at half and double their default sizes.
**Configs:** `baseline`, `llc_half`, `llc_double`, `l2c_half`, `l2c_double`, `stlb_half`, `stlb_double`, `dtlb_half`, `dtlb_double`, `itlb_half`, `itlb_double`

| Suite | Launch | Cluster dir | Status |
|---|---|---|---|
| DPC3, Google, QMM | 2026-05-11 | `{suite}_cache_size_20260511_2342` | ✅ in `results/` |
| GAP, GMS, Ligra, ML | 2026-05-23 | `{suite}_cache_size_20260523_1346` | ⏳ running |

**Plot command:**
```bash
python3 scripts/analysis/plot_cache_size_study.py results/{suite}_cache_size_YYYYMMDD_HHMM \
    --out results/plots/cache_size/
```

---

## IPV-Live Rewrite Validation & Historical Duel Reconstruction (2026-07-06)

**Context:** `replacement/ipv_live/ipv_live.cc` was rewritten as a true k-way permutation IPV
(Jiménez MICRO 2013) on branch `fix-ipv-states`, replacing a broken 4-state RRPV hack.
`bin/champsim_ipv_live` on Castillo was **stale** (built 2026-07-05 21:38, before the
rewrite commits at 2026-07-06 14:55) until it was rebuilt locally and redeployed via scp
at **2026-07-06 20:47**. Any batch submitted before that timestamp ran the OLD broken
mechanism regardless of what vectors/env-vars it was given — confirmed by hand-running
the pre-fix Castillo binary and comparing to the post-fix local binary with identical env
vars (dueling block present locally, absent on Castillo pre-fix).

**Scripts:** `scripts/submit/submit_ipv_designs.sh` (wave1/wave2 base-vector study),
`scripts/submit/submit_old_equiv.sh` (old_equiv + old_flat unguided-IPV control),
`scripts/submit/submit_ipv_hist_duel.sh` (historical cfgA/ilB set-dueling reconstruction).
Config: THD_DOA=8/THD_DEAD=2, 50M warmup/50M sim, 251 traces (dpc3 95 + gap 9 + ligra 17 +
gms 11 + google 43 + qmm 45 + ml 31), Config-C 2MB LLC.

| Launch | Cluster dir | Purpose | Binary | Status |
|---|---|---|---|---|
| 2026-07-06 01:40/05:45 | `ipv_designs_wave1_20260706_0140` / `wave2_20260706_0545` | GIPPR vs MDPP base-vector study, 8 arms × 7 suites | stale (pre-fix) | ✅ completed, but **INVALID** — wrong mechanism |
| 2026-07-06 14:10 | `ipv_flat_bases_20260706_1410` (mdpp_flat) | unguided IPV/MDPP baseline | stale (pre-fix) | ✅ completed, **INVALID** |
| 2026-07-06 14:23 | `ipv_old_equiv_20260706_1423` (old_equiv + old_flat) | unguided IPV baseline (MA-only vector) | stale (pre-fix) | ✅ completed, **INVALID** |
| 2026-07-06 20:41 | `ipv_hist_duel_20260706_2041` | 1st historical-duel reconstruction attempt | stale (pre-fix) | cancelled after bug found, **INVALID** |
| 2026-07-06 20:47 | `ipv_hist_duel_20260706_2047` | 2nd attempt, correct binary | **correct** | cancelled mid-run (blanket qdel mistake) — ~20/95 dpc3 traces completed with valid dueling before being killed; not used, superseded by 2058 |
| 2026-07-06 20:55 | `ipv_designs_wave1_20260706_2055` / `wave2_20260706_2055` | rerun of base-vector study, correct binary | **correct** | killed before any task started (unauthorized relaunch) — **0 output**, needs resubmitting if still wanted |
| 2026-07-06 20:56 | `ipv_flat_bases_20260706_2056` (mdpp_flat) | rerun of MDPP baseline, correct binary | **correct** | killed before any task started — **0 output** |
| **2026-07-06 20:58** | **`ipv_hist_duel_20260706_2058`** | historical cfgA/ilB duel reconstruction | **correct** | **✅ completed, 251/251, VALID** — the one usable result from this whole session. Pooled +2.55% vs SRRIP (caveated: SRRIP baseline is 50M/100M, mismatched instruction count) |
| 2026-07-06 23:38 | `ipv_old_flat_20260706_2338` | unguided-IPV baseline, correct binary, matches hist_duel's 50M/50M | **correct** | submitted, **still stuck in `qw` as of 2026-07-07 01:2x — Castillo's all.q is cluster-wide unreachable (all 244 slots, all 41 exec hosts flagged `u`), confirmed not job-specific. Jobs are correctly queued; will run once the outage clears. Do NOT resubmit — would just duplicate the same queued work.** |

**Bottom line:** only `ipv_hist_duel_20260706_2058` is both complete and valid. Everything
else needs re-running against the corrected binary before its numbers can be trusted.
The direct IPV-Live/IPV comparison (the one that actually matters, not vs-SRRIP) is
blocked on `ipv_old_flat_20260706_2338` finishing.

---

## Mostly-dead removal (branch `remove-mostly-dead`, 2026-07-08)

Merged `blackbox-phase-reset-fix` into `main` (fast-forward, `f5d4138e168c`), then
branched `remove-mostly-dead` off `main` to delete the 3-way DoA/mostly-dead/mostly-alive
classification entirely from `lru_live.cc`, `srrip_live.cc`, `ipv_live.cc`, and
`HistTable`/`PCPartitionedTable` in `cache.h`/`cache.cc` — collapsed to a flat scheme:
+1 score on every DoA eviction, reset to 0 on any accessed eviction, single `THD_DOA`
threshold, no scoring-mode zoo (`SCORING_MODE` removed), no `HistTable::Policy::TIERED`.
Rebuilt both `champsim_maz_policies.json` and `champsim_config_redwoodcove.json` configs
locally (0 errors), smoke-tested 5 binaries on a local trace.

| Launch | Cluster dir | Purpose | Status |
|---|---|---|---|
| 2026-07-08 ~16:03 (local) | — | `blackbox_run_cluster.sh generate`, 60 scenarios (3 policies × 5 conditions × 4 traces), regenerating `test/blackbox/expected/*.out` against the MD-free binaries | ran to completion, 60/60 finished; committed by the script itself |
| 2026-07-08 ~17:19 (local) | — | `blackbox_run_cluster.sh` (verify), confirming the regenerated references reproduce cleanly | running, 0 FAIL so far |

---

## Still Pending / Not Yet Submitted

- **All suites — hist_size sweep** (`sweep_hist_size.sh`): large pHIST×bHIST grid with LRU/LFU/hashed; not yet submitted for any suite
- **pc_bypass AND/OR match variants** (`pc_addr_pred`, `pc_or_addr_pred`): designed in `sweep_pc_bypass.sh` comment but not in configs array; not yet submitted
- **STLB policy / STLB thd — PC mode for new suites** (GAP, GMS, Ligra, ML): not yet submitted
- **srrip_live_bypass for new suites** (GAP, GMS, Ligra, ML): not yet submitted

Note: Mazumdar traces are NOT run for new experiments.
