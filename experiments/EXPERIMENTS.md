# Bypass Predictor Reevaluation — Experiment Log

Branch: `bypass-predictor-reevaluation`

Each experiment has its own subdirectory containing:
- `README.md` — commit, date, description, config summary, results, observations
- `config_*.json` — exact ChampSim config files used
- `srv_128/` — full champsim output for the canonical verification trace (srv_128)
  across all configurations tested

Results from full sweeps (45 QMM traces) are not committed. The sweep script
and binary name in each README are sufficient to reproduce them.

---

## Timeline

| # | Date | Commit | Description | 1MB (6,6) | 1MB (0,0) | 2MB (6,6) | 2MB (0,0) |
|---|------|--------|-------------|-----------|-----------|-----------|-----------|
| [001](001_clean_baseline/README.md) | 2026-05-28 | f4d7a30024ba | Clean baseline: remove all Sniper approximations | +0.95% | +7.56% | −0.17% | −1.58% |
| [002](002_pfq_gating/README.md) | 2026-05-28 | — | PFQ gate variants: NO_PFQ=−1.49%, EMA≈+6.09% (srv_128) | N/A | N/A | N/A | N/A |
