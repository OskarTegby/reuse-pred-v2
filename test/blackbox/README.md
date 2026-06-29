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
| **trace** | `pr` — ligra PageRank | graph DoA: exercises bypass and the aggressive duel arm |
| | `cactus` — 607.cactuBSSN | many PCs → history table active; temporal reuse → the gentle arm wins |
| | `lbm` — 619.lbm | streaming → bypass has a large impact |
| | `qmm` — srv_12 | many PCs, a different workload from cactus |

A scenario is named `<policy>_<condition>_<trace>` (e.g. `lru_duel_cactus`). The
runner executes ChampSim on that trace (50M warmup + 100M sim), strips the one
nondeterministic line (the wall-clock `Simulation time` suffix), and byte-diffs
the **entire** report against `expected/<scenario>.out`.

`run_scenario.sh --list` enumerates all scenarios and is the single source of
truth — `CMakeLists.txt`, `blackbox_validation.sh`, and `blackbox_run_cluster.sh`
all derive their lists from it.

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
~4%), scoring modes other than 5, the comma-vs-colon parser variants, and the
3-way duel. If one of these is revived, add it back as a condition.

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

The hold only exists to let the bb jobs grab slots promptly, so it is released as
soon as every bb job has **started running** (or after `HOLD_MAX`, default 600s,
regardless) — *not* at the end of verification. Otherwise one slow or stuck bb job
would keep the rest of the cluster held for hours.

### Incremental verification

In verify mode the driver does not wait for jobs to finish before judging them.
Each poll it pulls the partial outputs and classifies every scenario against its
reference with `check_progress.sh`:

| State | Meaning |
|---|---|
| `PENDING` | no usable output yet |
| `RUNNING` | output is a correct prefix of the reference, < 50M sim done |
| `SOFT_PASS` | correct prefix **and** the 50M-sim heartbeat reached — most likely to pass |
| `FULL_PASS` | output matches the reference exactly — fully verified |
| `FAIL` | a completed line diverged from the reference |

Because every non-wallclock line is deterministic, a partial output is a clean
line-prefix of the reference: any mismatch in an already-written line is a real
failure, caught the moment it appears rather than after the full run. On `FAIL`
the driver prints the diff and cancels the doomed job (`qdel bb_<scenario>`). The
soft-pass milestone is the heartbeat at 100,000,000 total instructions — 50M
warmup plus 50M of the 100M simulation, i.e. half the run verified and on-track.
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
