# Paper — Next Steps

## Finalise threshold studies
The Mazumdar-config QMM threshold sweep (LLC and STLB separately) is currently
running. Once complete, the optimal thresholds will be used for a combined
LLC+STLB run.

## Bypass predictor
The same per-PC liveness signal can be used to bypass insertion entirely for
confirmed DoA blocks. Evaluate the bypass predictor with its own dedicated
table first, then share the table with the replacement policy to understand
whether the two mechanisms compose additively.

## PC forwarding
ChampSim provides the PC at every cache level for free. Real hardware requires
a forwarding mechanism to get the PC to the LLC and STLB. The most natural
candidate is a small PC-forwarding queue analogous to the prefetch queue.
This needs to be designed and validated before a hardware cost estimate is
meaningful.

## Storage overhead
Quantify the per-way RRPV and liveness-class bit costs for the LLC and STLB,
and the size of the per-PC counter table at a practical hardware budget.

## ML and Ligra regression
Both suites regress under LLC liveness guidance. The cause is not yet clear —
possibilities include working-set fit, streaming access patterns that the DoA
counter mislabels, or counter aliasing. Per-workload characterisation is needed.
