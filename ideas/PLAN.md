# Research plan — cbPred history table improvements

## Step 1 — Replacement policy and promotion buffer (idea 001)

**Status: in progress (experiment 005 submitted)**

Replacement policy sweep (exp003, confounded) → LFU selected.
Exp004 confirmed: LFU full predictor (0,0)=+7.27%, (6,6)=+6.12% on QMM geomean.
pHIST: 1024 entries is not overprovisioned (sharp cliff at 512).
bHIST: graceful degradation; floor near +4% at 128 entries.

Exp005 now running:
- DoA-LFU vs standard LFU for flat bHIST (freq increments only on dead evictions).
- Promotion buffer for flat bHIST (new entries stage; promote when dead_count >
  LFU victim freq).
- PC-partitioned bHIST (PCPartitionedTable, 256 PC × 16 addr, DoA-LFU at both
  levels, optional per-PC addr buffer).
- Size sweeps for flat DoA-LFU (with/without buffer) and PC-partitioned
  (vary addr_ways).

Proceed to step 2 regardless of outcome.

## Step 2 — Pass dpPred PC through the PFQ (idea 002)

Extend the PFQ entries from bare PFNs to (PFN, PC) pairs, where PC is the
dpPred PC recorded at STLB bypass time. cbPred extracts this PC on a PFQ hit
and uses it as the bHIST key instead of the block address. Store the dpPred PC
in the BLOCK at fill time so update_eviction_counters can train bHIST with the
correct PC at eviction time even after the PFQ entry has aged out.

Evaluate on QMM. The hypothesis is that collapsing all fills from pages flagged
by the same dpPred PC into one bHIST entry reduces key-space noise and lets the
confidence counter accumulate faster, particularly at the default (6,6)
threshold where the current address-indexed bHIST rarely reaches saturation.

## Step 3 — PC-partitioned bHIST with per-PC address sets

Extend the PC-indexed bHIST from step 2 into a two-level structure:

  PC → { block address → counter }

The top level is indexed by dpPred PC (small key space, fast accumulation).
Within each PC entry, a set of block addresses belonging to that PC is tracked,
recording which specific lines loaded by this PC have been dead.

Two sub-variants to evaluate:

- **One counter per PC**: bypass whenever the PC's aggregate confidence exceeds
  the threshold, regardless of which specific block address is being filled.
  Simpler; loses address-level specificity but is robust to noise.

- **Per-address counter within each PC**: bypass only when both the PC's entry
  exists and the specific block address within that entry has its own counter
  above threshold. More precise; requires knowing which block addresses have
  been observed under each PC and managing capacity at both levels.

The key question at this step is how to bound the inner address sets: a fixed
number of ways per PC entry (set-associative within each PC partition) with
SRRIP replacement is the natural choice given the work in step 1.

## Dependencies

Step 2 must precede step 3 (step 3 extends the PC-in-PFQ infrastructure).
Step 1 is independent and informs the replacement policy choice for step 3.
