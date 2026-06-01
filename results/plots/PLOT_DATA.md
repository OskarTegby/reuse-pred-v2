# Plot Data Sources

Generated on branch `liveness-guided-replacement`.

---

## Figure 1 — Liveness breakdown (`liveness_rates.png`)

**Script**: `scripts/analysis/plot_liveness_rates.py`  
**Data**: `results/{suite}_repl_pol_20260522_0722/lru_baseline/`  
**Config**: Config A — 2 MB LLC, 1,536-entry STLB (128×12)  
**Note**: Config A used a 12-way STLB instead of the correct 8-way (Config C). The
liveness fractions are structural properties of the workloads, so the STLB counts
are slightly off but the qualitative picture holds.

Suites: DPC3, QMM, Google, GAP, GMS, Ligra, ML.

---

## Figures 2 & 3 — Threshold sensitivity (`llc_threshold_combined.png`, `stlb_threshold_combined.png`)

**Scripts**: `scripts/analysis/plot_llc_threshold_combined.py`,
             `scripts/analysis/plot_stlb_threshold_combined.py`

### LLC threshold data (Figure 2)

| Suite  | SRRIP-Live result dir                        | IPV-Live result dir                                      |
|--------|----------------------------------------------|----------------------------------------------------------|
| DPC3   | `dpc3_srrip_live_thd_pc_20260513_0055`       | `cluster/dpc3_ipv_live_thd_addr_20260514_1432`           |
| QMM    | `qmm_srrip_live_thd_pc_20260513_0056`        | `cluster/qmm_ipv_live_thd_pc_20260514_1432`              |
| Google | `google_srrip_live_thd_pc_20260513_0056`     | `cluster/google_ipv_live_thd_pc_20260514_1432`           |
| GAP    | `gap_srrip_live_thd_pc_20260520_0059`        | `gap_ipv_live_thd_pc_20260520_0819`                      |
| GMS    | `gms_srrip_live_thd_pc_20260520_0128`        | `gms_ipv_live_thd_pc_20260520_0819`                      |
| Ligra  | `ligra_srrip_live_thd_pc_20260520_0059`      | `ligra_ipv_live_thd_pc_20260520_0819`                    |
| ML     | `ml_srrip_live_thd_pc_20260520_0059`         | `ml_ipv_live_thd_pc_20260520_0819`                       |

LRU baselines: `results/{suite}_repl_pol_20260522_0722/lru_baseline/`

### STLB threshold data (Figure 3)

| Suite  | SRRIP-Live result dir                         | IPV-Live result dir                                    |
|--------|-----------------------------------------------|--------------------------------------------------------|
| DPC3   | `dpc3_pc_bypass_20260522_0101`                | `dpc3_pc_bypass_20260522_0101`                         |
| QMM    | `qmm_pc_bypass_20260522_0101`                 | `qmm_pc_bypass_20260522_0101`                          |
| Google | `google_pc_bypass_20260522_0101`              | `google_pc_bypass_20260522_0101`                       |
| GAP    | `gap_pc_bypass_20260522_0101`                 | `gap_pc_bypass_20260522_0101`                          |
| GMS    | `gms_pc_bypass_20260522_1958`                 | `gms_pc_bypass_20260522_1958`                          |
| Ligra  | `ligra_pc_bypass_20260522_1958`               | `ligra_pc_bypass_20260522_1958`                        |
| ML     | `ml_pc_bypass_20260522_0101`                  | `ml_pc_bypass_20260522_0101`                           |

**Config**: Config A — 2 MB LLC, 1,536-entry STLB.  
**⚠ Rerun pending**: A Mazumdar-config (Config C — 2 MB LLC, 1,024-entry STLB, 8-way)
threshold sweep for QMM and Google was submitted 2026-06-01 into
`results/qmm_maz_thd_20260601_1537/` and `results/google_maz_thd_20260601_1537/`
(Castillo job arrays 1403838–1403879). Once complete, regenerate both figures with
the new data and update the plot scripts' directory constants.

---

## Simulation config in use at plot-generation time

```
champsim_config.json commit: cbc12a70bcce (liveness-guided-replacement)
LLC:  2048 sets × 16 ways × 64 B = 2 MB,  latency 40 cycles
STLB: 128 sets  ×  8 ways        = 1,024 entries, latency 8 cycles  ← Config C
      (existing result data used 1,536-entry STLB = Config A)
L1I:  64×8, 4 cy   L1D: 64×8, 5 cy   L2C: 512×8, 11 cy
DRAM: 3200 MHz, 1 ch, tRP/tRCD/tCAS = 12.5 ns
```

To regenerate all plots from scratch:
```bash
python3 scripts/analysis/plot_liveness_rates.py
python3 scripts/analysis/plot_llc_threshold_combined.py
python3 scripts/analysis/plot_stlb_threshold_combined.py
```
