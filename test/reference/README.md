# Reference outputs (manual diff, no harness)

`outputs/<policy>_<condition>_<trace>.out` are 60 pinned full-report outputs
from the liveness-replacement-policy work, kept so a suspicious code change
can be checked by hand (`diff` a fresh run against the matching file here).
There is deliberately no test runner, CMake integration, or CI wiring around
these — that infrastructure (`test/blackbox/`) was removed on 2026-07-16
because maintaining it was costing more time than it saved. This directory is
just the goldens plus the information needed to reproduce a run.

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

| key | path |
|---|---|
| `pr` | `trace-files/ligra/ligra_PageRank.com-lj.ungraph.gcc_6.3.0_O3.drop_51000M.length_250M.champsimtrace.xz` |
| `cactus` | `<dpc3 shared mount>/607.cactuBSSN_s-3477B.champsimtrace.xz` |
| `bwaves` | `<dpc3 shared mount>/603.bwaves_s-891B.champsimtrace.xz` |
| `qmm` | `trace-files/QMM/srv_12.champsimtrace.xz` |

`<dpc3 shared mount>` was `/home/users/shared/traces/dpc3_traces` on Castillo.

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
| lru | fixed | `champsim_lru_live` | `THD_DOA=6 BHIST_MODE=pc SRRIP_LIVE_TARGET=llc LRU_LIVE_DOA_INS=2n3` |
| lru | bypass | `champsim_lru_live` | above `base` fragment + `LRU_LIVE_DOA_INS=bypass` |
| lru | duel | `champsim_lru_live` | `base` fragment + `LRU_LIVE_DOA_INS=2n3 LRU_LIVE_DOA_INS_B=lru DUEL_N_SAMPLERS=32 DUEL_METRIC=latency` |
| lru | addr | `champsim_lru_live` | `base` fragment + `LRU_LIVE_DOA_INS=2n3` + `REPL_HIST_MODE=addr REPL_HIST_LLC_CAP=4096 REPL_HIST_REPL=lfu_doa` |
| srrip | base | `champsim_srrip` | (none) |
| srrip | fixed | `champsim_srrip_live` | `base` fragment |
| srrip | bypass | `champsim_srrip_live` | `base` fragment + `SRRIP_LIVE_TARGET=none LIVENESS_BYPASS=1` |
| srrip | duel | `champsim_srrip_live` | `base` fragment + `SRRIP_DOA_INS_RRPV=2 SRRIP_DOA_HIT_RRPV=2 SRRIP_DOA_INS_RRPV_B=3 SRRIP_DOA_HIT_RRPV_B=0 DUEL_N_SAMPLERS=32` |
| srrip | addr | `champsim_srrip_live` | `base` fragment + `addr` fragment |
| ipv | base | `champsim_ipv` | (none) |
| ipv | fixed | `champsim_ipv_live` | `base` fragment + `IPV_DOA=0:1:2:2:3` |
| ipv | bypass | `champsim_ipv_live` | `base` fragment + `SRRIP_LIVE_TARGET=none LIVENESS_BYPASS=1` + `IPV_DOA=0:1:2:2:3` |
| ipv | duel | `champsim_ipv_live` | `base` fragment + `DUEL_N_CONFIGS=2 DUEL_N_SAMPLERS=32 IPV_DOA_0=0:1:2:2:2 IPV_DOA_1=0:1:2:2:3 DUEL_METRIC=latency` |
| ipv | addr | `champsim_ipv_live` | `base` fragment + `IPV_DOA=0:1:2:2:3` + `addr` fragment |

`base` fragment = `THD_DOA=6 BHIST_MODE=pc SRRIP_LIVE_TARGET=llc`. `addr`
fragment = `REPL_HIST_MODE=addr REPL_HIST_LLC_CAP=4096 REPL_HIST_REPL=lfu_doa`.

## Provenance

Generated on commit **`f4b985ea553b0a608bc93906a3834e585fa592bd`**
(2026-07-08, "test: update expected outputs from cluster full runs" — on
`main` at the time, later inherited by `blackbox-refactor`), built from
**`champsim_maz_policies.json`** (LLC 2048 sets × 16 ways, L2C 2048×16) — not
`champsim_config.json`. That config file was itself archived in
`60284871dd6a` ("archive everything non-Redwood-Cove"); its exact content at
generation time is still recoverable with:

```sh
git show f4b985ea553b:champsim_maz_policies.json
```

## Known caveats — read before diffing

1. **Not reproducible from the current `champsim_config.json`.** That file
   now only builds the Redwood Cove architecture (LLC 4096×12) and defines
   just 4 executables (`champsim_lru`, `champsim_srrip`, `champsim_lru_live`,
   `champsim_srrip_live` — no `ipv`/`ipv_live` at all). None of these 60
   references can be regenerated from today's default build; you'd need to
   resurrect `champsim_maz_policies.json` from history first (see above) and
   build against that.

2. **One statistic is known-stale as of one day after generation.** Commit
   `984706a8eebf` (2026-07-09, "feat: allocate history-table entries only on
   DoA evictions") changed the liveness history table so an alive eviction of
   an untracked key no longer allocates a zero entry or records a
   transition. Any non-`base` (i.e. `*_live`) scenario run against current
   `inc/cache.h`/`src/cache.cc` can show a diff confined to the
   transition/entry-count statistic from this change alone — that is a real,
   expected difference from this one commit, not a regression. `base`
   scenarios (no history table involved) are unaffected. If you need a clean
   diff against current behavior, regenerate first (`GENERATE=1` against the
   reconstructed binaries, matching the invocation above).
