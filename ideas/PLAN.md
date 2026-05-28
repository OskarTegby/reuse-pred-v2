# Research plan — cbPred history table improvements

## Step 1 — Replacement policy and promotion buffer (idea 001)

Evaluate LRU, LFU, and SRRIP as replacement policies for the bounded bHIST
and pHIST tables currently running on QMM. If the replacement policy alone
shows improvement, add the two-stage promotion buffer: new entries stage in a
small buffer and only graduate to the main table once they have been observed
dead at least K times. This filters the one-time dead blocks that dominate the
address-indexed bHIST and dilute the confidence counters.

Proceed to step 2 regardless of outcome — the two directions are orthogonal.

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
