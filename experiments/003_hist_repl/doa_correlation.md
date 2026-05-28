# DoA correlation across benchmark suites

Measured with baseline (DPPRED=0, CBPRED=0), 1MB LLC, 50M warmup + 100M sim.
Result set: `corr_baseline_20260528`.

| Suite | Traces | LLC DoA rate | STLB–LLC DoA correlation |
|---|---|---|---|
| QMM | 45 | 100.0% | 36.1% |
| GAP | 9 | 100.0% | 37.2% |
| GMS | 11 | 100.0% | 20.4% |
| Ligra | 17 | 100.0% | 70.9% |
| ML | 31 | 100.0% | 95.7% |
| DPC3 | 95 | 100.0% | 58.6% |
| Google | 43 | 100.0% | 49.7% |

**LLC DoA rate is 100% across every suite.** Every evicted LLC block was dead
on arrival — these server workloads have essentially zero LLC reuse, which
explains why the bypass predictor has so much headroom.

**STLB–LLC DoA correlation varies widely.** ML is almost perfectly correlated
(95.7%): a dead STLB entry almost always implies dead LLC blocks from that
page. Ligra is strong (70.9%), DPC3 and Google moderate (~50%), QMM and GAP
weaker (~37%), and GMS weakest (20.4%). This means:

- The bypass predictor signal is strongest on ML and Ligra — dpPred's page-level
  dead prediction reliably propagates to the block level.
- On GMS the STLB signal is noisy: many STLB dead entries do not correspond to
  dead LLC blocks, so the PFQ gate may admit many false positives.
- The default threshold (6,6) may need per-suite tuning, particularly for GMS.
