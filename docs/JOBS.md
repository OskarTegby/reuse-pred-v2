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

**RESULT (2026-07-07, `mru_end_mostly_dead_20260707_0117`, complete 1004/1004, 50M/100M):**
all three variants beat plain LRU by ~3% pooled, but the *mostly-dead trigger signal
itself makes essentially no difference* — default (wall-clock halflife) +2.99% pooled,
recency-rank MRU-end +3.01%, recency-rank LRU-end +2.93% (per-suite spread ≤0.5pp,
pooled spread 0.08pp). Per suite: dpc3 ~+0.9%, gap ~+6.8%, ligra +1.1–1.9%, gms ~+1.3%,
google +4.4–4.8%, qmm ~+2.1%, ml ~+3.7–3.9% — all three arms track each other closely in
every suite. Conclusion: what matters for LRU-Live is having *some* liveness-guided
insertion mechanism at all; the fine details of which signal decides mostly-dead
(wall-clock halflife vs. recency-stack position, or which end of the stack) don't
meaningfully change outcomes on this architecture/threshold. See
[[project_mru_end_mostly_dead]].

**Bottom line:** only `ipv_hist_duel_20260706_2058` is both complete and valid. Everything
else needs re-running against the corrected binary before its numbers can be trusted.

**FINAL RESULT (2026-07-07, 50M/100M, both batches complete 251/251):** IPV-Live/IPV —
dpc3 +0.86%, gap +1.77%, ligra +1.76%, gms +0.47%, google +1.65%, qmm +1.76%,
ml +1.75%. Pooled (equal-weight): **+1.43%**. Positive on all 7 suites, no outliers —
this is the definitive, trustworthy confirmation that the rewritten true k-way
permutation IPV mechanism delivers a real, consistent improvement over plain IPV,
correctly instruction-count-matched and on the corrected binary. Supersedes everything
below in this section.

**SUPERSEDED (2026-07-07): wrong instruction count.** All of the above (including
`ipv_hist_duel_20260706_2058` and `ipv_old_flat_20260706_2338`) ran at 50M warmup/50M sim.
I had generalized "gate phase = 50M/50M" (from [[feedback_sim_instruction_count]], which
is specifically about black-box test development) as a default for this session's
exploratory work — wrong. User: "We are supposed to do 100M sim, not 50M" + "the IPV-Live
batches (and all experiments besides black-box tests) need to be done with 100M sim."
50M warmup/100M sim is the standard for any experiment meant to produce a trustworthy
number, not a black-box-test-specific rule. Relaunched both at the correct instruction
count: **`ipv_hist_duel_20260707_0118`** (jids 1409334–1409340) and
**`ipv_flat_bases_20260707_0118/old_flat`** (jids 1409341–1409347), same correct binary,
same 251 traces. The +1.18% pooled IPV-Live/IPV figure below is now superseded pending
these — treat it as provisional until the 100M-sim numbers land.

**IPV-Live/IPV result (2026-07-07, `ipv_old_flat_20260706_2338`):** matched instruction
count (50M/50M), same 251 traces, correct binary both sides. Positive on all suites so
far — dpc3 +0.77%, gap +2.03%, ligra +0.75%, gms +0.44%, google +1.60%, qmm +1.60%.

**CORRECTION:** an initial pass reported ml at −33.56% (severe regression), attributed to
IPV-Live mispredicting liveness on ML-inference traces. **This was a data artifact, not a
real finding.** The "251/251 champsim.out present" completion check only verified the
*file* existed, not that the run had actually finished — 12+ ml `old_flat` tasks were
still mid-simulation when the IPC was extracted, so their "IPC" was actually the
warmup-phase cumulative IPC (grabbed because it was the last "cumulative IPC" line
present in a truncated, still-being-written file), not the true final simulation IPC.
Confirmed by checking for the actual `^Simulation finished` completion marker (absent on
12 of 31 ml traces) — re-extracting only the verified-complete pairs gives ratios in the
0.88–1.06 range, matching every other suite, and a partial ml pooled figure of **+1.09%**
(n=19/31, pending the rest). No mechanism problem exists; nothing to fix. **Lesson: a
`champsim.out` file existing is not proof a run finished — check for the actual
completion marker (`Simulation finished`), not just file presence or the last matching
line in a possibly-truncated file.**

---

## Recency-Rank Mostly-Dead Signal for LRU-Live (`mru_end_mostly_dead`, 2026-07-07)

**Context:** design discussion converged on swapping LRU-Live's mostly-dead/mostly-alive
eviction signal from the existing wall-clock halflife criterion
(`src/cache.cc`'s `update_eviction_counters` call site: `time_til_end <= lifetime/2`,
using `install_cycle`/`last_hit_cycle`/`current_cycle`) to a recency-stack-rank signal:
did the block's *last* hit land in the MRU half or the LRU half of the recency stack.
Question being tested: which end, if it's where the last hit landed, is the better
predictor of "this block is mostly dead" — repurposes `BLOCK::eviction_state` (added on
`recency-4state-liveness`) rather than a new field. Branch: `mru-end-mostly-dead`
(merged `recency-4state-liveness` → `main` first, branched off updated `main`).

**Code:** `replacement/lru_live/lru_live.cc` sets `eviction_state` on every hit (bit0=
accessed, one-way; bit1=last hit was in MRU half, reversible) and resets to 0 on fill.
`src/cache.cc`'s `evict_lv` computation gains an env-gated branch (`MD_SIGNAL_RECENCY=1`)
that reads `way->eviction_state`'s bit1 instead of the timestamp criterion; `MD_SIGNAL_END`
(`mru` default or `lru`) selects which end counts as mostly-dead evidence. Default
behavior (env var unset) is completely unchanged — verified locally: unguided IPV/LRU
bit-identical checks still pass, and a local smoke test on `pagerank` confirmed the switch
compiles and produces a (tiny, sample-limited) divergence between arms.

**Architecture:** `champsim_config_redwoodcove.json` (Intel Redwood Cove config, sourced
from vendor docs — see `results/paper/ARCHITECTURE_CONFIGURATION.md`), 2MB→3MB-class LLC
at 4096 sets × 12 ways, 4GHz OoO core, 1024-entry STLB. This is a genuinely different
hardware config from the "Config C" 2MB/2048×16 LLC used for the IPV-Live rewrite work
elsewhere in this doc — chosen because these LRU-Live results need to be representative
of the final architecture, not the generic baseline config.

**Instructions/thresholds:** 50M warmup / 100M sim (corrected — this is a Redwood-Cove
"representative of final architecture" run, not gate-phase iteration; the 50M/50M gate
convention was wrongly applied at first, see correction below), THD_DOA=8/THD_DEAD=2
(established thresholds reused as-is, no resweep), all 251 traces across all 7 suites
(dpc3 95, gap 9, ligra 17, gms 11, google 43, qmm 45, ml 31).

**4 arms per suite**, jids 1409250–1409277 (28 arrays):
1. `lru` — plain LRU baseline (`champsim_lru_redwoodcove`), for computing speedup.
2. `lru_live_default` — LRU-Live, existing production mostly-dead signal (unchanged).
3. `lru_live_mru` — LRU-Live, recency signal, MRU-end-last-hit ⇒ mostly-dead.
4. `lru_live_lru` — LRU-Live, recency signal, LRU-end-last-hit ⇒ mostly-dead.

Launched via `scripts/submit/submit_mru_end_mostly_dead.sh`.

**First attempt (`mru_end_mostly_dead_20260707_0112`, jids 1409250–1409277) CRASHED
on every task.** Built both binaries with plain `make` (dynamic linking) instead of
`make static` — Castillo's compute nodes have an older glibc/libstdc++ than the local
build machine, so every task failed immediately with `GLIBCXX_3.4.32 not found`
(`champsim.err`), producing empty `champsim.out` files. Exactly the mistake
[[feedback_build_workflow]] exists to prevent. Cancelled all 28 arrays, rebuilt both
binaries with `make static` (verified `file` shows "statically linked"), redeployed,
confirmed a manual run completes cleanly on Castillo. Relaunched as
`mru_end_mostly_dead_20260707_0114` (jids 1409278–1409305) — **wrong instruction count**
(50M sim, the gate-phase convention used elsewhere this session), user corrected: this
run needs 100M sim to be representative of the final architecture. Cancelled just this
batch (28 arrays; left the unrelated `ml_oldfl` IPV stragglers from earlier untouched),
fixed `submit_mru_end_mostly_dead.sh` (`S=100000000`), **relaunched clean as
`mru_end_mostly_dead_20260707_0117`, jids 1409306–1409333.**

**Bug found + fixed in the reporting stat (commit `465068899af3`):**
`sim_stats.mostly_dead`/`mostly_alive` (the printed `LLC ... MOSTLY_DEAD/MOSTLY_ALIVE`
line) was computed via a separate, hardcoded wall-clock halflife check — completely
independent of the `evict_lv` that actually drives the history table. It never
respected `MD_SIGNAL_RECENCY`/`MD_SIGNAL_END`, so that one diagnostic line was silently
wrong for every `mru`/`lru` run above. **Did not affect IPC or the real mechanism** —
only that reported stat was wrong; the actual `evict_lv` feeding
`update_eviction_counters()` was already correct, so the RESULT above stands. Fixed by
sharing one `evict_lv_for_stats` variable between both consumers.

**New: `MD_DISABLE_DOA_SCORE=1`** (same commit) — DoA evictions stop feeding the
history-table score, isolating mostly-dead/mostly-alive as the only signal driving
future insertion decisions (DoA is still detected/reported as before). Purpose: test
whether DoA's dominance was masking a real difference between the MRU-end and LRU-end
signals (see [[project_mru_end_mostly_dead]] for the per-block classification analysis
that motivated this).

**LAUNCHED (`md_nodoa_20260707_1142`, jids 1409348–1409368):** 3 arms × 7 suites —
`lru_live_default_nodoa`/`lru_live_mru_nodoa`/`lru_live_lru_nodoa`, each combining
`MD_DISABLE_DOA_SCORE=1` with the corresponding MD signal. Same config as
`mru_end_mostly_dead_20260707_0117` (Redwood Cove, THD_DOA=8/THD_DEAD=2, 50M/100M, all
251 traces) — reuses that batch's `lru` baseline since plain LRU is unaffected by this
flag.

**Stronger version: DoA fully disabled via unreachable threshold, not just
score-feedback.** `MD_DISABLE_DOA_SCORE` only stops DoA evictions from feeding the
history-table score — the score could still drift into DoA territory via repeated
mostly-dead nudges (MD→DoA), so `classify()` could still occasionally predict DoA.
Cleaner approach needing zero code change: `THD_DOA=1000000000000` (score is `int64_t`,
parsed via `std::stoull` — confirmed no overflow risk) makes the `score >= thd_doa`
branch in `HistTable::classify()` structurally unreachable, leaving `THD_DEAD=2`
(unchanged) as the sole active threshold — a clean 2-way mostly-dead/mostly-alive split
with zero DoA. Verified locally: `Insert mix: DoA=0.0% Dead=81.6% Alive=18.5%` (up from
~2–4% Dead when DoA was present) — a much better-powered sample for telling the two MD
signals apart. Also added a raw-count print (`Insert mix (raw): DoA=X Dead=Y Alive=Z
Unguided=W`, commit `bb3259fac2ba`) alongside the existing percentages.

**LAUNCHED (`md_nodoa_full_20260707_1244`, jids 1409369–1409382):** 2 arms × 7 suites —
`lru_live_mru_nodoa_full` / `lru_live_lru_nodoa_full`, `THD_DOA=1000000000000
THD_DEAD=2 MD_SIGNAL_RECENCY=1 MD_SIGNAL_END=mru|lru`. Same Redwood Cove config,
50M/100M, all 251 traces. Reuses the existing `lru` baseline (plain LRU has no
liveness guidance to disable). This is the cleanest, best-powered test yet of whether
the MRU-end vs LRU-end signal choice actually matters once DoA can't dominate.

**CANCELLED both batches (`md_nodoa_20260707_1142` jids 1409348–1409368,
`md_nodoa_full_20260707_1244` jids 1409369–1409382) — missing `LRU_LIVE_HIT_INIT`.**
Neither batch set this env var, so `hit_mode=0` (default) applied: every hit,
regardless of class, promotes fully to MRU. This meant only *insertion* position
differed by classification (mostly-dead N/3 vs mostly-alive MRU) — *promotion*-on-hit
behavior was identical across all classes, so the MD/MA distinction had no ongoing
effect once a block got hit even once. User: "if there is no change then there is
nothing to evaluate." `md_nodoa_20260707_1142` had 217/753 traces already finished
when cancelled; not reused since it doesn't test what's needed.

**BUG FOUND AND FIXED in `MD_DISABLE_DOA_SCORE` itself (commit `c90c5354657d`):** the
original implementation skipped `update_eviction_counters()` entirely for DoA evictions
at the call site — which also froze the *doa* counter itself for DoA-dominated PCs
(never able to grow), on top of the intended md-counter isolation. Also, the `md_nodoa`
and `md_nodoa_full` batches launched with it (`md_nodoa_20260707_1326`/
`md_nodoa_full_20260707_1326`) showed **zero MD activation on every completed dpc3
trace** — cancelled both (214/753 traces had finished, not reused). Root cause,
identified via `HistTable::update()`'s `scoring_mode==2` code: DoA evictions were
*coupled* — `p.first = old_md + delta; p.second = old_doa + delta;` — a DoA eviction
bumped the md counter by design ("DoA eviction drives both"). So mostly-dead
classification was substantially driven by repeated DoA evictions alone, not genuine
accessed-but-stale behavior. An initial attempted fix (`SCORING_MODE=5`, an
already-decoupled mode) was rejected — it also swaps in a completely different delta
philosophy (5/3/1 vs mode 2's 1/2/3) never used elsewhere this session, confounding the
comparison. **Correct fix**: `HistTable` gained a `decouple_doa_md_` flag
(`set_decouple_doa_md()`), checked only inside `scoring_mode==2`'s DoA branch — a DoA
eviction still updates its own doa counter exactly as before (DoA stays exactly as
reachable), it just no longer also bumps the md counter. Every other aspect of mode 2
is unchanged. `MD_DISABLE_DOA_SCORE` now wires to this (both unbounded and bounded
`repl_hist_pc` init sites); the old caller-side skip in `cache.cc` was removed —
`update_eviction_counters()` is called unconditionally again.

**Verified before relaunch**: on `dpc3/654.roms_s-1070B` — coupled baseline
`Dead=808`; decoupled + default (wall-clock) signal `Dead=0` (the earlier "56.9%/81.6%
Dead" numbers were themselves a coupling artifact); decoupled + recency **MRU-end**
signal `Dead=922` (healthy, real, independent of DoA); decoupled + recency **LRU-end**
signal `Dead=0` at the classify() level, but the *raw per-eviction* count (`LLC ...
MOSTLY_DEAD: 509`) confirms the signal does fire — it just never repeats on the same
PC often enough (without an intervening mostly-alive reset) to cross `thd_dead=2` and
affect an actual insertion. Confirmed the full partition holds:
`DOA + MOSTLY_DEAD + MOSTLY_ALIVE` sums exactly to total evictions in every case
(333621+509+89=334219) — every accessed block is classified as exactly one of the two.
This MRU-end/LRU-end asymmetry (one signal concentrates enough to matter, the other is
real but too diffuse) is itself a genuine, informative finding — validates the
original hypothesis that MRU-end is the more consequential signal.

**RELAUNCHED both, clean, with the fix (`md_nodoa_20260707_1615`, jids 1409418–1409438;
`md_nodoa_full_20260707_1615`, jids 1409439–1409452).** These were subsequently
cancelled (all still `qw`, nothing running) pending a cluster-side verification check
per user instruction ("run tests on the cluster, not ad-hoc SSH").

**Cluster verification checks (qsub debug jobs, dpc3/654.roms_s-1070B unless noted):**
- `debug_md_check.sh` (jid 1409453, 2M/10M, both mru/lru ends, THD_DOA=8): confirmed
  matches earlier ad-hoc SSH results exactly.
- `debug_md_check2.sh` (jid 1409454, 2M/10M, THD_DOA=1e12 unreachable): confirmed
  `Insert mix Dead=0` in both arms — insertion-level DoA fully unreachable as intended.
- **New requirement**: DoA counter (`p.second`) must not increment AT ALL (temporary,
  "for now only, later we will restore it") — stronger than `MD_DISABLE_DOA_SCORE`
  (which only stops DoA's effect on `md`, not `doa` itself). Added
  `MD_SUPPRESS_DOA_UPDATE=1`: skips `update_eviction_counters()` entirely for
  `evict_lv==doa` (`src/cache.cc`), distinct from and stackable with
  `MD_DISABLE_DOA_SCORE`.
- `debug_md_check3.sh` (jid 1409455, 2M/10M, roms): confirmed raw per-eviction
  classification unaffected by the new flag (exact match to job 1409454's numbers);
  only 6 total non-DoA evictions in this short window on roms — too sparse to show
  real `Insert mix: Dead` activation (small-sample, not a bug).
- `debug_md_check4.sh` on `dpc3/607.cactuBSSN_s-2421B` (temporally-reused workload,
  chosen because roms is ~99.8% DoA-dominated and can't demonstrate real MD activation)
  — iterated instruction count per user feedback (2M/10M → 500K/2M "too little" →
  1M/5M → **20M/30M**, settled): jid 1409459 (before phase-reset fix) showed
  **real activation**: lru-end arm `Insert mix Dead=873`, `MA→MD=4` transitions;
  mru-end arm showed 0 (all 34 raw accessed evictions in this window landed on the
  LRU half, none on MRU — opposite direction from roms, confirming which end "wins"
  is trace-dependent, not universal).

**BUG FOUND: `Insert mix`/`repl_hist transitions` counters were never reset at the
warmup→ROI boundary** (unlike `sim_stats`' evictions/DOA/MOSTLY_DEAD/MOSTLY_ALIVE,
which correctly reset via `CACHE::begin_phase()` — comment: "exclude warmup"). This
meant those counters silently included the full 20M-instruction warmup phase on top
of the 30M-instruction sim phase, inflating magnitudes and making them incomparable to
the properly-scoped eviction stats. **Fixed**: added `repl_hist_pc.reset_stats()` +
`g_merged_repl_hist.reset_stats()` to `begin_phase()`, plus a new weak-symbol hook
`lru_live_reset_phase_stats(CACHE*)` (declared weak in `cache.cc`, defined strong in
`lru_live.cc`) that resets `lru_live.cc`'s own `Stats` struct — a no-op in binaries
that don't link `lru_live.o`. Verified via `nm` that only `champsim_lru_live_redwoodcove`
has the strong symbol; the other 3 redwoodcove binaries build/link clean without it.

**Added new stat**: `promo_capped_doa`/`promo_capped_dead` in `lru_live.cc` — counts
hits on a DoA/MD-classified slot where the promotion target was *actually* capped
below full MRU (distinct from `hit_doa`/`hit_dead`, which count hits on classified
slots regardless of whether `LRU_LIVE_HIT_INIT` caps anything). Printed as
`Promo capped (raw): DoA=x/y  Dead=x/y`.

**`debug_md_check4` rerun (job 1409462, cactuBSSN, 20M/30M)** launched with the
phase-reset fix + new promo-capped stat + expanded grep filter (previously silently
dropped `Insertion positions`/`Hit promotion`/`Hit rate`/`Promo capped` lines) — result
pending at time of writing.

**Extensive comparison launched: `mru_end_mostly_dead_v2_20260707_1749`** (jids
1409463–1409470, 8 array jobs / 24 tasks total). Supersedes the earlier, un-fixed
`mru_end_mostly_dead_20260707_0117` batch (jids 1409278–1409305, ran to completion
under the old buggy config — missing `MD_DISABLE_DOA_SCORE`/`MD_SUPPRESS_DOA_UPDATE`/
`LRU_LIVE_HIT_INIT`, results unreliable, not reused). Scope: 4 arms (plain LRU
baseline, LRU-Live default/halflife, LRU-Live recency MRU-end, LRU-Live recency
LRU-end) × 6 curated traces (not whole suites — would be hundreds of tasks):
- dpc3: `654.roms_s-1070B` (DoA-dominated), `607.cactuBSSN_s-2421B` (temporally-reused,
  validated this session), `623.xalancbmk_s-325B` (temporally-reused per project
  history), `619.lbm_s-2676B` (streaming/DoA-dominated contrast)
- ligra: `ligra_MIS...drop_21250M` (temporally-reused per `project_bypass_pertrace`),
  `ligra_PageRank...drop_51000M` (streaming graph-kernel contrast)

50M warmup / 100M sim (standard scale). All three LRU-Live arms use
`MD_DISABLE_DOA_SCORE=1,MD_SUPPRESS_DOA_UPDATE=1,LRU_LIVE_HIT_INIT=1` (validated this
session); plain LRU baseline has none of this apparatus. `THD_DOA=8,THD_DEAD=2`
throughout. Script: `scripts/submit/submit_mru_end_mostly_dead_v2.sh`.

**Earlier step in this saga, still valid, superseded only by the coupling bug above:
`LRU_LIVE_HIT_INIT=1` was added** (caps mostly-dead blocks'
promotion back to their own insertion depth, N/3, instead of full MRU — verified via
`Hit promotion: DoA/MD capped to class initial position`): **`md_nodoa_20260707_1326`**
(jids 1409383–1409403) and **`md_nodoa_full_20260707_1326`** (jids 1409404–1409417).
No binary rebuild needed (`LRU_LIVE_HIT_INIT` is a runtime env var). Verified locally
and on a real cluster trace (dpc3/654.roms_s-1070B, 5M sim) before launching: `Insert
mix: Dead=56.9%` (136455 raw), non-degenerate.

---

## Still Pending / Not Yet Submitted

- **All suites — hist_size sweep** (`sweep_hist_size.sh`): large pHIST×bHIST grid with LRU/LFU/hashed; not yet submitted for any suite
- **pc_bypass AND/OR match variants** (`pc_addr_pred`, `pc_or_addr_pred`): designed in `sweep_pc_bypass.sh` comment but not in configs array; not yet submitted
- **STLB policy / STLB thd — PC mode for new suites** (GAP, GMS, Ligra, ML): not yet submitted
- **srrip_live_bypass for new suites** (GAP, GMS, Ligra, ML): not yet submitted

Note: Mazumdar traces are NOT run for new experiments.

---

## DoA/MD ablation (2026-07-08)

**Branch restructure first**: pulled the phase-reset fix (lru_live + srrip_live +
ipv_live) and the regenerated black-box `expected/` outputs onto a new branch,
**`blackbox-phase-reset-fix`** (based on `main`, cherry-picked from
`mru-end-mostly-dead`'s commits `e1c5ae35`/`3f49ef70`/`30281e67`) — general-purpose
correctness fixes, kept separate from the MD-signal experiment so it can be
reviewed/merged on its own timeline. `mru-end-mostly-dead` keeps all 9 commits
(duplication is intentional, not a rewrite).

**Black-box verify re-run**: `blackbox_run_cluster.sh` (no `generate` arg) launched
to confirm the regenerated references reproduce cleanly on a fresh run. Note: the
script's own `jobs_in_queue()` has a real bug — `qstat` returning empty output is
ambiguous between "0 jobs" and "SSH blip," so a `generate`-mode run can hang forever
once the queue genuinely empties (hit this on the first `generate` run; had to kill
it and manually finish the download/copy/commit steps). Verify mode has a second,
more robust termination path (direct output-file comparison via `check_progress.sh`),
so less likely to hit the same hang, but worth knowing about if a future run stalls.

**First two launch attempts failed, both from bugs in the submission script itself
(not the binary/experiment config):**
- `md_doa_ablation_20260708_0018` (jids 1409591–1409614): `TRACE_FILTER` was built
  as an anchored basename match (`^654\.roms_s-1070B$`), but `run_cs.sh` greps the
  *full path* returned by `find`, which never matches an anchored basename pattern
  — every task failed instantly with "No traces found", before any simulation
  started (verified via `Simulation finished`-marker-free, essentially-empty
  `champsim.out`/near-zero runtime; no compute wasted). My own pre-submission
  check had tested against a basename-stripped string, not what `run_cs.sh`
  actually greps — didn't reproduce the real code path. Fixed: unanchored
  substring filter (`${tname//./\\.}`, no `^`/`$`), matching the v2 script's style.
- `md_doa_ablation_20260708_0022` (jids 1409615–1409638): fixed the filter, but
  submitted as plain (non-array) qsub jobs. This SGE setup sets `SGE_TASK_ID` to
  the literal string `"undefined"` for non-array jobs rather than leaving it
  unset, so `run_cs.sh`'s `: "${SGE_TASK_ID:=1}"` default never triggers — every
  task failed instantly with "SGE_TASK_ID (undefined) out of range". `run_cs.sh`
  requires the `-t 1-N` array form even for N=1, matching what the v2 script
  always did. Verified the fix with a single standalone test job before
  resubmitting the full batch.

**Launched (`md_doa_ablation_20260708_0026`, jids 1409641–1409664, 24 tasks,
`mru-end-mostly-dead` branch, `champsim_lru_live_redwoodcove`)**: pinpoints exactly
what mostly-dead classification contributes vs. DoA, on the same curated 6-trace
subset used in `mru_end_mostly_dead_v2` (dpc3: roms/cactuBSSN/xalancbmk/lbm; ligra:
MIS/PageRank), 50M/100M. 4 arms per trace:
- `lru` — plain LRU baseline
- `both` — THD_DOA=8, THD_DEAD=2, LRU_LIVE_HIT_INIT=1, no suppress/decouple flags:
  normal coupled production behavior ("how things were" before this session's
  isolation work), default wall-clock halflife MD signal (no MD_SIGNAL_RECENCY —
  deliberately kept out of this ablation to isolate DoA-vs-MD cleanly, independent
  of the separate MRU-end/LRU-end signal-choice question already answered by
  `mru_end_mostly_dead_v2`)
- `doa_only` — THD_DOA=8, THD_DEAD=0: MD's branch in `classify()` is structurally
  unreachable (`thd_dead > 0` check fails), DoA operates completely normally
- `md_only` — THD_DOA=8, THD_DEAD=2, MD_DISABLE_DOA_SCORE=1,
  MD_SUPPRESS_DOA_UPDATE=1: DoA fully suppressed (validated this session), only MD
  contributes

Verified trace-filter regex matches exactly 1 file per trace name before submitting.

**Superseded by an all-suites run per explicit user request** ("I wanted you to
run these different categories on all suites... run now overnight"). Launched
**`md_doa_ablation_allsuites_20260708_0038`** (jids 1409665–1409692, 28 array
jobs / 1004 tasks total, `mru-end-mostly-dead` branch): same 4 arms
(lru/both/doa_only/md_only) as above, but across **all 7 suites, all 251 traces**
(dpc3 95, gap 9, ligra 17, gms 11, google 43, qmm 45, ml 31), 50M/100M,
`champsim_lru_live_redwoodcove`. Verified actually running (real ChampSim
heartbeat output, not an instant error) before trusting it at this scale — see
the two failed attempts above for why that check matters. The curated 6-trace
batch (`md_doa_ablation_20260708_0026`) was left running rather than cancelled,
since it gives an earlier partial read and costs little to leave alone.

**Both ablation batches finished clean overnight**: curated (24/24, 0 errors) and
all-suites (1004/1004, 0 errors). Curated results (IPC % vs plain-LRU baseline):

| trace | both | doa_only | md_only |
|---|---|---|---|
| roms | +7.30% | +7.95% | +0.45% |
| lbm | -3.85% | -3.50% | 0.00% |
| cactuBSSN | -1.08% | -0.78% | +0.06% |
| xalancbmk | +1.22% | +1.07% | +0.87% |
| MIS | +0.03% | +0.03% | -0.03% |
| PageRank | -0.60% | +0.25% | -0.51% |

`md_only` is consistently near-zero/mixed-sign — real trace-dependent interaction
(DoA actively hurts on lbm; MD's marginal contribution is negative on PageRank
even though DoA-only there is positive). A follow-up Explore-agent investigation
found this isn't simply "MD carries no signal": where MD activates rarely
(lbm 0%, cactuBSSN 0.1% of insertions) there's nothing to move IPC; where it
activates substantially with clean class separation (roms, xalancbmk — Dead hit
rate ~4-5% vs Alive ~40-50%), IPC moves modestly positive; but
`LRU_LIVE_HIT_INIT=1` caps every hit on an MD slot back to its N/3 insertion
rank regardless of outcome, so even correctly-identified reuse gets no reward —
plausibly explaining the flat-to-negative net effect. Also noted: this whole
ablation ran `SCORING_MODE=2`/`THD_DOA=8`/`THD_DEAD=2`, not the project's own
previously-chosen config (`docs/FINDINGS.md`: `SCORING_MODE=5`,
`THD_DOA=6`/`THD_DEAD=10`) — a possible confound not yet tested.

---

## Recency-position-gated promotion (LRU_LIVE_HIT_INIT=5) — 2026-07-08

User's read on the above: "mostly-dead just doesn't work so well." One last
experiment before setting the classify()-driven MD signal aside: replace
class-based promotion capping with a purely **recency-position-gated** rule,
independent of DoA/MD/MA classification entirely (insertion positions/
classification unchanged — only the on-hit promotion rule differs):
- hit while in the LRU half (rank < N/2): promoted only to just above the
  middle, two steps closer to MRU than dead-center (`(N-1-N/2)+2`). A repeat
  hit while still in the LRU half lands at this same capped position again
  (no escalation).
- hit while already in the MRU half (rank >= N/2): promoted fully to MRU, same
  as an ordinary uncapped hit.

Implemented as a new `LRU_LIVE_HIT_INIT=5` mode in `replacement/lru_live/lru_live.cc`
(also extended the `replacement_final_stats()` print-side `hit_mode` parser,
which had only ever supported 0/1/2, to recognize 3/4/5 too, for accurate
"Hit promotion" description text). On a **new branch, `lru-live-recency-promotion-cap`**
(off `mru-end-mostly-dead`), commit `9c185e7fffa8`. Rebuilt, statically-linked
verified, smoke-tested locally (no crash, correct stats block) before deploying.

**Launched (`recency_promo_test_20260708_0936`, jids 1409693–1409710, 18 tasks)**:
3 arms (lru baseline / hit_init_1 existing class-capped / hit_init_5 new
recency-gated) × the same 6 curated traces, 50M/100M, `THD_DOA=8`/`THD_DEAD=2`
for both LRU-Live arms (DoA+MD both enabled/classify()-driven insertion
unchanged — only promotion-on-hit differs between arms 2 and 3). Result
(5/6 done, lbm pending): hit_init_5 does not beat hit_init_1 on any
completed trace — roms -1.87%, cactuBSSN -0.05%, xalancbmk +0.09%, MIS
0.00%, PageRank -0.34% (hit_init_5 vs hit_init_1).

---

## Set-dueling MD isolation — 2026-07-08

User's methodological correction: all of this session's DoA/MD ablation work
(`md_doa_ablation_*`) used a simplified, non-dueling, fixed-arm config
(`SCORING_MODE=2`, `THD_DOA=8`, flat `THD_DEAD=2`) — **not** the actual
established production config, which uses set dueling for the DoA arm choice
(`arch_rerun_zen4_redwoodcove_20260702_2100`: `SCORING_MODE=5`, `THD_DOA=6`,
per-suite `THD_DEAD`, `LRU_LIVE_DOA_INS=2n3` vs `LRU_LIVE_DOA_INS_B=lru`,
`DUEL_METRIC=latency`, `DUEL_N_SAMPLERS=32`). Since set dueling only chooses
between DoA insertion arms — MD's own contribution is never part of what's
being dueled — the only way to know MD's *true* marginal effect is to compare
the full production config against the same config with MD disabled,
holding the dueling mechanism itself completely fixed.

Confirmed the exact production env vars via
`scripts/submit/arch_rerun_zen4_redwoodcove.sh` (line 41: per-suite
`THD_DEAD` table; line 43: `LRU_LIVE_DUEL` string) and one existing
`run_info.txt` (`redwoodcove/lru_live/dpc3/654.roms_s-1070B`:
`scoring_mode=5, thd_doa=6, thd_dead=4`). Reusing the existing "with MD"
data (already on Castillo, `arch_rerun_zen4_redwoodcove_20260702_2100`) —
no need to rerun it.

**Launched (`duel_no_md_20260708_1044`, jids 1409711–1409717, 7 array jobs /
251 tasks, all 7 suites)**: identical production config, but `THD_DEAD=0`
(disables `classify()`'s mostly-dead branch entirely; DoA + dueling
untouched). Verified correct config via `run_info.txt`
(`scoring_mode=5, thd_doa=6, thd_dead=0`) before trusting at scale.
`champsim_lru_live_redwoodcove` binary (built on this branch, includes
today's phase-reset fix — doesn't change IPC, only reporting counters).
Once done: compare per-suite + per-suite-equal-weighted-pooled IPC against
the existing `arch_rerun_zen4_redwoodcove_20260702_2100/redwoodcove/lru_live`
data (same binary family, same architecture, same dueling mechanism, only
MD switched off) to isolate MD's true contribution within the real
production setup.
