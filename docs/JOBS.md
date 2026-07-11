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
| 2026-07-08 ~17:19 (local) | — | `blackbox_run_cluster.sh` (verify), confirming the regenerated references reproduce cleanly | **contaminated**: `git checkout main` + merge ran in this same working dir while the poll loop was mid-diff against it, so all 20 `lru_*` scenarios read a briefly-reverted `expected/` and were falsely FAILed/cancelled. No real regression (confirmed post-merge file content was correct). Cancelled the leftover jobs and relaunched (jids 1409914–1409973) |
| 2026-07-08 18:06 (local) | jids 1409914–1409973 | Clean re-verify from stable `main`, no concurrent git ops this time. The local polling script itself got killed by session teardown mid-run, but the cluster jobs ran to completion independently (SGE doesn't depend on the poller staying alive) | **60/60 PASS** — pulled `test_outputs` from Castillo directly and diffed by hand against `expected/` (mod the wall-clock line) since the poller was dead; byte-identical |

## DoA counter-trace diagnostic (same branch, 2026-07-08)

Follow-up investigation into *why* a low `THD_DOA` is optimal: added `DOA_COUNTER_TRACE=1`
to `HistTable`'s eviction path in `cache.cc`/`cache.h` — logs every LLC/STLB repl_hist score
update (ROI only) to `doa_counter_trace_<NAME>.csv` as
`cycle,pc,addr,evict_class,old_score,new_score`, so the full per-key counter time series can
be reconstructed offline: does a PC's score climb once and saturate (rare resets), or
oscillate; and within a PC, which block addresses actually drive the score. Zero cost when
disabled. Deployed as a separate binary (`champsim_lru_live_doatrace`) rather than
overwriting `champsim_lru_live`, specifically to avoid any risk to the concurrently-running
black-box regeneration job.

| Launch | Cluster dir | Purpose | Status |
|---|---|---|---|
| 2026-07-08 15:33 | `doa_trace_debug/{pr,cactus,bwaves,qmm}` (jids 1409778–1409781) | First 4 representative traces (same as black-box), THD_DOA=6, BHIST_MODE=pc, LRU_LIVE_DOA_INS=2n3, 50M warmup/100M sim | completed |
| 2026-07-08 15:41 | `doa_trace_debug/{gap,ligra,gms,ml,qmm,dpc3}_*` (jids 1409782–1409853, 72 jobs) | Broadened to fill the cluster (~75 slots): **all** of gap (9), ligra (17), gms (11), sampled ml (11), qmm (12), dpc3 (12). Same binary/env/scale. Submitted via `submit_doatrace_broad.sh` (ad hoc, not committed — lives only in the scratchpad) | completed — 76 files, 126.2M rows total, 5.9GB. 3 dpc3 traces (600.perlbench, 641.leela, 648.exchange2) produced zero eviction rows: `repl_hist: unbounded (0 entries)`, `Insert mix DoA=0.0%` in their logs — their working sets fit entirely in the 2MB LLC for the sampled ROI window, not a bug |
| 2026-07-08 18:24 | job 1409974 (`doa_summarize`) | Too large to pull raw (5.9GB); aggregate in place with `awk` (`doa_summarize.awk`, ad hoc/scratchpad) into per-trace `summary.txt`: reset-streak histogram (score value at each alive-eviction reset) + per-PC detail (doa_count, reset_count, max_score, top_addr_doa_count) | **errored** (Eqw) — relative `-o` log path resolved against `$HOME` instead of `ChampSim-dev/` (no `-wd` set), so it couldn't open the log file. Never actually ran |
| 2026-07-08 18:25 | job 1409975 (`doa_summarize`) | Same, resubmitted with absolute `-o` path and `-wd` set | **completed** — full analysis done inline in conversation (streak-length + per-suite/per-PC breakdown); see summary below |

**Analysis conclusion**: reset-streak histogram (6.6M resets) shows 39.6%/21.5%/12.5%/7.7%
at streak lengths 1/2/3/4; 46% of active PCs (doa_count>=5) never reset for the whole run.
Per-suite split explains the established optimal thresholds (`docs/SPEEDUP_SUMMARY.md`):
GAP/Ligra (THD=1) win via *abundance* (tens-of-thousands of DoA evictions per PC swamp
occasional oscillation); QMM (THD=4) is driven by *scarcity* (median PC seen exactly once
in the whole run, so there's rarely a second chance to wait for); DPC3/SPEC (THD=8-16) has
the lowest per-PC activity plus a real oscillating tail, making wrong calls costliest.
Top-address concentration is low (4-14% median) almost everywhere, so per-PC aggregation
isn't masking one hot address in general.

## Random DoA-insertion experiments on QMM (same branch, 2026-07-08)

Two new opt-in `HistTable` mechanisms, built to test whether removing the "free pass"
every key gets before any DoA evidence exists helps QMM specifically (per the scarcity
finding above):
  - **`DOA_DEFAULT_PCT=<0-100>`**: read-time override — that % of never-seen keys classify
    as DoA on first sight instead of the default alive. No persistent state touched.
  - **`DOA_FORCE_PCT=<0-100>`**: write-time override — forces an existing key's persistent
    score up to max(THD_DOA, BYPASS_THD), once per candidate LLC fill under
    `LIVENESS_BYPASS=1`, so the same event sees the forced value for bypass, insertion, and
    later promotion alike (a decoupled subset of keys from DOA_DEFAULT_PCT).

Both compile clean, smoke-tested locally on pagerank (small but real effect: DOA_FORCE_PCT=50
raised LLC bypasses from 93182→95182).

| Launch | Cluster dir | Purpose | Status |
|---|---|---|---|
| 2026-07-08 19:06 | `doa_random_qmm/{A,B}_*` (jids 1410041/1410042-1410053 and preceding, 78 jobs total) | 13 QMM traces (same as counter-trace study) × established config (THD_DOA=4, BHIST_MODE=pc, LRU_LIVE_DOA_INS=2n3) × 3 arms each: Experiment A = base/DOA_DEFAULT_PCT=25/50 (no bypass); Experiment B = base/DOA_FORCE_PCT=25/50 (LIVENESS_BYPASS=1, BYPASS_THD=4). Submitted via `submit_doa_random_qmm.sh` (ad hoc, scratchpad only) | **completed, 78/78, REFUTED both ideas**: A (`DOA_DEFAULT_PCT`) 25%→-2.10% IPC, 50%→-5.15%; B (`DOA_FORCE_PCT`) 25%→-6.48%, 50%→-7.43% — geomean IPC vs each arm's own baseline. LLC miss rate climbs monotonically with the pct in both (A: 5.87%→7.07%; B: 6.29%→8.84%; B's bypass count roughly doubles), confirming the mechanism: forced/defaulted DoA calls are wrong often enough to cause real extra misses, not just bookkeeping churn. One severe outlier: B on `srv_575` at 50% — IPC -34.2%, miss rate 8.6%→25.8%, bypasses 108K→601K. Conclusion: QMM's cold-start "free pass" is not free — it protects blocks that really do get reused; blind random pessimism (no recurrence signal) mostly just injects false positives. Investigation closed; did not pursue `BYPASS_RECHECK_MODE` fix for B since the core hypothesis already failed. |

Both `DOA_DEFAULT_PCT` and `DOA_FORCE_PCT` remain in the code as opt-in, zero-cost-when-off
mechanisms (in case a future, recurrence-informed variant is worth trying), but this specific
"random/blind" instantiation is a dead end for QMM.

**Clarifying control** (reused from `B_base`, no new jobs): plain earned-evidence bypass
(`LIVENESS_BYPASS=1, BYPASS_THD=4`, no randomization) vs the true no-bypass baseline
(`A_base`) — **+1.98% geomean IPC, positive on all 13 traces individually** (+1.2% to +3.0%,
no outliers), despite LLC miss rate rising too (5.87%→6.29%, 99,291 avg bypasses). So
bypassing itself isn't what broke Experiment B — bypassing *correctly* is a real, consistent
win here even though it costs some miss rate. What failed was bypassing on random assignment
instead of earned evidence: `DOA_FORCE_PCT` roughly doubled the bypass count (163,908–203,421)
and pushed miss rate to 7.96–8.84%, which is where it flips from a net win to a net loss. Not
a small tweak on top of a working mechanism — a different, worse regime entirely.

(Note: a dedicated, more-conservative `BYPASS_THD` sweep — e.g. 8/16/32, mirroring the old
`sweep_bypass_allsuites.sh` design — was considered but not run; the existing sweep results
for that question, `bypass_allsuites_20260610_2312`/`bypass_only_allsuites_20260611_1200`,
are the ones already flagged elsewhere as contaminated by `champsim_srrip_live_hrp`.)

## Plain bypass on Ligra (same branch, 2026-07-08)

Testing the same plain, earned-evidence bypass (no randomization) that won on QMM, on Ligra
instead — its own established optimal threshold (THD_DOA=1, per `docs/SPEEDUP_SUMMARY.md`),
all 17 traces. Not a guaranteed win the way QMM was: `docs/FINDINGS.md` documents Ligra's
DoA blocks have a real 2-25%-per-trace reuse rate, and SRRIP-Live's `ins@3` (aggressive but
less drastic than bypass — still installs the block, just at immediate-eviction RRPV) already
regressed up to -5.2% vs SRRIP there specifically because of that reuse. Bypass never installs
the block at all, so if anything it should be more exposed to that risk, not less.

| Launch | Cluster dir | Purpose | Status |
|---|---|---|---|
| 2026-07-08 ~20:20 | `doa_random_qmm/L_{base,byp}_*` (jids 1410080-onward, 34 jobs) | 17 Ligra traces × base (no bypass) / `LIVENESS_BYPASS=1,BYPASS_THD=1`, THD_DOA=1, BHIST_MODE=pc, LRU_LIVE_DOA_INS=2n3, 50M warmup/100M sim. Submitted via `submit_bypass_ligra.sh` (ad hoc, scratchpad only) | submitted, running |
| 2026-07-08 ~20:35 | `doa_random_qmm/L{A,B}_*` (jids 1410148-onward, 68 jobs) | Same random-insertion experiments as QMM, now on Ligra: LA_ddp25/50 (`DOA_DEFAULT_PCT`, baseline=`L_base`), LB_dfp25/50 (`DOA_FORCE_PCT` under bypass, baseline=`L_byp`). Submitted via `submit_random_ligra.sh` (ad hoc, scratchpad only) | **93/102 completed**, results below |
| 2026-07-08 ~20:55 | `doa_random_qmm/LB_dfp100_*` (jids 1410156-1410172, 17 jobs) | "Bypass without checking" control: `DOA_FORCE_PCT=100` forces every fill's score to the bypass bar before `classify()` runs, so every valid eviction bypasses unconditionally regardless of real evidence. Baseline=`L_byp` (informed bypass). Submitted via `submit_bypass_all_ligra.sh` (ad hoc, scratchpad only) | submitted, running |

**Plain bypass results (L_byp vs L_base, 16/17 traces)**: +34.95% geomean IPC — much larger
than QMM's +1.98%. LLC miss rate rises sharply too (59%→81% avg; several traces hit
99.99-100%, meaning almost everything bypasses). Consistent with the counter-trace finding
that Ligra's PCs are overwhelmingly persistent 100%-DoA generators with near-zero resets —
at THD_DOA=1 nearly everything qualifies, and skipping LLC install/evict machinery for
genuinely one-touch traffic frees the LLC for the reused minority. Not universal: 3/16 traces
regressed (`PageRank` 0.60x, `Triangle` 0.78x, `MIS_21250M` 0.86x) — matches FINDINGS.md's
documented 2-25%-per-trace real DoA reuse rate on Ligra.

**Randomization still fails here too (15/17 traces)**: `DOA_DEFAULT_PCT` -2.50%/-3.66%
(25%/50% vs L_base); `DOA_FORCE_PCT` -6.09%/-4.56% (25%/50% vs L_byp, the already-winning
bypass baseline). Same conclusion as QMM: degrading the informed check with randomness hurts
even when the informed check itself is a massive win, not just when it's a modest one.

Next step: pull IPC + LLC miss rate + bypass count per trace for all remaining Ligra jobs once
done, geomean vs each arm's own baseline, same methodology as the QMM comparison above.

## Bug found + fixed: DOA_FORCE_PCT was coupled to LIVENESS_BYPASS (same day)

`maybe_force_doa()` was gated behind `liveness_bypass` and forced scores to
`max(THD_DOA, BYPASS_THD)`, so every `DOA_FORCE_PCT` result above (QMM -6.48%/-7.43%,
Ligra -6.09%/-4.56%) actually tested "force interacting with bypass," not the original ask
(force affecting insertion/promotion on its own, independent of bypass). Fixed: moved the
force call to right before `classify_block_liveness()`, unconditional on bypass, forcing to
plain `THD_DOA`. Rebuilt, smoke-tested (confirmed effect present with no `LIVENESS_BYPASS`
set at all), committed (`0aa2d48e1162`), binary redeployed to Castillo.

| Launch | Cluster dir | Purpose | Status |
|---|---|---|---|
| 2026-07-08 ~22:25 | `doa_random_qmm/F_qmm_dfp{25,50}_*` (26 jobs) + `F_ligra_dfp{25,50}_*` (34 jobs), jids 1410173-1410232 | Corrected `DOA_FORCE_PCT` rerun, no bypass: 13 QMM traces (THD_DOA=4, baseline=`A_base`) + 17 Ligra traces (THD_DOA=1, baseline=`L_base`). Submitted via `submit_dfp_fixed.sh` (ad hoc, scratchpad only) | **QMM complete (13/13): still negative but smaller than the buggy version — dfp25 -1.70% (was -6.48%), dfp50 -4.89% (was -7.43%). Ligra 13/17 so far: dfp25 -1.87%, dfp50 -9.86%.** Confirms the corrected conclusion holds (forcing without evidence still hurts), just less severely than when coupled to bypass (bypass is unrecoverable; distant insertion isn't) |

**Recheck experiment on Ligra** (jids 1410233-onward, 17 jobs, `R_recheck_*`): `L_byp` config
(THD_DOA=1, LIVENESS_BYPASS=1, BYPASS_THD=1) + `BYPASS_RECHECK_MODE=backoff,
BYPASS_RECHECK_INTERVAL=32, BYPASS_RECHECK_CAP=256` (code defaults) — tests whether
periodically letting a bypassed key through as a real fill (to observe reality, not overwrite
scores) recovers the 3 traces that regressed under plain bypass (`PageRank` 0.60x, `Triangle`
0.78x, `MIS_21250M` 0.86x) without costing the traces where plain bypass is winning big.
Submitted via `submit_recheck_ligra.sh` (ad hoc, scratchpad only). Baseline for comparison:
`L_byp`.

Next step: finish both reruns, compare vs A_base/L_base (DOA_FORCE_PCT) and vs L_byp
(recheck), then add forced-key outcome tagging to DOA_COUNTER_TRACE (measure the force
mechanism's real false-positive rate directly instead of inferring it from IPC/miss deltas).

## Bypass threshold, one value higher than THD_DOA, across 6 suites (2026-07-09)

Random-insertion and random-recheck mechanisms both washed out or hurt (see above); the
remaining ask was to test **one** bypass threshold higher than plain THD_DOA (not a sweep),
across a varied trace set since bypass suitability clearly varies a lot by suite (QMM
modest +1.98%, Ligra massive +34.95% but 3 regressing traces).

4 representative traces each, from dpc3/gap/gms/ligra/ml/qmm (24 traces total), each suite
at its own established THD_DOA (dpc3=8, gap=1, gms=4, ligra=1, ml=16, qmm=4), 2 arms per
trace: no-bypass base, BYPASS_THD=2x that suite's THD_DOA.

**Correction**: originally launched as a 4-arm 1x/2x/4x sweep (96 jobs) — that was a
misread of the request (explicitly *not* a sweep, one higher value). Cancelled the 1x/4x
arms (48 jobs, jids listed in the cancel command) once caught; kept base+2x only (48 jobs).

| Launch | Cluster dir | Purpose | Status |
|---|---|---|---|
| 2026-07-09 ~00:10 | `doa_random_qmm/T_{suite}_{base,byp2x}_*` (48 jobs, jids 1410250-1410345, thinned from 96) | dpc3: mcf/omnetpp/xalancbmk/fotonik3d. gap: bc-0/cc-13/bfs-10/sssp-10. gms: triangle_count_117/k_clique_edge_367/maxclique_3852/k_clique_node_236. ligra: PageRank/Triangle/BFSCC_15500/MIS_15750 (2 regressing + 2 winning traces from the earlier bypass result). ml: llama110M/biogpt/rwkv/whisper. qmm: srv_12/575/128/21. Submitted via `submit_bypass_thd_multisuite.sh` (ad hoc, scratchpad only) | **completed, 48/48**: dpc3 +12.99%, gap +10.98%, ligra +34.56% (confirms 1x result holds at 2x; also fixes `PageRank` specifically — 1.186x — but not `Triangle` — 0.777x, unchanged), qmm +1.81%, gms +0.08% and ml +0.32% (bypass barely matters either way for those two) |

**Final results, all 3 experiments complete:**
- **`DOA_FORCE_PCT` corrected (full data)**: still refuted — QMM -1.70%/-4.89% (25%/50%),
  Ligra -1.73%/-8.63% (16/17 traces). Confirms forcing without evidence hurts regardless of
  whether it's coupled to bypass or not.
- **Bypass recheck on Ligra** (`BYPASS_RECHECK_MODE=backoff`, jids 1410233+, 17 jobs,
  vs `L_byp`): **+1.26% geomean, 16/17 traces** — the first addition on top of plain bypass
  that actually helped. Recovered `PageRank` from 0.60x (vs no-bypass) to ~1.14x — a full
  flip from big loser to modest winner — and improved `Triangle` from 0.78x to ~0.88x
  (still a regression, smaller). Cost: small dips (2-13%) on traces already winning under
  plain bypass, since recheck occasionally forces a real probe fill even when bypass was
  already correct. Net positive despite that cost.
- **Bypass at 2x THD_DOA, 6 suites**: see table row above.

Next step: build the PC temporal-behavior bucketing analysis, reprocessing the same raw
counter-trace CSVs with a new awk pass — classifies each PC by reset *position* in its own
timeline, not just count: always-DoA / early-only / late-only / oscillating-throughout.
First submitted as job 1410346, a single job looping over all 76 traces sequentially
(same pattern as the earlier `doa_summarize` job) — cancelled before it started once asked
why it wasn't parallelized (each trace's pass is fully independent). Resubmitted as 76
separate `bkt_<trace>` jobs (jids 1410347-1410422) via `submit_bucket_parallel.sh`.

**Per-(PC,address) analysis, GAP+Ligra only (26 jobs, `as_<trace>`)**: `doa_addr_summary.awk`
replays the same score rule keyed by `(pc,addr)` instead of `pc`, over the existing raw
CSVs. Pooled by address count: gap 91.6% always-doa addresses / 8.4% has-reset; ligra 99.1%
/ 0.9% — most individual addresses are simple and predictable; a PC gets flagged
"oscillating" because of a small reused-address minority, not because most of its addresses
are unpredictable.

**Native DOA_ADDR_SUMMARY diagnostic** (`inc/cache.h`/`src/cache.cc`, commit `11c90fc47866`):
built the same (PC,address) replay directly into ChampSim instead of post-processing, since
post-processing raw CSVs doesn't scale to QMM/ML/DPC3's address counts. Prints an aggregated
per-PC summary (`n_addr, always_doa, has_reset, doa_total`) at `end_phase`, gated by
`DOA_ADDR_SUMMARY=1`, zero cost when off. Smoke-tested locally, matches expected pattern.

| Launch | Cluster dir | Purpose | Status |
|---|---|---|---|
| 2026-07-09 ~15:40 | `doa_addrsum_debug/{suite}_*` (72 jobs, jids 1410449-1410520) | Same trace lists/config as the original counter-trace study (THD_DOA=6, all 6 suites), `DOA_ADDR_SUMMARY=1` instead of `DOA_COUNTER_TRACE=1`. Submitted via `submit_addrsum_allsuites.sh` (ad hoc, scratchpad only) | submitted, running |

Next step: pull the per-suite `always_doa`/`has_reset` address split for dpc3/gms/ml/qmm,
extending the gap/ligra numbers above to all 6 suites.

**Gap noted**: Google is a 7th suite in project scope (Mazumdar explicitly excluded from
new experiments) and has been missing from every analysis this session — skipped early on
for its nested per-site directory structure (`Google_Traces_v2/{site}/{site}_NNNN.champsim.gz`)
and never revisited. Confirmed 4 site traces exist (arizona/charlie/merced/tahoe, `_0000`),
added to the recheck experiment below at THD_DOA=4 (per `docs/SPEEDUP_SUMMARY.md`). Not yet
backfilled into the earlier bypass-2x-threshold or address-summary experiments.

## Bypass recheck, expanded to all 6 non-MAZ suites (2026-07-09)

Same `BYPASS_RECHECK_MODE=backoff` config validated on Ligra (+1.26%), now testing
gap/gms/dpc3/ml/google (4 traces each, `byp1x` + `byp1x+recheck`, since we don't have a
plain-bypass-without-recheck baseline for these yet) and qmm (recheck only, full 13-trace
set, reusing the existing `B_base` plain-bypass baseline).

| Launch | Cluster dir | Purpose | Status |
|---|---|---|---|
| 2026-07-09 ~16:05 | `doa_random_qmm/RC_{suite}_*` (53 jobs, jids 1410521-1410573) | gap/gms/dpc3/ml/google: byp1x + byp1x+recheck (8 jobs each suite). qmm: recheck only (13 jobs). Submitted via `submit_recheck_allsuites.sh` (ad hoc, scratchpad only) | **cancelled** — used individual `qsub -b y` calls with only 4 representative traces per suite, not the project's established `qsub -t` array convention with full suite counts. User called this out directly; resubmitted properly below. |

**Corrected**: resubmitted via the established convention — `scripts/submit/run_cs.sh`
(shared runner, picks trace by `SGE_TASK_ID`) + `qsub -t 1-N` arrays, matching the pattern
in `scripts/submit/lru_live_bypass.sh`. Full suite counts confirmed by `find`: gap=9,
ligra=17, gms=11, ml=31, qmm=45, dpc3=95, google=43 (251 total, not the 4-per-suite sample
used above). 3 arms: base (no bypass), byp1x (plain bypass), recheck (byp1x +
`BYPASS_RECHECK_MODE=backoff,BYPASS_RECHECK_INTERVAL=32,BYPASS_RECHECK_CAP=256`).

| Launch | Cluster dir | Purpose | Status |
|---|---|---|---|
| 2026-07-09 22:19 | `results/recheck_allsuites_20260709_2219/{base,byp1x,recheck}/{suite}` (21 array jobs, jids 1410574-1410594, 753 tasks total) | Per-suite established THD_DOA (gap=1, ligra=1, gms=4, ml=16, qmm=4, dpc3=8, google=4). Submitted via `submit_recheck_arrays.sh` (ad hoc, scratchpad only — should be moved into `scripts/submit/` if kept) | submitted, running |

Next step: geomean recheck vs byp1x per suite, see if the Ligra-style recovery pattern
(the earlier 17-trace-only Ligra result: +1.26%, PageRank 0.60x→~1.14x) generalizes across
all 7 suites at full trace counts.

---

## Data-quality finding: SRRIP-Live/SRRIP column in FINDINGS.md is contaminated (2026-07-10)

FINDINGS.md's cross-policy table (`LRU-Live/LRU`, `SRRIP-Live/SRRIP`, `IPV-Live/IPV`) cites
`bypass_allsuites_20260610_2312/*/repl_only` as the SRRIP-Live/SRRIP source. That directory
carries a `DO_NOT_USE.txt`: it ran `champsim_srrip_live_hrp` (not `champsim_srrip_live`), the
binary already flagged as a ~4% contaminated baseline. `lru_live_vs_base_*` and
`ipv_live_vs_base_*` (the other two columns) are clean, dedicated directories — only SRRIP-Live
was sourced from the contaminated one.

Recomputed SRRIP-Live/SRRIP from `*_thd_rebaseline_20260605_2316` (clean, per-suite established
θ, unweighted geomean — directional, not final):

| suite | LRU-Live/LRU | SRRIP-Live/SRRIP (FINDINGS, contaminated) | SRRIP-Live/SRRIP (clean recompute) |
|---|---|---|---|
| dpc3  | +4.80% | +2.25% | +2.11% |
| gap   | +3.82% | +2.05% | +4.03% |
| gms   | +0.38% | +1.28% | +0.04% |
| ligra | +2.95% | +1.53% | **−3.41%** |
| ml    | +2.37% | **+8.80%** | +1.75% |
| qmm   | +1.40% | +0.99% | **−0.29%** |

The "SRRIP-Live wins big on ML" headline (the strongest counter-example to the room-for-error
theory) shrinks from +8.80% to +1.75%, and LRU-Live now wins 5/6 suites (was 4/6). Ligra and
QMM flip sign entirely. **TODO: regenerate the full three-way table from a clean,
SimPoint-weighted, matching-config source before using it in the paper or in further analysis.**

## DOA_DECAY: soft decay instead of hard reset on alive eviction (2026-07-10)

Added `DOA_DECAY=<N>` (`inc/cache.h`/`src/cache.cc`): on an alive eviction, subtract N from the
score (floored at 0) instead of resetting to 0. Unset/default behaves identically to the
existing hard reset (sentinel = `int64_t max`, subtraction always floors to 0). Zero cost when
off. Built locally, no errors; local smoke test inconclusive (only local trace, pagerank, has
zero alive evictions in the tested window). Tests the hypothesis that if resets are rare (this
session's addr-summary finding), soft decay should show ~no benefit over hard reset. Not yet
run on cluster — pending scope confirmation (which θ_decay values, which suites).

## Full-suite DoA counter-sequence stats (2026-07-10)

Extends `doa_sequence.awk` (mean score, max score, mean/max peak-value-before-reset,
mean/max run-length between resets, per PC) from the earlier 76-trace sample
(`doa_trace_debug/`, uniform θ=6) to every trace of every suite, each at its own established
θ (gap=1, ligra=1, gms=4, ml=16, qmm=4, dpc3=8, google=4) — the actual production operating
point, not an arbitrary fixed value.

**Bug found + fixed before launch:** `scripts/submit/run_cs.sh` never `cd`s into the per-trace
`RUN_DIR` (it only redirects stdout/stderr there); `champsim_lru_live_doatrace` writes
`doa_counter_trace_{LLC,cpu0_STLB}.csv` to a fixed relative filename in its CWD. Run via
`run_cs.sh`'s shared `-wd`, parallel array tasks would clobber each other's CSVs. Wrote
`scripts/submit/run_cs_doatrace.sh`: resolves binary/trace to absolute paths, `cd`s into the
per-trace `RUN_DIR` before invoking the binary. Smoke-tested on 2 gap traces (jid 1410595,
held competing not-yet-started queued arrays via `qhold` so it would schedule next) — confirmed
distinct per-trace CSVs (142815 vs 142809 lines), nothing leaked to the shared root.

| Launch | Cluster dir | Purpose | Status |
|---|---|---|---|
| 2026-07-10 00:21 | `results/doa_seq_full_20260710_0021/{suite}` (7 array jobs, jids 1410596-1410602, 251 tasks total) | All traces, all 7 suites, per-suite established θ, `champsim_lru_live_doatrace`, `DOA_COUNTER_TRACE=1`, `BHIST_MODE=pc`, `LRU_LIVE_DOA_INS=2n3`, 50M/100M. Submitted via `submit_doa_seq_full.sh` (ad hoc, scratchpad only) | submitted, running |

Next step once complete: run `doa_sequence.awk` remotely on each trace's `doa_counter_trace_LLC.csv`
(raw CSVs are multi-GB at full scale — post-process in place, only pull back the compact
per-PC stat CSVs), aggregate per suite.

## LRU-Live cushion causal test (2026-07-10)

Direct, within-policy test of whether LRU-Live's edge over SRRIP-Live comes from its
graduated insertion cushion (room for a misclassified block to prove itself via a hit
before eviction), rather than comparing across policies (too many confounds at once).
Same binary (`champsim_lru_live`), same suite, same established θ — only
`LRU_LIVE_DOA_INS` changes: `2n3` (cushioned, DoA inserted at position 10/16) vs `lru`
(no cushion, DoA inserted at LRU end, same recovery window as SRRIP's ins@3). Plain
`champsim_lru` baseline rerun fresh in the same launch for self-consistent provenance
(avoids repeating the SRRIP-Live contamination mistake above). Prediction: if the theory
holds, `cfgB` (lru)'s edge over baseline should be much smaller than `cfgA` (2n3)'s, and
may regress on some suites — converging toward SRRIP-Live's observed fragility.

| Launch | Cluster dir | Purpose | Status |
|---|---|---|---|
| 2026-07-10 00:42 | `results/cushion_test_20260710_0042/{base,cfgA,cfgB}/{suite}` (21 array jobs, jids 1410603-1410623, 753 tasks total) | All traces, all 7 suites, per-suite established θ. Submitted via `submit_cushion_test.sh` (ad hoc, scratchpad only) | submitted, running |

`DOA_DECAY` deferred initially — cluster time prioritized for the cushion test above;
launched after. Not part of the counter-stats collection (that's purely observational),
it's a separate mechanism experiment testing whether the "resets are rare" finding has
an actionable consequence.

## DOA_DECAY test (2026-07-10)

Subtract a fixed amount from the score on an alive eviction (soft decay) instead of
hard-resetting to 0. Prediction, per the addr-summary finding (resets are rare, 0.08-8.36%
of addresses): should show ~no benefit, since there's little to smooth over. Reviewed the
implementation before launch (inc/cache.h/src/cache.cc): allocate-only-on-DoA preserved
(decay only applies to already-tracked keys), sentinel default (`int64_t max`) gives
byte-identical behavior to the old hard reset, both bounded/unbounded paths updated
consistently, `REPL_HIST_MERGED` path untouched (irrelevant here, not used in this test).
Local `champsim_lru_live` binary rebuilt today (contains `DOA_DECAY`) and transferred to
Castillo via the double-SSH `cat` pipe (scp fails through the abdet jump host) — confirmed
same size + `strings` match on the remote copy before launch; verified no in-flight
`cushion_test` tasks were disrupted by the overwrite (all still `qw` at the time).

`DOA_DECAY ∈ {1, 2}`, fixed (not θ-scaled, to avoid gap's θ=1 producing a degenerate
θ/2=0 decay that would never actually reset), vs `base` (established config, decay unset).

| Launch | Cluster dir | Purpose | Status |
|---|---|---|---|
| 2026-07-10 00:47 | `results/doa_decay_20260710_0047/{base,decay1,decay2}/{suite}` (21 array jobs, jids 1410624-1410644, 753 tasks total) | All traces, all 7 suites, per-suite established θ. Submitted via `submit_doa_decay.sh` (ad hoc, scratchpad only) | **cancelled — wrong θ, see below** |

## Threshold-provenance bug: `doa_seq_full`/`cushion_test`/`doa_decay` used stale θ from the old scoring system (2026-07-10)

The "established per-suite THD_DOA" (gap=1, ligra=1, gms=4, ml=16, qmm=4, dpc3=8, google=4)
used for all three launches above traces to two bad sources: (1) `docs/SPEEDUP_SUMMARY.md`,
cited in JOBS.md as the source for Ligra's θ=1, doesn't contain "THD_DOA" at all — it
documents `MID_THD=1` for the old 3-way `ipv_live` system, a different parameter on a
different policy; (2) the other candidate source, `results/lru_live_thd_duel_20260627`,
ran under `scoring_mode=5` — the old weighted kDelta system — which commit `6b344a582826`
("remove mostly-dead classification from all liveness policies", **2026-07-08 17:40**)
deleted entirely. `SCORING_MODE` is not read anywhere in current `inc/cache.h`/`src/cache.cc`.
No θ sweep exists in `docs/JOBS.md` after that commit — every "established THD_DOA" citation
since just repeats the same numbers with no new sweep behind them.

**Fix — derived the conversion from the actual `scoring_mode==5` code** (`git show
38f82fc1c241:inc/cache.h`, the commit that introduced the June 27 sweep): a DoA eviction from
a fresh/MA-state PC added `dd=5` to the doa counter (dropping to 3 only once already past the
MD band, which barely activates — consistent with this session's "MD contributes nothing"
finding); an alive eviction reset both counters to 0, same category as the current hard reset.
So old θ and new (flat, +1-per-DoA-eviction) θ measure the same thing — consecutive DoA
evictions needed to cross — off by that factor: **new θ = ceil(old θ / 5)**. Regrouped the
existing `lru_live_thd_duel_20260627` sweep's IPC-vs-θ data (θ∈{2,4,8,16,20,25,30,35,40}) by
this conversion and took the real argmax on the correctly-scaled grid — no new simulation
needed for the correction itself.

| suite | old (wrong) θ | corrected θ |
|---|---|---|
| dpc3   | 8  | **1** |
| gap    | 1  | 1 |
| gms    | 4  | **6** |
| google | 4  | **6** |
| ligra  | 1  | 1 |
| ml     | 16 | **6** |
| qmm    | 4  | **2** |

4 of 7 suites change (dpc3 and ml substantially). gap and ligra happen to already be correct.
Cancelled `doa_seq_full` (1410596-1410602), `cushion_test` (1410603-1410623), `doa_decay`
(1410624-1410644) — none had started producing usable data at wrong θ — and relaunched all
three with the corrected table:

| Launch | Cluster dir | Status |
|---|---|---|
| 2026-07-10 01:00 | `results/doa_seq_full_20260710_0100/{suite}` (jids 1410645-1410651, 251 tasks) | submitted, running |
| 2026-07-10 01:00 | `results/cushion_test_20260710_0100/{base,cfgA,cfgB}/{suite}` (jids 1410652-1410672, 753 tasks) | submitted, running |
| 2026-07-10 01:00 | `results/doa_decay_20260710_0100/{base,decay1,decay2}/{suite}` (jids 1410673-1410693, 753 tasks) | submitted, running |

**Resolved**: also affected — `recheck_allsuites_20260709_2219` (same stale θ table), and the
"clean" SRRIP-Live/SRRIP recompute from the contamination fix above (`*_thd_rebaseline_20260605_2316`
predates the flat-scoring change too — its `run_info.txt` shows `mid_thd`, not `thd_doa` — so
picking the "established" `thd{N}` subdirectory per suite there was also at the wrong θ for
dpc3/gms/ml/qmm). Cancelled `recheck_allsuites`'s remaining tail (1410589-1410594) and relaunched
the full 3-arm study fresh (not just the unfinished suites — ml/qmm/gms had already completed
under the wrong θ too). For the SRRIP-Live/SRRIP comparison: `results/baselines/srrip` is
reusable as-is (SRRIP has no threshold, untouched by this bug) — only the SRRIP-Live arm needed
a fresh run.

| Launch | Cluster dir | Purpose | Status |
|---|---|---|---|
| 2026-07-10 01:05 | `results/recheck_allsuites_20260710_0105/{base,byp1x,recheck}/{suite}` (21 array jobs, jids 1410694-1410714, 753 tasks) | Full clean rerun, corrected θ, all 7 suites | submitted, running |
| 2026-07-10 01:05 | `results/srrip_live_clean_20260710_0105/{suite}` (7 array jobs, jids 1410715-1410721, 251 tasks) | `champsim_srrip_live` only (baseline reused from `results/baselines/srrip`), corrected θ, all 7 suites | submitted, running |

Not relaunched (lower priority, already-conclusive directional findings, holding unless asked):
`DOA_FORCE_PCT`/`DOA_DEFAULT_PCT` on QMM (ran at θ=4, should be 2) and the "bypass at 2x
THD_DOA" 6-suite result (dpc3/gms/ml/qmm at wrong θ).

## All five overnight studies complete; results consolidated (2026-07-10/11)

`doa_seq_full`, `cushion_test`, `doa_decay`, `recheck_allsuites`, `srrip_live_clean` all finished
overnight (~24h). Findings written up in full at the private Claude Artifact
(`https://claude.ai/code/artifact/e5c78688-178f-4e57-979a-53277895298f`, not shared/public —
this is unpublished research). Headlines:

- **Counter sequence**: confirms the DoA counter is a streak, not a confidence score — average
  held score sits 2-4 orders of magnitude above θ everywhere (e.g. dpc3 ~79,000 vs θ=1).
- **Cushion causal test**: mixed, 3-of-7 confirm room-for-error / 4-of-7 contradict (gap, ml,
  qmm, google favor the *no-cushion* config bigger); doesn't correlate with reset rate or
  peak-before-reset.
- **Bypass-recheck**: small aggregate hides a bimodal per-trace effect (ligra PageRank +90.21%,
  most other traces slightly negative — a consistent "probe tax" paid everywhere, earned back
  only where bypass is a real, sizeable mistake).
- **DOA_DECAY**: prediction ("resets are rare, so softening shouldn't matter") refuted on 4 of 7
  suites, moving up to ±2.4% in both directions.
- **SRRIP-Live clean rerun**: confounded — accidentally used the already-known-degenerate default
  `SRRIP_DOA_INS_RRPV=2` (same insertion as plain SRRIP), so it mostly re-confirms that finding
  rather than testing anything new.

## SRRIP-Live ins@3 rerun (2026-07-10 23:11)

Follow-up to the confound above: `SRRIP_DOA_INS_RRPV=3` (immediate-eviction candidate, the
config FINDINGS.md documents as the only one that "produces meaningful gains"), corrected θ,
all 7 suites. Baseline reused from `results/baselines/srrip`.

| Launch | Cluster dir | Status |
|---|---|---|
| 2026-07-10 23:11 | `results/srrip_live_ins3_20260710_2311/{suite}` (7 array jobs, jids 1410722-1410728, 251 tasks) | submitted, running |

## Closing out remaining θ-bug loose ends + gap/ligra addr-summary at real θ (2026-07-10 23:32)

Three more relaunches, all ready-to-go with existing binaries/knobs, no new code:

1. **`DOA_DEFAULT_PCT`/`DOA_FORCE_PCT` on QMM, corrected θ=2** (was 4), full 45-trace count
   (was a 13-trace sample). Both decoupled from bypass per the earlier fix. Prediction:
   still refuted (random-insertion mechanisms don't help), just at the right operating point.
2. **Bypass at 2x THD_DOA, corrected θ**, dpc3/gms/ml/qmm only (gap/ligra already had the
   right θ, not rerun). base vs byp2x, full trace counts.
3. **`DOA_ADDR_SUMMARY`, gap+ligra, corrected θ=1** — replaces the earlier `doa_addrsum_debug`
   sample, which used a uniform θ=6 for all suites (never the real operating point for any of
   them). Supports the open "what do PageRank/Triangle/cc-13 have in common" question at the
   threshold actually in production use.

| Launch | Cluster dir | Status |
|---|---|---|
| 2026-07-10 23:32 | `results/dfp_ddp_qmm_clean_20260710_2332/{base,ddp25,ddp50,dfp25,dfp50}` (5 array jobs, jids 1410729-1410733, 225 tasks) | submitted, running |
| 2026-07-10 23:32 | `results/bypass2x_clean_20260710_2332/{base,byp2x}/{gms,ml,qmm,dpc3}` (8 array jobs, jids 1410734-1410741, 364 tasks) | submitted, running |
| 2026-07-10 23:32 | `results/addrsum_gap_ligra_clean_20260710_2332/{gap,ligra}` (2 array jobs, jids 1410742-1410743, 26 tasks) | submitted, running |

Not started: a configurable LRU-Live insertion depth (`LRU_LIVE_DOA_INS` currently only supports
the fixed presets `2n3`/`lru`/`bypass`) to properly sweep the room-for-error question with more
than two endpoints. Needs a code change, held until reviewed together rather than run unattended.

## Results: SRRIP-Live ins@3 + the three closing reruns (2026-07-11)

**SRRIP-Live ins@3 vs SRRIP, corrected θ** — the clean room-for-error test the ins@2 rerun
couldn't be: LRU-Live/LRU (cfgA) beats SRRIP-Live(ins@3)/SRRIP on **all 7 suites**. Ligra is the
sharpest case — ins@3 actually regresses there (−3.46%, matching the documented ins@3-punishes-reuse
finding), while LRU-Live's cushioned insertion avoids that regression and still gets +3.49%. This
resolves the open room-for-error question decisively (see the artifact, §06).

**DOA_DEFAULT_PCT/DOA_FORCE_PCT on QMM, θ=2** — still refuted, similar magnitude to the original
wrong-θ run (ddp25 −1.80%, ddp50 −4.39%, dfp25 −1.52%, dfp50 −4.24%).

**Bypass at 2x THD_DOA, corrected θ** — direction holds on all 4 suites but magnitude shifts
meaningfully for dpc3 (+12.99%→+7.61%) and ml (+0.32%→+1.75%); gms/qmm close to unchanged.

**DOA_ADDR_SUMMARY, gap+ligra at real θ=1** — checked whether PageRank/Triangle/cc-13 (the big
bypass-recheck winners) share an elevated per-address reset rate. Partial confirmation: PageRank
(4.25%) and Triangle (2.56%) do sit at the high end of ligra's reset-rate distribution (most
traces ~0.00%), but it's not a clean predictor — Components-Shortcut (22000M) has the highest
reset rate of all (9.66%) yet only a modest recheck gain, while two other traces with non-trivial
reset rates (0.84–1.29%) still show recheck as a net loss.

Full write-up updated in place at the same Claude Artifact URL (private, not shared) referenced
above.

## New scoring system: surprise-weighted DoA counter (2026-07-11/12)

Added `DOA_SURPRISE_WEIGHT=1` (`inc/cache.h`/`src/cache.cc`): on a DoA eviction, `+2` if the
entry was NOT already guided as DoA at fill time (surprising — high information), `+1` if it
was (self-confirming — low information), vs the current System A's flat `+1` regardless of
`ins_class`. Matches the "surprising evidence carries more weight" rule that won empirically in
the old scoring-mode work (5/3/1 beat 1/3/5). `victim.ins_class` (already tracked per-`BLOCK`)
threaded through to `HistTable::update()`'s new 4th parameter; default unchanged when the env
var is unset. Reviewed both bounded/unbounded code paths; smoke-tested locally (pagerank trace)
— confirmed the code path engages (small but real IPC shift, 0.226867→0.226839) even with zero
resets, since a key's very first DoA eviction is always "surprising" regardless of reset history.

**No exact threshold-conversion factor exists between System A and System B** (unlike the old
scoring-system fix, which had one fixed `δ=5`): System B's increment is +1 or +2 depending on the
confirming/surprising mix, which varies by suite and PC. Testing System B at established θ,
1.5×, and 2× brackets it instead of assuming one number; low-θ suites (gap/ligra/dpc3, θ=1)
collapse 1.5×/2× to the same integer, so those get 2 distinct thresholds tested, not 3.

**All under Redwood Cove per this request** — built `champsim_{lru,srrip,lru_live,srrip_live}_redwoodcove`
locally from `champsim_config_redwoodcove.json` (never built on the cluster), transferred via
the double-SSH `cat` pipe, smoke-tested (confirms different LLC geometry: 4096 sets vs default's
2048). A complete Redwood Cove LRU baseline already existed from the June arch-rerun work
(`arch_rerun_zen4_redwoodcove_20260702_2100/redwoodcove/lru`, all 7 suites) — reused as-is
since plain LRU doesn't depend on the scoring system.

| Launch | Cluster dir | Purpose | Status |
|---|---|---|---|
| 2026-07-11 22:40 | `results/scoring_ab_redwoodcove_20260711_2240/{sysA,sysB_1x,sysB_15x,sysB_2x}/{suite}` (25 array jobs, jids 1410744-1410768, 883 tasks) | System A vs System B, `champsim_lru_live_redwoodcove`, all 7 suites, full trace counts | submitted, running |

Next steps once complete (per the user's plan): pick the winning (system, θ) combination per
suite → proper threshold sweep for the winner under Redwood Cove → size study → per-PC vs
per-address indexing comparison, all under Redwood Cove.

## Planned follow-up: victim cache for SRRIP-Live misprediction detection

Contingent on confirming (via the above) that LRU-Live's edge over SRRIP-Live really does come
from misprediction-detection ability (graduated stack lets a wrongly-classified block prove
itself via a hit before eviction), not some other suite-specific effect: prototype a small
victim cache that catches blocks evicted by SRRIP-Live's more conservative insertion/promotion,
giving SRRIP-Live an analogous recovery path. Not started — gated on the causal check above.

---

## Still Pending / Not Yet Submitted

- **All suites — hist_size sweep** (`sweep_hist_size.sh`): large pHIST×bHIST grid with LRU/LFU/hashed; not yet submitted for any suite
- **pc_bypass AND/OR match variants** (`pc_addr_pred`, `pc_or_addr_pred`): designed in `sweep_pc_bypass.sh` comment but not in configs array; not yet submitted
- **STLB policy / STLB thd — PC mode for new suites** (GAP, GMS, Ligra, ML): not yet submitted
- **srrip_live_bypass for new suites** (GAP, GMS, Ligra, ML): not yet submitted

Note: Mazumdar traces are NOT run for new experiments.
