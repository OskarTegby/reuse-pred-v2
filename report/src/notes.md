# Report design notes

## Figure organization

### Two-figure split (decided 2026-05-24)

Per-suite geomean masks too much intra-suite variance to be meaningful as the
primary result. Use **per-workload bars at individually optimal threshold** as
the primary figure; geomean can appear as a secondary overview if needed.

Figures are split into two groups:

| Group | Suites | Rationale |
|---|---|---|
| **Mazumdar domain** | DPC3, GAP, Ligra | Benchmark families from Mazumdar et al. (HPCA 2021) |
| **New domains** | Google, QMM, GMS, ML | Not evaluated by Mazumdar — novel contribution |

### Mazumdar's 14 workloads (Table II, HPCA 2021)

Mazumdar used: cactusADM, cc, cg.B, sssp, lbm, Triangle, KCore, canneal, pr,
graph500, bfs, bc, mis, mcf — drawn from SPEC, GAPBS, NAS, PARSEC, Ligra.

Mapping to our traces:
- SPEC → DPC3 (`607.cactuBSSN_s`, `619.lbm_s`, `605.mcf_s`, ...)
- GAPBS → GAP (`bc-*`, `cc-*`, `sssp-*`, `pr-*`, `graph500-*`, `bfs-*`)
- Ligra → Ligra (`ligra_Triangle.*`, `ligra_MIS.*`, ...)
- NAS (cg.B) and PARSEC (canneal) — **not available in our trace set**

So "Mazumdar domain" = DPC3 + GAP + Ligra suites (closest available match).

### Suite ordering (use consistently throughout)

SPEC (DPC3) → Qualcomm (QMM) → Google → GAP → GMS → Ligra → AI/ML

---

## Generated figures (results/plots/)

| File | Contents | Script |
|---|---|---|
| `optimal_thd_all7_pc.png` | Per-workload srrip_live, PC-indexed, all 7 suites, 4 per suite | `plot_optimal_thd_per_benchmark.py` |
| `optimal_thd_all7_addr.png` | Per-workload srrip_live, addr-indexed, all 7 suites | same |
| `optimal_thd_all7_srrip_ipv_pc.png` | Per-workload srrip_live + ipv_live, PC-indexed, all 7 suites | same |
| `pol/{suite}_missing_policy_ipc.png` | LLC+STLB combined policy comparison, per suite | `plot_suite_comparison.py` |

Pol dirs for new suites (GAP/GMS/Ligra/ML) are symlinked under
`results/.tmp_pol_combined/` because the 2026-05-21 pol dirs were empty.
LRU/SRRIP data lives in the older cluster pol dirs.
