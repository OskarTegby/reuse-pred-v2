# Liveness Scoring Design

Two disjoint counters per PC: `md_count` (mostly-dead evidence) and `doa_count`
(dead-on-arrival evidence). Classification:
  - doa_count >= thd_doa  → DoA
  - md_count  >= thd_md   → Mostly Dead
  - otherwise             → Mostly Alive

Current state is determined by the counters at insertion time.

---

## Approach A — Gradual (no resets, symmetric state-dependent ±)

Increment/decrement magnitude = depth of current state (1 = MA, 2 = MD, 3 = DoA).

| Current state | DoA eviction    | MD eviction      | MA eviction      |
|---------------|-----------------|------------------|------------------|
| In MA         | md+1, doa+1     | md+1, doa−1      | md−1, doa−1      |
| In MD         | md+2, doa+2     | md+2, doa−2      | md−2, doa−2      |
| In DoA        | md+3, doa+3     | md+3, doa−3      | md−3, doa−3      |

Rules:
- DoA eviction: both counters accumulate (confirms dead behaviour at all levels)
- MD eviction:  md accumulates, doa decrements (confirms MD, contradicts DoA)
- MA eviction:  both counters decrement (evidence against all dead classifications)
- Counters clamped to zero from below.

DoA gate holds: MD evictions cannot drive doa up, so MD evictions alone cannot
push a PC into DoA. Only sustained DoA evictions cross that threshold.

---

## Approach B — Reset (hard resets; selected approach)

| Current state | DoA eviction    | MD eviction       | MA eviction          |
|---------------|-----------------|-------------------|----------------------|
| In MA         | md+1, doa+1     | md+1, doa: reset  | md: reset, doa: reset|
| In MD         | md+2, doa+2     | md+2, doa: reset  | md: reset, doa: reset|
| In DoA        | md+3, doa+3     | md+3, doa: reset  | md: reset, doa: reset|

Rules:
- DoA eviction: both counters accumulate (state-dependent magnitude).
- MD eviction:  md accumulates; doa is **reset to zero** (MD eviction is evidence
  *against* DoA classification — the block had residency value).
- MA eviction:  both counters **reset to zero** (block was alive; all dead
  evidence cleared).

DoA gate holds: doa is reset on every MD eviction, so no amount of MD evictions
can push a PC into DoA. Only a run of DoA evictions (with no MD evictions
intervening) can cross thd_doa.
