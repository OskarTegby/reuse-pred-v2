# Configs snapshot — commit 0443feaae590

Snapshot of all files needed to understand and reproduce the simulation runs
documented in DATA_LOG.md (new QMM runs, 2026-06-02). These are copies from
the repo at commit `0443feaae590` on branch `liveness-guided-replacement`.

The canonical source is the git repo; these copies exist so the setup is
self-contained in the paper directory even if the repo is unavailable.

---

## champsim_maz_policies.json

ChampSim configuration array defining all binaries used in the new runs.
Each entry specifies the full cache hierarchy (LLC 2048×16 = 2 MB, STLB 128×8
= 1,024 entries) and the replacement policy for LLC and/or STLB.

Binaries defined:

| Executable | LLC repl | STLB repl | Used for |
|---|---|---|---|
| champsim_lru | lru | lru | LRU baseline |
| champsim_srrip | srrip | lru | SRRIP baseline |
| champsim_lru_live | lru_live | lru | LRU-Live LLC sweep |
| champsim_srrip_live | srrip_live | lru | SRRIP-Live LLC sweep |
| champsim_ipv_live | ipv_live | lru | IPV-Live LLC sweep |
| champsim_stlb_srrip_live | lru | srrip_live | SRRIP-Live STLB sweep |
| champsim_stlb_ipv_live | lru | ipv_live | IPV-Live STLB sweep |

Build with:
```
./config.sh champsim_maz_policies.json
make static
```

---

## run_cs.sh

SGE job script. Reads environment variables set by qsub -v:
- `BINARY` — executable name (without path)
- `TRACE_DIR`, `TRACE_EXT` — trace location and extension
- `WARMUP`, `SIM` — instruction counts
- `RUN_LABEL` — output subdirectory under results/
- `MID_THD`, `LOW_THD` — DoA and mostly-dead classification thresholds
- `BHIST_MODE` — liveness history indexing mode (pc | addr | flat)
- `SRRIP_LIVE_TARGET` — which cache level gets guidance (llc | stlb | both)

The SGE task ID (`$SGE_TASK_ID`) indexes into the sorted trace list to pick
one trace per job.

---

## sweep_mazumdar_threshold.sh

Submission wrapper that launches all policies for a given suite in one call.
Used with `--llc-only` for the LLC sweeps; run without the flag for LLC+STLB.

---

## cache.cc and cache.h

Core liveness tracking implementation. Key functions/structs:

**cache.h:**
- `struct ReplHistEntry { uint64_t doa; uint64_t dead; }` — per-PC counters
- `std::unordered_map<uint64_t, ReplHistEntry> repl_hist_pc` — the table
- `enum class liveness_class { doa, mostly_dead, mostly_alive }`
- `liveness_class classify_block_liveness(uint64_t addr, uint64_t ip)` — reads
  counters against MID_THD / LOW_THD env vars to classify a new insertion
- `BLOCK` fields: `accessed` (bool), `install_cycle`, `last_hit_cycle` (uint64_t)

**cache.cc:**
- `try_hit`: sets `way->accessed = true` and `way->last_hit_cycle` for all
  LLC/STLB hits (unconditional — not gated on any cbpred flag)
- `handle_fill`: classifies evicted block into doa/mostly_dead/mostly_alive
  using the halflife criterion (`time_til_end <= lifetime/2` → mostly_alive),
  then calls `update_eviction_counters`
- `update_eviction_counters`: increments/resets per-PC counters:
  - doa eviction → `doa++`
  - mostly_dead eviction → `dead++`, `doa = 0`
  - mostly_alive eviction → `doa = 0`, `dead = 0`

---

## replacement/

Snapshots of the three liveness-guided replacement policies.

**srrip_live.cc** — SRRIP with per-class insertion RRPV and hit promotion:
- DoA insert: maxRRPV (3); hit: maxRRPV−1 (2)
- Mostly-dead insert: maxRRPV−1 (2); hit: maxRRPV−2 (1)
- Mostly-alive insert: maxRRPV−1 (2); hit: 0
- Hit promotion uses class stored at insertion time (not re-classification)

**ipv_live.cc** — IPV with one vector per liveness class:
- DoA:          {0,0,1,2,3} — insert 3; 3→2→1→0
- Mostly-dead:  {0,0,0,2,3} — insert 3; 3→2→0
- Mostly-alive: {0,0,0,0,2} — insert 2; 2→0

**lru_live.cc** — LRU with position-biased insertion:
- DoA insert at rank N−1−⌊2N/3⌋ from LRU end (position ⌊2N/3⌋ from MRU)
- Mostly-dead insert at rank N−1−⌊N/3⌋ (position ⌊N/3⌋ from MRU)
- Mostly-alive insert at rank N−1 (MRU, same as standard LRU)
- All hits promote to MRU (no hit differentiation by class)
- For N=16: DoA→rank 5, mostly-dead→rank 10, mostly-alive→rank 15
