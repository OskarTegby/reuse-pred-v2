# Plot Data Sources

Generated on branch `liveness-guided-replacement` (commit `8989555edfa4`).

---

## Step 0 — Build binaries (always required first)

Run locally, **never on Castillo**:

```bash
make static
```

This produces `bin/champsim_lru`, `bin/champsim_srrip_live`, `bin/champsim_ipv_live`,
`bin/champsim_stlb_srrip_live`, `bin/champsim_stlb_ipv_live`.
Transfer to Castillo with `scp bin/* castillo:reuse-pred/bin/`.

---

## Trace locations (on Castillo)

| Suite  | Path                                          | Extension           |
|--------|-----------------------------------------------|---------------------|
| DPC3   | `/home/users/shared/traces/dpc3_traces`       | `champsimtrace.xz`  |
| Google | `/home/users/shared/traces/Google_Traces_v2`  | `champsim.gz`       |
| QMM    | `trace-files/QMM`  (under project root)       | `champsimtrace.xz`  |
| GAP    | `trace-files/gap`  (under project root)       | `trace.gz`          |
| GMS    | `trace-files/gms`  (under project root)       | `champsimtrace.gz`  |
| Ligra  | `trace-files/ligra` (under project root)      | `champsimtrace.xz`  |
| ML     | `trace-files/ml`   (under project root)       | `champsimtrace.gz`  |

---

## Figure 1 — Liveness breakdown (`liveness_rates.png`)

**Script**: `scripts/analysis/plot_liveness_rates.py`

**How to generate the data**:
```bash
# On Castillo — runs champsim_lru with LIVENESS_CHAR=1 on all suites
./scripts/submit/sweep_liveness_char.sh
```

**Existing data dir**: `results/{suite}_repl_pol_20260522_0722/lru_baseline/`  
**Config**: Config A — 2 MB LLC, 1,536-entry STLB (128×12, 12-way).  
**Note**: Config A used a 12-way STLB instead of the correct 8-way (Config C).
Liveness fractions are structural workload properties, so the STLB numbers are
slightly off but the qualitative picture holds.

---

## Figures 2 & 3 — Threshold sensitivity (`llc_threshold_combined.png`, `stlb_threshold_combined.png`)

**Scripts**: `scripts/analysis/plot_llc_threshold_combined.py`,
             `scripts/analysis/plot_stlb_threshold_combined.py`

**How to generate the data** (for all 7 suites, Config C):
```bash
# On Castillo — one call per suite
./scripts/submit/sweep_mazumdar_threshold.sh qmm
./scripts/submit/sweep_mazumdar_threshold.sh google
# For remaining suites, use sweep_srrip_live_thd.sh / sweep_threshold_newsuites.sh
# (those scripts cover DPC3, GAP, GMS, Ligra, ML)
```

### Current data used by the plot scripts (Config A)

The hardcoded directory constants in the plot scripts point to **Config A** runs.
After the pending Mazumdar sweep completes (see below), update the directory
constants at the top of each plot script before regenerating.

#### LLC threshold (Figure 2)

| Suite  | SRRIP-Live dir (`results/`)                  | IPV-Live dir                                             |
|--------|----------------------------------------------|----------------------------------------------------------|
| DPC3   | `dpc3_srrip_live_thd_pc_20260513_0055`       | `cluster/dpc3_ipv_live_thd_addr_20260514_1432`           |
| QMM    | `qmm_srrip_live_thd_pc_20260513_0056`        | `cluster/qmm_ipv_live_thd_pc_20260514_1432`              |
| Google | `google_srrip_live_thd_pc_20260513_0056`     | `cluster/google_ipv_live_thd_pc_20260514_1432`           |
| GAP    | `gap_srrip_live_thd_pc_20260520_0059`        | `gap_ipv_live_thd_pc_20260520_0819`                      |
| GMS    | `gms_srrip_live_thd_pc_20260520_0128`        | `gms_ipv_live_thd_pc_20260520_0819`                      |
| Ligra  | `ligra_srrip_live_thd_pc_20260520_0059`      | `ligra_ipv_live_thd_pc_20260520_0819`                    |
| ML     | `ml_srrip_live_thd_pc_20260520_0059`         | `ml_ipv_live_thd_pc_20260520_0819`                       |

`cluster/` dirs are under `results/cluster/` (older experiment data stored separately).
Each dir contains subdirs `srrip_live_thd{1,2,4,8,16}/` or `ipv_live_thd{1,2,4,8,16}/`.

LRU baselines: `results/{suite}_repl_pol_20260522_0722/lru_baseline/`

#### STLB threshold (Figure 3)

| Suite  | Result dir (`results/`)            | SRRIP subdir               | IPV subdir                  |
|--------|------------------------------------|----------------------------|-----------------------------|
| DPC3   | `dpc3_pc_bypass_20260522_0101`     | `stlb_srrip_live_thd{N}/`  | `stlb_ipv_live_thd{N}/`     |
| QMM    | `qmm_pc_bypass_20260522_0101`      | same pattern               | same pattern                |
| Google | `google_pc_bypass_20260522_0101`   | same pattern               | same pattern                |
| GAP    | `gap_pc_bypass_20260522_0101`      | same pattern               | same pattern                |
| GMS    | `gms_pc_bypass_20260522_1958`      | same pattern               | same pattern                |
| Ligra  | `ligra_pc_bypass_20260522_1958`    | same pattern               | same pattern                |
| ML     | `ml_pc_bypass_20260522_0101`       | same pattern               | same pattern                |

### ⚠ Pending: Mazumdar sweep (Config C)

A full threshold sweep under Config C was submitted 2026-06-01:

| Suite  | Result dir                            | Castillo job arrays  |
|--------|---------------------------------------|----------------------|
| QMM    | `results/qmm_maz_thd_20260601_1537/`  | 1403838–1403858      |
| Google | `results/google_maz_thd_20260601_1537/` | 1403859–1403879    |

Directory structure per suite:
```
{suite}_maz_thd_{date}/
  lru/
  llc_srrip_live/thd{1,2,4,8,16}/
  llc_ipv_live/thd{1,2,4,8,16}/
  stlb_srrip_live/thd{1,2,4,8,16}/
  stlb_ipv_live/thd{1,2,4,8,16}/
```

**After the sweep completes**: update the directory constants at the top of
`plot_llc_threshold_combined.py` and `plot_stlb_threshold_combined.py` to
point to the new dirs, then rerun the regeneration commands below.

---

## Simulation config

```
Config C (target for all new runs):
  champsim_config.json at commit 8989555edfa4
  LLC:  2048 sets × 16 ways × 64 B = 2 MB,  latency 40 cycles
  STLB: 128 sets  ×  8 ways        = 1,024 entries, latency 8 cycles
  ITLB: 16 sets   ×  4 ways,  latency 1 cycle
  DTLB: 16 sets   ×  4 ways,  latency 1 cycle
  L1I:  64×8, 4 cy   L1D: 64×8, 5 cy   L2C: 512×8, 11 cy
  DRAM: 3200 MHz, 1 ch, tRP/tRCD/tCAS = 12.5 ns
  Warmup: 50M instructions   Simulation: 100M instructions

Config A (used by current Figure 1–3 data):
  Same as above except STLB: 128 sets × 12 ways = 1,536 entries
```

Key env vars passed to simulations:
- `MID_THD=N` — liveness threshold θ (1/2/4/8/16)
- `BHIST_MODE=pc` — use PC-indexed history table
- `SRRIP_LIVE_TARGET=stlb` — apply policy to STLB instead of LLC (STLB runs only)
- `LIVENESS_CHAR=1` — enable per-PC liveness logging (Figure 1 only)

---

## Regenerate all plots

```bash
python3 scripts/analysis/plot_liveness_rates.py
python3 scripts/analysis/plot_llc_threshold_combined.py
python3 scripts/analysis/plot_stlb_threshold_combined.py
```
