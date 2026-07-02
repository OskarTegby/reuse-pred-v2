# Black-box regression tests

These tests guard the liveness techniques we **developed and chose to keep**, so
a future code change cannot silently corrupt experimental results. They are
**not** unit tests: nothing asserts an internal property in isolation. Each test
runs a real simulation end-to-end and pins its observable output, because the
failure mode that matters here is a seemingly innocent change that *compounds*
over millions of instructions and lands as a different IPC.

## What it tests — and why this shape

The suite is a matrix of **policy × condition × trace**. The traces are chosen so
that every kept mechanism is *actually active* in at least one cell — testing the
mechanism where it engages, not a knob in isolation on a synthetic trace.

| axis | values | role |
|------|--------|------|
| **policy** | `lru`, `srrip`, `ipv` | the three liveness replacement policies |
| **condition** | `base` | the non-liveness baseline policy — each policy's own reference point |
| | `fixed` | liveness, single fixed insertion config (no dueling) |
| | `bypass` | liveness with DoA blocks bypassing the LLC |
| | `duel` | liveness with set dueling, at each policy's kept metric (LRU/IPV: miss-latency; SRRIP: hit-count/PSEL) |
| | `addr` | liveness with **per-address** history indexing (`REPL_HIST_MODE=addr`), bounded 4K + lfu_doa eviction — guards the per-address ablation reported in the paper *and* the bounded-table eviction path (which the other conditions, running unbounded, never exercise) |
| **trace** | `pr` — ligra PageRank | graph DoA: exercises bypass and the aggressive duel arm |
| | `cactus` — 607.cactuBSSN | many PCs → history table active; temporal reuse → the gentle arm wins |
| | `bwaves` — 603.bwaves | streaming → bypass has a large impact (~4× faster to simulate than lbm) |
| | `qmm` — srv_12 | many PCs, a different workload from cactus |

A scenario is named `<policy>_<condition>_<trace>` (e.g. `lru_duel_cactus`). The
runner executes ChampSim on that trace (50M warmup + 100M sim), strips the one
nondeterministic line (the wall-clock `Simulation time` suffix), and byte-diffs
the **entire** report against `expected/<scenario>.out`.

`run_scenario.sh --list` enumerates all scenarios. `CMakeLists.txt`,
`blackbox_validation.sh`, and `blackbox_run_cluster.sh` all call it to get their
lists, rather than defining the matrix a second time.

## Why the full-report reference is enough

The reference output pins every cache counter and every liveness statistic. Because the
simulator is deterministic (same binary + same trace → bit-identical output),
zero tolerance is valid, and **no metric is hand-picked**: any compounding drift
moves *some* number and the diff catches it.

This is also why there are no separate winner-flip, threshold, or eviction
assertions. The set-dueling winner, the score→tier classification, and every
eviction decision are *already baked into* the report — if the duel selects a
different arm, a threshold reclassifies a block, or the history table evicts a
different PC, the IPC and counters move and the diff fires. We only have to make
sure each mechanism is *active* on some trace; trace selection does that.

## Deliberately not tested

Paths we explored but did **not** keep are intentionally absent, so the suite
tracks the shipped design rather than dead options: bypass set-dueling (regressed
~4%), the comma-vs-colon parser variants, and the 3-way duel. Mostly-dead
classification (the 3-way DoA/mostly-dead/mostly-alive scheme and its scoring-mode
zoo) was removed entirely — see the replacement-policy source for the rationale.
If one of these is revived, add it back as a condition.

## Running

```sh
cmake -S test/blackbox -B test/blackbox/cmake_build
ctest --test-dir test/blackbox/cmake_build -j8 --output-on-failure
```

A scenario whose binary or trace is missing reports as **skipped** (exit 77), not
failed, so the suite is safe to run on a partial build. Locally the dpc3/QMM
traces are usually absent, so most cells skip; the authoritative run is on the
cluster, where all traces and binaries exist:

```sh
bash scripts/submit/blackbox_run_cluster.sh            # verify against expected/
bash scripts/submit/blackbox_run_cluster.sh generate   # regenerate expected/ + commit
```

That driver holds queued jobs, submits the full suite, and then either copies the
finished outputs into `expected/` (generate) or **incrementally verifies** them
(verify, the default).

The held jobs are released as soon as **every bb job has launched** (none left
waiting for a slot) — not when they finish. The hold only exists to get the bb
jobs started ahead of the queue; once none are waiting, the already-running bb
jobs keep their slots and the queue resumes behind them. Releasing strictly at
"none waiting" is both starvation-free (no queued bb job loses its slot to the
resumed queue) and strangle-free (a hung *running* job does not delay the release,
since the trigger is launch, not completion). Separately, a watchdog cancels any
running bb job whose streamed output has not advanced for `STUCK_TIMEOUT` (default
900s) so the verify loop can finish; diverged jobs are still cancelled immediately
on the first mismatching line.

### Incremental verification

In verify mode the driver does not wait for jobs to finish before judging them.
Each poll it pulls the partial outputs and classifies every scenario against its
reference with `check_progress.sh`:

| State | Meaning |
|---|---|
| `PENDING` | no usable output yet |
| `RUNNING` | output is a correct prefix of the reference, < 20M sim done |
| `SOFT_PASS` | correct prefix **and** the 20M-sim heartbeat reached — most likely to pass |
| `FULL_PASS` | output matches the reference exactly — fully verified |
| `FAIL` | a completed line diverged from the reference |

Because every non-wallclock line is deterministic, a partial output is a clean
line-prefix of the reference: any mismatch in an already-written line is a real
failure, caught the moment it appears rather than after the full run. On `FAIL`
the driver prints the diff and cancels the doomed job (`qdel bb_<scenario>`). The
soft-pass milestone is the heartbeat at 70,000,000 total instructions — 50M
warmup plus 20M of the 100M simulation. It is a single tunable constant
(`SOFT_MILESTONE` in `check_progress.sh`); lowering it surfaces the soft pass
sooner (each 10M earlier ~ one heartbeat).
The run ends when every scenario is `FULL_PASS`/`FAIL`; the final report requires
`FULL_PASS` for all.

## Regenerating reference outputs

After an **intentional** behavior change, review the diff, then regenerate on the
cluster (`blackbox_run_cluster.sh generate`) and commit the updated
`expected/*.out` together with the code change so the reference update is
reviewable alongside what caused it.

## Adding a policy, condition, or trace

Edit the `POLICIES` / `CONDITIONS` / `TRACE_KEYS` arrays and the corresponding
`case` arm (and `trace_path`/`trace_dead`) in `run_scenario.sh`, then regenerate
the reference outputs. The CMake and cluster lists update themselves via `--list`.
