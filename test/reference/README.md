# Reference outputs (manual diff, no harness)

`outputs/<policy>_<condition>_<trace>.out` are 60 pinned full-report outputs
from the liveness-replacement-policy work, kept so a suspicious code change
can be checked by hand (`diff` a fresh run against the matching file here).
There is deliberately no test runner, CMake integration, or CI wiring around
these: This directory just contains the reference results and the information
needed to reproduce a run.

## Scenario naming

`<policy>_<condition>_<trace>`, e.g. `lru_duel_cactus`. 3 policies × 5
conditions × 4 traces = 60 files.

- **policy**: `lru`, `srrip`, `ipv`
- **condition**: `base` (non-liveness baseline), `fixed` (liveness, fixed
  insertion config), `bypass` (DoA blocks bypass the LLC), `duel` (set
  dueling against the base arm), `addr` (per-address history indexing,
  `REPL_HIST_MODE=addr`, bounded 4K table + `lfu_doa` eviction)
- **trace**: `pr` (ligra PageRank), `cactus` (607.cactuBSSN), `bwaves`
  (603.bwaves), `qmm` (srv_12) — chosen so every mechanism is actually active
  on at least one trace, not just exercised as an isolated knob

## Traces

The four traces aren't interchangeable — each is picked for a specific reason,
since the mechanisms here only show up when the workload actually triggers
them:

| key | path | why this one |
|---|---|---|
| `pr` | `trace-files/ligra/ligra_PageRank.com-lj.ungraph.gcc_6.3.0_O3.drop_51000M.length_250M.champsimtrace.xz` | Graph workload where dead-on-arrival blocks are common — exercises LLC bypass and the aggressive duel arm. |
| `cactus` | `<dpc3 shared mount>/607.cactuBSSN_s-3477B.champsimtrace.xz` | Many distinct PCs keep the history table genuinely active (not just idle), and its temporal-reuse pattern is where the gentle, non-bypass arm wins — the counterweight to `pr`. |
| `bwaves` | `<dpc3 shared mount>/603.bwaves_s-891B.champsimtrace.xz` | Streaming access pattern where LLC bypass has its largest impact; also ~4x faster to simulate than the lbm trace originally used for this role, same coverage. |
| `qmm` | `trace-files/QMM/srv_12.champsimtrace.xz` | Many-PC workload structurally different from `cactus` — guards against the history-table behavior being an artifact of one trace's specific PC distribution. |

`<dpc3 shared mount>` is `/home/users/shared/traces/dpc3_traces` on Castillo.

## Run settings

Each scenario is one invocation of a policy binary:

```sh
<binary> --warmup_instructions 50000000 --simulation_instructions 100000000 <trace>
```

with the condition's env vars (below) set beforehand. The reference file is
the full stdout, with the one nondeterministic line (the wall-clock
` (Simulation time: H hr M min S sec)` suffix) stripped before comparing —
everything else is deterministic given the same binary + trace.

### Binary and env vars per policy × condition

| policy | condition | binary | env vars |
|---|---|---|---|
| lru | base | `champsim_lru` | (none) |
| lru | fixed | `champsim_lru_live` | `THD_DOA=6 SRRIP_LIVE_TARGET=llc LRU_LIVE_DOA_INS=2n3` |
| lru | bypass | `champsim_lru_live` | above `base` fragment + `LRU_LIVE_DOA_INS=bypass` |
| lru | duel | `champsim_lru_live` | `base` fragment + `LRU_LIVE_DOA_INS=2n3 LRU_LIVE_DOA_INS_B=lru DUEL_N_SAMPLERS=32 DUEL_METRIC=latency` |
| lru | addr | `champsim_lru_live` | `base` fragment + `LRU_LIVE_DOA_INS=2n3` + `REPL_HIST_MODE=addr REPL_HIST_LLC_CAP=4096 REPL_HIST_REPL=lfu_doa` |
| srrip | base | `champsim_srrip` | (none) |
| srrip | fixed | `champsim_srrip_live` | `base` fragment |
| srrip | bypass | `champsim_srrip_live` | `base` fragment + `SRRIP_LIVE_TARGET=none LIVENESS_BYPASS=1` |
| srrip | duel | `champsim_srrip_live` | `base` fragment + `SRRIP_DOA_INS_RRPV=2 SRRIP_DOA_HIT_RRPV=2 SRRIP_DOA_INS_RRPV_B=3 SRRIP_DOA_HIT_RRPV_B=0 DUEL_N_SAMPLERS=32` |
| srrip | addr | `champsim_srrip_live` | `base` fragment + `addr` fragment |
| ipv | base | `champsim_ipv` | (none) |
| ipv | fixed | `champsim_ipv_live` | `base` fragment |
| ipv | bypass | `champsim_ipv_live` | `SRRIP_LIVE_TARGET=none LIVENESS_BYPASS=1` |
| ipv | duel | `champsim_ipv_live` | `base` fragment + `DUEL_N_CONFIGS=2 DUEL_N_SAMPLERS=32 DUEL_METRIC=latency` |
| ipv | addr | `champsim_ipv_live` | `base` fragment + `addr` fragment |

`base` fragment = `THD_DOA=6 SRRIP_LIVE_TARGET=llc`. `addr`
fragment = `REPL_HIST_MODE=addr REPL_HIST_LLC_CAP=4096 REPL_HIST_REPL=lfu_doa`.

Earlier runs of this matrix also set `BHIST_MODE=pc` in the base fragment;
it's dropped here because it's no longer read anywhere in the codebase
(removed along with the dpPred/cbPred subsystem, the only thing that ever
consumed it) — the 60 outputs above were regenerated without it and are
unaffected, since it was already a no-op before removal too.

### IPV mechanism

`champsim_ipv`/`champsim_ipv_live` implement IPV as a **full k-way
permutation** (Jimenez, MICRO 2013): each LLC set is a strict order/rank
permutation over all `NUM_WAY` positions, like real LRU. Default vector: 
Jimenez's WI-GIPPR (16-way), resampled for Redwood Cove's 12-way LLC; 
DoA defaults to that vector floor-clamped at `floor(2*NUM_WAY/3)`, 
same ratio `lru_live.cc` uses.

## Provenance

Generated on commit **`0ebb15cfac7730dbad71cf7590f42156fc54c36d`**
(2026-07-17) from the current `champsim_config.json` (Redwood Cove).

