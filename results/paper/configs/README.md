# Configs snapshot — branch history-table-instrumentation (2026-06-03)

Snapshot of all files needed to understand and reproduce the simulation runs
documented in DATA_LOG.md. These are copies from the repo on branch
`history-table-instrumentation` (merging into `liveness-guided-replacement`).

The canonical source is the git repo; these copies exist so the setup is
self-contained in the paper directory even if the repo is unavailable.

---

## champsim_maz_policies.json

ChampSim configuration array defining all binaries used in the runs.
Each entry specifies the full cache hierarchy (LLC 2048×16 = 2 MB, STLB 128×8
= 1,024 entries) and the replacement policy for LLC and/or STLB.

| Executable | LLC repl | STLB repl | Used for |
|---|---|---|---|
| champsim_lru | lru | lru | LRU baseline |
| champsim_srrip | srrip | lru | SRRIP baseline |
| champsim_lru_live | lru_live | lru | LRU-Live LLC sweep |
| champsim_srrip_live | srrip_live | lru | SRRIP-Live LLC sweep |
| champsim_ipv_live | ipv_live | lru | IPV-Live LLC sweep |
| champsim_stlb_lru_live | lru | lru_live | LRU-Live STLB sweep |
| champsim_stlb_srrip_live | lru | srrip_live | SRRIP-Live STLB sweep |
| champsim_stlb_ipv_live | lru | ipv_live | IPV-Live STLB sweep |
| champsim_both_srrip_live | srrip_live | srrip_live | Combined LLC+STLB SRRIP-Live |
| champsim_both_ipv_live | ipv_live | ipv_live | Combined LLC+STLB IPV-Live |

Build with:
```
./config.sh champsim_maz_policies.json
make static
```

---

## run_cs.sh

SGE job script. Key env vars (set via qsub -v):
- `BINARY` — executable name
- `TRACE_DIR`, `TRACE_EXT`, `WARMUP`, `SIM`, `RUN_LABEL`
- `MID_THD`, `LOW_THD` — classification thresholds (shared across levels)
- `LLC_MID_THD`, `LLC_LOW_THD` — per-level override for LLC
- `STLB_MID_THD`, `STLB_LOW_THD` — per-level override for STLB
- `SRRIP_LIVE_TARGET` — which cache level gets guidance (llc | stlb | both)
- `REPL_HIST_LLC_CAP`, `REPL_HIST_STLB_CAP` — history table capacity (0 = unbounded)
- `REPL_HIST_BUF_CAP` — promotion buffer size (0 = disabled)
- `REPL_HIST_SHADOW_CAP` — shadow+oracle buffer size for instrumentation (0 = disabled)
- `REPL_HIST_CHECKPOINT` — print occupancy to stderr every N updates (0 = disabled)
- `REPL_HIST_REPL` — table replacement policy (lru | lfu | lfu_doa | srrip)

---

## cache.h — HistTable class

Bounded or unbounded PC-indexed history table with pluggable replacement.

**Key design:**
- Default constructor → unbounded mode (unordered_map, backward compatible)
- `HistTable(cap, pol, buf_cap, shadow_cap)` → bounded mode
- `update(key, liveness_class)` — update counters on eviction
- `classify(key, mid_thd, low_thd)` — look up main table then promotion buffer;
  tracks whether classification came from main / buf_guided / buf_weak
- `print_stats(prefix, mid_thd, low_thd)` — prints full instrumentation at end
  of simulation: occupancy, classification source breakdown, shadow/oracle stats

**Classification source stats:**
- `classify_main` — resolved from main table
- `classify_buf_guided` — resolved from promotion buffer (above threshold)
- `classify_buf_weak` — found in buffer but below threshold (demoted, count reset)
- `classify_warm_miss` — PC was seen before but entry evicted (accuracy loss)
- `classify_cold_miss` — PC never seen (expected, no history exists)
- `classify_warm_oracle_hit` — subset of warm_miss recoverable by infinite buffer

---

## cache.cc

Key functions:
- `load_predictor_settings()`: reads all env vars, initialises HistTable with
  capacity/policy/buffer settings, sets up checkpoint if requested.
  Reads `LLC_MID_THD` / `STLB_MID_THD` as per-level threshold overrides.
- `classify_block_liveness(addr, pc)`: delegates to `repl_hist_pc.classify()`
- `update_eviction_counters(victim, lv)`: calls `repl_hist_pc.update()`

---

## replacement/

**srrip_live.cc** — SRRIP with per-class insertion RRPV and hit promotion:
- DoA insert: maxRRPV (3); hit: maxRRPV−1 (2)
- Mostly-dead insert: maxRRPV−1 (2); hit: maxRRPV−2 (1)
- Mostly-alive insert: maxRRPV−1 (2); hit: 0

**ipv_live.cc** — IPV with one vector per liveness class:
- DoA:          {0,0,1,2,3} — insert 3; 3→2→1→0
- Mostly-dead:  {0,0,0,2,3} — insert 3; 3→2→0
- Mostly-alive: {0,0,0,0,2} — insert 2; 2→0

**lru_live.cc** — LRU with position-biased insertion:
- DoA insert at rank N−1−⌊2N/3⌋ (2N/3 from MRU end)
- Mostly-dead insert at rank N−1−⌊N/3⌋ (N/3 from MRU end)
- Mostly-alive insert at MRU (standard LRU)
- All hits promote to MRU regardless of class

---

## Key results

**Optimal thresholds (unbounded, QMM 45 traces):**
| Level | Policy | Optimal thd | Speedup vs LRU |
|---|---|---|---|
| LLC | IPV-Live | 4 | +4.51% |
| LLC | SRRIP-Live | 4 | +3.56% |
| STLB | IPV-Live | 1 | +5.25% |
| STLB | SRRIP-Live | 1 | +5.13% |

**Bounded table accuracy loss (IPV-Live at optimal thd):**
| Config | Speedup | Loss vs unbounded |
|---|---|---|
| LLC unbounded | +4.51% | — |
| LLC 4096 entries | +3.92% | −0.59 pp |
| STLB unbounded | +5.25% | — |
| STLB 1024 entries | +3.54% | −1.71 pp |

**Size study (IPV-Live, QMM 45 traces):**
LLC curve is flat — no knee down to 128 entries (+3.11%).
STLB has sharp knee at 1024→512 (+3.54% → +2.06%).
