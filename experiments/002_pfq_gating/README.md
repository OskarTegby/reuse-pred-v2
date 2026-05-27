# 002 — PFQ gate variants: static-off and EMA-adaptive

**Date**: 2026-05-28
**Branch**: bypass-predictor-reevaluation
**Commit**: 8b00276690fb

---

## Motivation

Experiment 001 established that with the PFQ gate ON and (0,0) thresholds,
cbPred achieves +7.56% geomean on QMM. The gate requires a PFQ hit (dpPred
corroboration) before cbPred bypasses. This experiment asks: what happens if
we relax or adaptively control that gate?

Two variants tested, both at (0,0) thresholds, 1MB LLC, LRU:

1. **CBPRED_NO_PFQ** — gate permanently OFF; cbPred fires on bhist confidence
   alone, no PFQ hit required.
2. **PFQ_EMA** — gate starts ON; an exponential moving average of the PFQ hit
   rate per LLC fill is tracked. When EMA drops below the threshold (default
   10%), the gate turns OFF. When it recovers, the gate turns back ON.

EMA parameters (all tunable at runtime):
- `PFQ_EMA_ALPHA`: decay factor, default 1/1024 ≈ 0.001
- `PFQ_EMA_THD`: gate-off threshold in percent, default 10

---

## Implementation

New fields in `CACHE` (private, `inc/cache.h`):
```cpp
bool   pfq_gate     = true;           // false → bypass on bhist alone
bool   pfq_ema_mode = false;          // true → dynamically flip pfq_gate
double pfq_ema_val  = 1.0;            // EMA starts at 100% hit rate → gate ON
double pfq_ema_alpha = 1.0 / 1024.0;
double pfq_ema_thd   = 0.10;
```

New stat in `cache_stats` (`inc/cache.h`):
```cpp
uint64_t cbpred_nogate_bypasses = 0;  // bypasses that fired without a PFQ hit
```

Updated `cbpred_bypass` (`src/cache.cc`):
```cpp
if (pfq_ema_mode) {
  pfq_ema_val = pfq_ema_alpha * (in_pfq ? 1.0 : 0.0)
              + (1.0 - pfq_ema_alpha) * pfq_ema_val;
  pfq_gate = (pfq_ema_val >= pfq_ema_thd);
}
if (pfq_gate && !in_pfq) return false;
if (bhist[block_hash] <= bconf_thd) return false;
sim_stats.back().llc_bypasses++;
if (!in_pfq) sim_stats.back().cbpred_nogate_bypasses++;
return true;
```

New env vars:
- `CBPRED_NO_PFQ=1` — permanently disable gate
- `PFQ_EMA=1` — enable adaptive gate
- `PFQ_EMA_ALPHA=<f>` — override alpha
- `PFQ_EMA_THD=<pct>` — override gate-off threshold (percent, 0–100)

Output now prints `NOGATE_BYPASSES` alongside `LLC_BYPASSES` when nonzero.

---

## Verification trace: srv_128 (1MB LLC)

Full output in `srv_128/`. For reference, experiment 001 numbers:
- baseline:       IPC = 1.2464
- optimal_bypass: IPC = 1.3221  LLC_BYPASSES=153,803  NOGATE_BYPASSES=0

| Config              | IPC     | vs baseline | LLC_BYPASSES | NOGATE_BYPASSES | % nogate |
|---------------------|---------|-------------|--------------|-----------------|----------|
| cbpred_nopfq_opt    | 1.2278  | −1.49%      | 830,024      | 667,456         | 80.4%    |
| cbpred_ema_opt      | 1.32239 | +6.09%      | 157,960      | 2,457           | 1.6%     |
| optimal_bypass (001)| 1.3221  | +6.07%      | 153,803      | —               | —        |

---

## Observations

**CBPRED_NO_PFQ regresses (−1.49% vs baseline)**. Without the PFQ gate, bhist
alone identifies ~830K blocks as "dead", of which 80% (667K) are bypassed even
though dpPred never flagged their page. This is over-aggressive: cbPred evicts
live blocks whose pages are not dead, causing more LLC misses than it prevents.
The PFQ gate is not merely an optimisation — it provides the cross-level
validity check that makes the bypass decision correct.

**PFQ_EMA matches optimal_bypass (+6.09% vs +6.07%)**. On srv_128 the EMA
gate rarely opens: only 2,457 of 157,960 bypasses (1.6%) fired without a PFQ
hit. This is expected: srv_128 has a high PFQ hit rate (dpPred reliably
identifies dead pages), so the EMA stays well above the 10% threshold for
almost the entire simulation. The adaptive logic does not hurt performance and
provides a safety valve for workloads where dpPred is unreliable.

**Takeaway**: the PFQ gate is load-bearing. Removing it unconditionally
degrades performance. The EMA-adaptive variant achieves identical IPC to the
static gate on this trace, while being capable of graceful degradation on
traces where dpPred rarely fires.

---

## Next steps

- Full QMM sweep (45 traces) via `sweep_pfq_gating.sh qmm` to confirm
  EMA ≈ optimal_bypass at geomean level and NO_PFQ regresses broadly.
- Consider additional EMA parameter tuning (lower alpha, higher threshold) if
  the sweep reveals workloads where EMA opens the gate too aggressively.
