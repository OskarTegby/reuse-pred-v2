# 001 — Clean baseline predictor (dpPred + cbPred, no Sniper approximations)

**Date**: 2026-05-28
**Branch**: bypass-predictor-reevaluation
**Commit**: f4d7a30024ba

---

## What was changed

Removed all three Sniper approximations that had been introduced in commit
`fb719b249e65` and left the predictor effectively broken:

1. **phist query PC** (`dppred_bypass`): `last_ip` → `fill_mshr.ip`
   — bypass decisions now use the actual load PC that caused the STLB miss,
   not a stale global set by the most recent ITLB access.

2. **phist training PC** (`update_eviction_counters`): `last_ip` → `victim.ip`
   — confidence counters are now incremented on the correct (VPN, PC) pair
   that originally caused the evicted STLB entry to be filled.

3. **PFQ push** (`dppred_bypass`): `fill_mshr.address >> 17` (VPN/32, virtual)
   → `fill_mshr.data >> LOG2_PAGE_SIZE` (exact physical PFN from page walk)
   — cbPred can now actually find LLC blocks whose page was bypassed by dpPred.

4. **PFQ lookup** (`cbpred_bypass`): `fill_mshr.address >> 17` (PFN/32)
   → `fill_mshr.address >> LOG2_PAGE_SIZE` (exact PFN)
   — consistent with the push side above.

5. **Removed** `last_ip` static field from `cache.h` and its update in `try_hit`.

This restores the implementation to the clean ChampSim version from commit
`8ada215a9683` ("Add cbPred dead-block predictor on the LLC").

---

## Configuration

Two LLC sizes evaluated. See `config_1mb.json` and `config_2mb.json` for full
ChampSim configs. Key parameters:

| Parameter     | 1MB LLC            | 2MB LLC (Mazumdar) |
|---------------|--------------------|--------------------|
| LLC sets      | 1024               | 2048               |
| LLC ways      | 16                 | 16                 |
| LLC latency   | 40 cycles          | 20 cycles          |
| L2C sets      | 512                | 1024               |
| L2C ways      | 8                  | 8                  |
| L2C latency   | 11 cycles          | 10 cycles          |
| Warmup        | 50M instructions   | 50M instructions   |
| Simulation    | 100M instructions  | 100M instructions  |

Predictor parameters (default, tunable at runtime via env vars):

| Parameter  | Value | Meaning                                  |
|------------|-------|------------------------------------------|
| PCONF_THD  | 6     | dpPred fires when phist counter > 6      |
| BCONF_THD  | 6     | cbPred fires when bhist counter > 6      |
| PFQ_CAP    | 8     | Physical Frame Queue capacity            |
| ST_SIZE    | 2     | Shadow table capacity                    |

---

## Verification trace: srv_128

Full champsim output in `srv_128/`. Summary:

### 1MB LLC

| Config          | IPC    | Speedup  | LLC-MPKI | LLT_BYPASSES | LLC_BYPASSES | PFQ_HITS |
|-----------------|--------|----------|----------|--------------|--------------|----------|
| baseline        | 1.2464 | —        | 5.35     | 0            | 0            | 0        |
| (6,6) default   | 1.2598 | +1.07%   | 5.21     | 22,651       | 8,796        | 37,592   |
| (0,0) optimal   | 1.3221 | +6.07%   | 4.53     | 128,379      | 153,803      | 7,119    |

### 2MB LLC

| Config          | IPC    | Speedup  | LLC-MPKI | LLT_BYPASSES | LLC_BYPASSES | PFQ_HITS |
|-----------------|--------|----------|----------|--------------|--------------|----------|
| baseline        | 2.5242 | —        | 0.51     | 0            | 0            | 0        |
| (6,6) default   | 2.5341 | +0.39%   | 0.50     | 20,957       | 11           | 5,436    |
| (0,0) optimal   | 2.4627 | −2.43%   | 0.53     | 131,167      | 16,712       | 5,694    |

---

## QMM geomean speedup (45 traces)

| Config          | 1MB LLC  | 2MB LLC  |
|-----------------|----------|----------|
| (6,6) default   | +0.95%   | −0.17%   |
| (0,0) optimal   | +7.56%   | −1.58%   |

Result sets: `qmm_1mb_20260527_1543`, `qmm_2mb_20260527_1543` (on cluster,
not committed — see sweep script for reproduction).

---

## Observations

- With 1MB LLC the DoA rate at the LLC is ~100%, meaning nearly every fill is
  dead on arrival. dpPred correctly identifies dead pages and cbPred bypasses
  the corresponding LLC fills, freeing slots and reducing MPKI. The optimal
  threshold (0,0) fires aggressively and gives +7.56% geomean, +6.07% on
  srv_128.

- With 2MB LLC the DoA rate is much lower (more capacity → more reuse), so
  the predictor has fewer genuinely dead blocks to bypass. The aggressive (0,0)
  threshold generates false positives that evict live blocks, causing a slight
  regression.

- The (6,6) default threshold is conservative: cbPred requires a block to have
  been seen as dead >6 times before bypassing. On the 2MB LLC this almost never
  fires (LLC_BYPASSES=11 on srv_128), so the result is essentially neutral.
