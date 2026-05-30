---
name: feedback-plot-lru-mid
description: Never show lru_mid bars in any plot — user explicitly banned it
metadata:
  type: feedback
---

Never render `lru_mid` bars in any plot, including `plot_optimal_thd_per_benchmark.py` and any other analysis script. Remove it from legends, bar groups, and geomean columns.

**Why:** User explicitly requested removal and expressed strong frustration at seeing it repeatedly ("I'm almost tempted to tell you to delete those results").

**How to apply:** When generating or regenerating any plot that iterates over policies, skip `lru_mid` entirely — do not load it, do not plot it, do not include it in the legend.
