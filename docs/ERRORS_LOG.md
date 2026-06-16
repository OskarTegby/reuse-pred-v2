# Errors Log

A running record of bugs and configuration mistakes that caused wasted cluster runs
or incorrect results. Kept to avoid repeating the same mistakes.

---

## 1. `SRRIP_LIVE_TARGET` empty-string export disables guidance

**What happened:** `run_cs.sh` exports `SRRIP_LIVE_TARGET=${SRRIP_LIVE_TARGET:-}`, which sets
the variable to an empty string when not supplied via `qsub -v`. `std::getenv` returns a
non-null pointer to `""`, so the `if (target_env)` branch is entered but matches nothing,
leaving `use_liveness = false`. All cluster runs of `champsim_srrip_live` and
`champsim_ipv_live` were running as plain SRRIP/IPV with no liveness guidance.

**Affected results:** Every SRRIP-Live and IPV-Live cluster run prior to the fix, including
all results used in the paper figures. Those results show SRRIP-vs-LRU improvement, not
liveness-guided improvement.

**Fix:** Check `target_env[0] != '\0'` before entering the if-branch.

**How to catch earlier:** Run a single trace on the cluster and check the `Activation rate`
line in SRRIP-Live stats. It should be non-zero; if it is zero, guidance is disabled.

---

## 2. `bhist` never populated without `CBPRED=1`

**What happened:** `update_eviction_counters` only updated `bhist_pc`/`bhist_flat` when
`cbpred=true && victim.dp=true`. With `CBPRED=0` (the default in all replacement runs),
the history table was always empty and `classify_block_liveness` always returned
`mostly_alive`. This bug was latent and masked by bug #1.

**Fix:** Added `repl_hist_pc` — a separate per-PC history table updated unconditionally for
all LLC/STLB evictions, keyed by `victim.ip`.

**How to catch earlier:** After a small test run, check the insert-mix stats. If DoA=0%
and Alive=100% for a workload known to have DoA blocks, the history is not being populated.

---

## 3. Re-classification on hits demotes live blocks

**What happened:** `update_replacement_state` called `classify_block_liveness` on every
hit, not just misses. A block inserted as alive (RRPV=2) whose PC later accumulated DoA
history was demoted to RRPV=2 on every hit instead of being promoted to RRPV=0. Live
blocks were never protected and got evicted prematurely. Introduced in `cb96843f17df`.

**Symptom:** DoA-classified blocks showing >100% hit rate; RRPV@evict showing 100% at
maxRRPV for both DoA and alive classes.

**Fix:** On hit, use the `slot_class` stored at insertion time rather than re-classifying.
Only re-classify on miss (insertion).

**How to catch earlier:** Check the hit-rate-per-class stats. A DoA hit rate above ~20%
is a strong signal of false positives or misprediction cascades.

---

## 4. `champsim_lru` built with wrong STLB size

**What happened:** `champsim_lru` was rebuilt from `champsim_lru_rebuild.json`, which only
specifies `LLC replacement: lru` and leaves all other parameters to ChampSim's built-in
defaults. The default STLB has 12 ways; the Mazumdar config requires 8 ways (1024 entries).
The resulting binary had a 50% larger TLB, inflating IPC by ~33% and making the LRU
baseline incomparable with the policy runs.

**Affected results:** `qmm_maz_thd_20260602_0810` — entire sweep cancelled.

**Fix:** Added `champsim_lru` to `champsim_maz_policies.json` so it is built from the same
base config as the policy binaries (which correctly inherits STLB 128×8 from
`champsim_config.json`).

**How to catch earlier:** After building any binary, verify the actual compiled cache
parameters in `.csconfig/<hash>/inc/core_inst.inc`. Specifically check LLC sets/ways and
STLB sets/ways match the intended configuration. Do not rely solely on the JSON input file.

---

## 5. Large sweeps submitted before verifying small test

**What happened (multiple times):**
- `liveness_char` sweep submitted before confirming the binary produces `LIVENESS_CHAR` output.
- `qmm_maz_thd` sweep submitted before verifying threshold sensitivity (thd=1 ≠ thd=8).
- `qmm_maz_thd_20260602_0810` sweep submitted before checking binary config matches intended cache sizes.

**Fix:** See `RESEARCH_METHODOLOGY.md`. Always run a 1–5 trace debug job (25M warmup /
50M sim) and verify the key metric before launching a full sweep.

---

## 6. `LIVENESS_CHAR` binary not rebuilt before sweep

**What happened:** The liveness characterisation sweep (`liveness_char_20260601_1907`) ran
with the pre-session `champsim_lru` binary that did not include `LIVENESS_CHAR` support.
All 251 outputs completed but contained no `LIVENESS_CHAR BEGIN/END` blocks.

**Fix:** Always check the binary timestamp vs when code changes were made. After rebuilding,
run a single trace directly on the cluster to confirm the expected output is present before
submitting the array job.

---

## 7. Binary verified locally but cluster jobs used different code path

**What happened:** Direct execution on Castillo (`MID_THD=1 ./bin/champsim_srrip_live ...`)
showed 100% activation rate. Cluster jobs (via `run_cs.sh`) showed 0% activation. The
difference: direct execution left `SRRIP_LIVE_TARGET` unset (null pointer); `run_cs.sh`
exported it as an empty string (non-null pointer). This is a distinct manifestation of
bug #1.

**Lesson:** Always verify behaviour through `run_cs.sh` (i.e. via a real cluster job), not
just by running the binary directly. The cluster execution environment differs from a direct
shell invocation in ways that matter.

---

## 8. `accessed` bit gated on `dp`, breaking liveness classification

**What happened:** In `try_hit`, `way->accessed` was only set for LLC blocks when
`way->dp == true`. Since `dp` marks cbpred-tagged blocks and `cbpred=0` in all
replacement runs, `accessed` was never set for any LLC block. Every evicted block was
therefore classified as DoA regardless of actual reuse, making the halflife criterion
and the mostly-dead path entirely non-functional.

**Root cause:** `dp` is a bypass-predictor field and has no business gating liveness
tracking. The liveness history (`repl_hist_pc`, `accessed`) must be independent of it,
just as the old `hit_count` counter was incremented unconditionally for all LLC hits.

**Symptom:** DoA eviction rate always 100% for LLC regardless of workload, and policy
results diverging from the old reference binary by several percent on some traces.

**Fix:** `if (NAME == "cpu0_STLB" || NAME == "LLC") way->accessed = true;` — remove
the `way->dp` condition entirely.

**How to catch earlier:** When reimplementing, trace every field used in classification
back to where it is set and verify the conditions fire under the actual run config.
Here: follow `accessed` from eviction classification → `try_hit` → see `way->dp` gate
→ check when `dp` is ever true → realise `cbpred=0` means never.

---

## 9. Write-hit promotion guard inflated "liveness" speedup (the *_live modules ≠ plain modules)

**What happened:** `srrip_live.cc`, `ipv_live.cc`, and `lru_live.cc` all began
`update_replacement_state` with `if (hit && type == WRITE) return;`. The plain baseline
modules (`srrip.cc`, stock LRU) have no such guard — they promote every hit (including
writeback hits) to RRPV 0 / MRU. So the `*_live` modules silently treated write hits
differently: writeback hits did not promote.

**Why it mattered:** The guard sits *before* the liveness logic, so it is active even
when the history table is empty and every block defaults to mostly-alive. We compared
`*_live` (with guard) against plain SRRIP/LRU (without guard), so the write-hit-handling
difference was miscredited to liveness. On srv_128, SRRIP-Live with a zero-entry table
(provably zero DoA classifications) beat plain SRRIP by **+1.2%** purely from not
promoting writebacks.

**Magnitude:** Across the LLC threshold sweep, ~0.8–1.2 pp of the reported "vs SRRIP"
speedup was this artifact — and it was *threshold-dependent* (largest at aggressive low
thresholds: thd=1's entire +1.18% apparent benefit was artifact, honestly ~0%). The
optimal threshold (thd=4) was unchanged, but magnitudes were inflated by ~36% at the
peak and up to ~100% at low thresholds.

**Fix:** Removed the guard from all three `*_live` modules so the no-liveness default
path is byte-for-byte the baseline policy. Verified: SRRIP-Live cap=0 == plain SRRIP
exactly (both 2.04288 on srv_128). The honest liveness contribution at thd=4 is
**+1.40% vs SRRIP** (unbounded), down from the inflated +2.18%.

**Deeper lesson — "a hit is not a hit":** Writeback hits are weak reuse evidence (a
dirty line landing from L2, not a read). This surfaced a real, separable optimization
("don't promote on writeback hits") AND a predictor-labeling bug: `accessed` was set on
*every* hit (`cache.cc`), so write-back-only blocks were mislabeled mostly-alive,
polluting the DoA training signal. Now gated behind `ACCESSED_ON_WRITE` (default 1 for
reproducibility; 0 = demand/prefetch hits only). Mazumdar 2021 does **not** distinguish
hit types — their Accessed bit is set on any hit and they use prediction for bypass, not
promotion — so this access-type refinement is novel relative to that work.

**How to catch earlier:** Run the zero-size sanity check — with the technique's storage
set to truly zero, the *_live policy MUST equal its plain baseline exactly. It didn't,
which is what exposed the guard. (See RESEARCH_METHODOLOGY.md.)
