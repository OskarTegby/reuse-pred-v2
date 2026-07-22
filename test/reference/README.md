# Reference outputs (manual diff, no harness)

`outputs/<policy>_<condition>_<trace>.out` are 48 pinned full-report outputs
from the liveness-replacement-policy work, kept so a suspicious code change
can be checked by hand (`diff` a fresh run against the matching file here).
There is deliberately no test runner, CMake integration, or CI wiring around
these: This directory just contains the reference results and the information
needed to reproduce a run.

## Scenario naming

`<policy>_<condition>_<trace>`, e.g. `lru_fixed_cactus`. 3 policies × 4
conditions × 4 traces = 48 files.

- **policy**: `lru`, `srrip`, `ipv`
- **condition**: `base` (non-liveness baseline), `fixed` (liveness, fixed
  insertion config), `bypass` (DoA blocks bypass the LLC), `addr` (per-address
  history indexing, `REPL_HIST_MODE=addr`, bounded 4K table + `lfu_doa`
  eviction)
- **trace**: `pr` (ligra PageRank), `cactus` (607.cactuBSSN), `bwaves`
  (603.bwaves), `qmm` (srv_12) — chosen so every mechanism is actually active
  on at least one trace, not just exercised as an isolated knob

## Traces

The four traces aren't interchangeable — each is picked for a specific reason,
since the mechanisms here only show up when the workload actually triggers
them:

| key | path | why this one |
|---|---|---|
| `pr` | `trace-files/ligra/ligra_PageRank.com-lj.ungraph.gcc_6.3.0_O3.drop_51000M.length_250M.champsimtrace.xz` | Graph workload where dead-on-arrival blocks are common — exercises LLC bypass and aggressive insertion. |
| `cactus` | `<dpc3 shared mount>/607.cactuBSSN_s-3477B.champsimtrace.xz` | Many distinct PCs keep the history table genuinely active (not just idle) — the counterweight to `pr`. |
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
| lru | addr | `champsim_lru_live` | `base` fragment + `LRU_LIVE_DOA_INS=2n3` + `REPL_HIST_MODE=addr REPL_HIST_LLC_CAP=4096 REPL_HIST_REPL=lfu_doa` |
| srrip | base | `champsim_srrip` | (none) |
| srrip | fixed | `champsim_srrip_live` | `base` fragment |
| srrip | bypass | `champsim_srrip_live` | `base` fragment + `SRRIP_LIVE_TARGET=none LIVENESS_BYPASS=1` |
| srrip | addr | `champsim_srrip_live` | `base` fragment + `addr` fragment |
| ipv | base | `champsim_ipv` | (none) |
| ipv | fixed | `champsim_ipv_live` | `base` fragment |
| ipv | bypass | `champsim_ipv_live` | `SRRIP_LIVE_TARGET=none LIVENESS_BYPASS=1` |
| ipv | addr | `champsim_ipv_live` | `base` fragment + `addr` fragment |

Note: `fixed`/`addr` explicitly pass `LRU_LIVE_DOA_INS=2n3` for `lru` — this
was the conservative option, pinned here as an explicit override so these
scenarios keep testing that specific configuration regardless of what the
code's own default happens to be (see Provenance: the default changed to
the aggressive option, `lru`/rank-0, on 2026-07-21, but explicit overrides
are unaffected by that change). `srrip`/`ipv`'s `fixed` scenarios don't
override the insertion RRPV/floor at all, so they now exercise whatever the
current default is — the aggressive option, as of the same change.

`base` fragment = `THD_DOA=6 SRRIP_LIVE_TARGET=llc`. `addr`
fragment = `REPL_HIST_MODE=addr REPL_HIST_LLC_CAP=4096 REPL_HIST_REPL=lfu_doa`.

Earlier runs of this matrix also set `BHIST_MODE=pc` in the base fragment;
it's dropped here because it's no longer read anywhere in the codebase
(removed along with the dpPred/cbPred subsystem, the only thing that ever
consumed it) — the 60 outputs above were regenerated without it and are
unaffected, since it was already a no-op before removal too.

As of the 2026-07-21 regeneration (see Provenance below), `REPL_HIST_LLC_CAP`
and `REPL_HIST_REPL` in the `addr` fragment are also no-ops: the history
table is now a fixed-size 256-entry array with no runtime-configurable size
or eviction policy, so neither env var is read. They're kept in the
fragment above only so the `addr` scenarios' full env-var history stays
visible; removing them would change nothing.

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

The 48 `_live`-active outputs (`fixed`/`bypass`/`duel`/`addr` conditions,
excluding `base`) were regenerated on 2026-07-19 after removing the
phase-boundary reset of `HistTable`/`_live`-policy stats from
`CACHE::begin_phase()`: those stats are printed exactly once, after all
phases, from `impl_replacement_final_stats()`, entirely independent of the
phase/warmup-filtered `sim_stats`/`roi_stats` pipeline, so resetting them
at the warmup/ROI boundary never matched how they're actually reported.
The printed `repl_hist`/insert-mix/lifespan block for these 48 outputs now
reflects combined warmup+ROI activity instead of ROI-only; the 12 `base`
outputs are unaffected (that binary never calls
`replacement_final_stats()`) and remain byte-identical to the commit
above.

The same 48 outputs were regenerated again on 2026-07-20 after a series
of follow-up simplifications to `HistTable` (shadow/buffer/promotion
subsystem removal, unused config knobs, the `Stats` struct, and the
`evict_attr` diagnostic fields — see the `champsim-source-refactor`
branch history for the itemized list). The only behavior change with any
potential to affect simulated results was simplifying `Entry::freq`'s
update rule to grow only on DoA-classified hits (no more decay on alive
hits) — verified via a full 60-scenario cluster run to produce **zero**
cache-level differences (IPC, hit/miss counts, bypass counts) anywhere,
including the 12 `addr` scenarios that actually exercise bounded-mode
eviction: `classify()` compares `Entry::score`, not `freq`, and `freq`
only influences which entries `HistTable` itself retains internally, not
the classification decision for a currently-tracked key. Every diff
across all 48 outputs is confined to the `repl_hist` block shrinking to
reflect the removed instrumentation; the 12 `base` outputs remain
untouched.

The 48 `_live`-active outputs were regenerated once more on **2026-07-21**
(commit **`a555e8508152`**, branch `hist-table-hashing`) after replacing
`HistTable` entirely: the tagged `unordered_map`/`vector<Entry>` storage
(with real recency/frequency-weighted eviction) was dropped in favor of a
single fixed **256-entry array of flat, tag-less saturating counters**,
indexed by `(pc ^ (pc>>2) ^ (pc>>5)) % 256`. This is **not**
behavior-preserving by design: two PCs that hash to the same slot now
silently alias (whichever last updated it wins), and there is no more
eviction policy for the table itself — direct-indexed writes just
overwrite in place. Every one of the 48 outputs differs from the prior
pinned version as a result, but the differences are small and consistent
with hash aliasing rather than a broken predictor: IPC/cycle counts shift
by roughly 0.01–0.02% (e.g. `lru_fixed_pr`: cycles 75883372 → 75894352,
cumulative IPC 1.31782 → 1.31763), and the printed `repl_hist` block's
*format* changed completely (from `unbounded (N entries)` /
`bounded (N/cap)` to a flat `occupancy: main N/256 (P%)`), independent of
any actual behavior change. The 12 `base` outputs are unaffected, as
always. If a future diff against these 48 files shows changes far
larger than this — a different policy's IPC moving by more than a
fraction of a percent, for instance — that's a signal to look for an
actual regression, not this rewrite.

