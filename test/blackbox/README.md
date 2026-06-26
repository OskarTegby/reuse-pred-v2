# Black-box regression tests

These tests guard the existing liveness replacement policies so a future code
change cannot silently corrupt experimental results. They are **not** unit
tests: nothing here asserts an internal property in isolation. Each test runs a
real simulation end-to-end and pins its observable output, because the failure
mode that matters in this simulator is a seemingly innocent change that
*compounds* over millions of instructions and lands as a different IPC.

## How it works

Each **scenario** names a binary (`bin/champsim_{lru,srrip,ipv}_live`) plus a
fixed environment, run on the deterministic `pagerank` trace (100 % DoA, four
load PCs). The runner captures the **entire** ChampSim report, strips the one
nondeterministic line (the wall-clock `Simulation time` suffix), and byte-diffs
it against `expected/<scenario>.<phase>.out`.

The golden file pins everything — every cache counter, the liveness statistics,
and (for the `*_cap256` scenarios) the `repl_hist` PC dump with each PC's DoA
and MD score. No metric is hand-picked: any compounding drift moves *some*
number and the diff catches it. Zero tolerance is valid because the simulator
is deterministic (same binary + same trace → bit-identical output).

A few **invariant** tests (`inv_*`) assert directional IPC relationships the
design depends on (e.g. bypass beats 2n3 insertion on a DoA trace, set-dueling
followers converge to the winning config). The goldens pin absolute output;
the invariants catch the orthogonal bug where a future change legitimately
updates the goldens but inverts a relationship.

## Two phases: gate and full

Each scenario runs in two phases that share the same warmup and differ only in
simulation length:

| phase  | sim instrs | wall  | role                          |
|--------|-----------:|------:|-------------------------------|
| `gate` |       250K | ~3 s  | fast early check (everyday)   |
| `full` |        2 M | ~25 s | thorough guard (pre-commit)   |

The gate is a CTest **fixture setup**; the full **requires** it. If the gate
fails, CTest skips that scenario's full automatically — no wasted 25 s on an
already-broken config, and no separate long suite that gets forgotten.

This is sound, not a shortcut: because warmup is identical and only the sim
window differs, the gate run is a true **prefix** of the full run. The first
250K ROI instructions are bit-identical whether you stop there or keep going,
so "gate passed" *proves* nothing diverged through that point — only the tail
can still differ, which is exactly what the full phase covers. The gate length
was chosen so the policies already separate clearly (e.g. bypass IPC 0.296 vs
2n3 0.225); tune `GATE_SIM` in `run_scenario.sh` if a new scenario needs longer
to become distinguishable.

## Running

```sh
cmake -S test/blackbox -B test/blackbox/cmake_build

# everyday loop: gates + invariants only, parallel (~15 s)
ctest --test-dir test/blackbox/cmake_build -L "gate|invariants" -j8 --output-on-failure

# thorough: gates then fulls (fulls auto-skipped where the gate failed)
ctest --test-dir test/blackbox/cmake_build -j8 --output-on-failure

ctest --test-dir test/blackbox/cmake_build -L full        # full diffs only
ctest --test-dir test/blackbox/cmake_build -L invariants  # ordering checks only
```

A scenario whose binary or trace is missing reports as **skipped** (exit 77),
not failed, so the suite is safe to run on a partial build.

## Regenerating goldens

After an **intentional** behavior change, review the diff, then regenerate both
phases:

```sh
GENERATE=1 bash test/blackbox/run_scenario.sh <scenario> gate
GENERATE=1 bash test/blackbox/run_scenario.sh <scenario> full
```

Commit the regenerated `expected/*.out` together with the code change so the
golden update is reviewable alongside what caused it.

## Adding a scenario

1. Add a `case` arm in `run_scenario.sh` (binary + env).
2. Add `cs_scenario(<name>)` in `CMakeLists.txt`.
3. Generate both phases (`gate` and `full`) and commit the new goldens.

## Note: the PC dump

The `*_cap256` scenarios set `REPL_HIST_DUMP_PCS=1`, which makes the history
table dump its resident PCs. That dump is gated behind the env var and is off
by default — it exists so these tests can pin *which* PCs the eviction policy
retains under a capacity bound (the meaningful check on many-PC QMM/SPEC
traces, where `cap256` actually evicts).
