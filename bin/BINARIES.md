# Binary inventory

All binaries are statically linked and built with `build_all.sh` (or the
one-off commands noted below) from the project root.  The base hardware
configuration is specified in `champsim_config.json`; per-policy overrides
live in `configs/<name>.json`.

Two hardware configurations have been used across experiments:

**Current config** (`champsim_config.json`, aligned with Mazumdar 2021 Table I
on 2026-03-30):
- L1D  32 KB  (64 sets × 8 ways, 5 cy)
- L2C  256 KB (512 sets × 8 ways, 11 cy)
- STLB 1024 entries (128 sets × 8 ways)
- LLC  2 MB  (2048 sets × 16 ways, 40 cy)

**Old config** (`champsim_config_old.json`, used for the March 22 QMM
threshold sweep before Mazumdar alignment):
- L1D  48 KB  (64 sets × 12 ways, 5 cy)
- L2C  512 KB (1024 sets × 8 ways, 10 cy)
- STLB 1536 entries (128 sets × 12 ways)
- LLC  2 MB  (2048 sets × 16 ways, 20 cy)

The LLC is the same size in both; the main differences are a 2× larger L2C
and half the LLC access latency in the old config.  Due to inclusive-cache
shadowing this gives the old config a much higher effective LLC capacity for
unique data and consequently higher LLC miss rates, which makes the bypass
predictor far more impactful.

---

## Standard binaries (current config, `champsim_config.json`)

Built with `./build_all.sh` at commit **fb1494ec** (2026-04-09) unless noted.

### No-prefetch variants

| Binary | LLC replacement | STLB replacement | Config file |
|--------|----------------|-----------------|-------------|
| `champsim_lru`     | LRU     | LRU | `configs/lru.json` |
| `champsim_lru_mid` | lru_mid | LRU | `configs/lru_mid.json` |
| `champsim_srrip`   | SRRIP   | LRU | `configs/srrip.json` |
| `champsim_drrip`   | DRRIP   | LRU | `configs/drrip.json` |

`champsim_lru` was **rebuilt on 2026-04-28 at commit 6d31e6e7** to include
PFQ probe/hit statistics (`pfq_probes`, `pfq_hits` fields in `CACHE_STATISTICS`
and the corresponding output lines in `plain_printer.cc`).  Earlier results
that do not need PFQ stats are unaffected; any run that needs them must use
this or a later build.

`champsim_lru_mid` is the primary experimental binary.  It applies the
liveness-guided mid-insertion policy to the LLC; the STLB uses plain LRU.
The mid-insertion threshold (N), key type (addr/pc), and promotion-on-hit
flag are all runtime parameters (`MID_THD`, `MID_KEY`, `MID_PROMOTE`).

### Scope-variant binaries

| Binary | LLC | STLB | Built at commit | Purpose |
|--------|-----|------|----------------|---------|
| `champsim_stlb_lru_mid` | LRU | lru_mid | 6d31e6e7 (2026-04-22) | STLB-only mid-insertion scope study |
| `champsim_lru_mid_both` | lru_mid | lru_mid | 6d31e6e7 (2026-04-26) | LLC+STLB mid-insertion scope study |

These were built individually with `./build_all.sh --nopref stlb_lru_mid` and
`./build_all.sh --nopref lru_mid_both` to cover the three-way scope comparison
(STLB-only / LLC-only / both) in the threshold sweep.

### ip_stride + spp_dev prefetch variants

Built with `./build_all.sh --pref` at commit **fb1494ec** (2026-04-09).
L1I = next_line_instr, L1D = ip_stride, L2C = spp_dev.

| Binary | LLC replacement |
|--------|----------------|
| `champsim_lru_pref`     | LRU     |
| `champsim_lru_mid_pref` | lru_mid |
| `champsim_srrip_pref`   | SRRIP   |
| `champsim_drrip_pref`   | DRRIP   |

Used for the policy comparison with prefetchers enabled.

### Paper-prefetch variants (PACIPV ISCA'25 configuration)

Built with `./build_all.sh --paper-pref` at commit **ece4f078** (2026-04-06).
L1I = epi_instr, L1D = berti, L2C = next_line.

| Binary | LLC replacement |
|--------|----------------|
| `champsim_lru_paper_pref`     | LRU     |
| `champsim_lru_mid_paper_pref` | lru_mid |
| `champsim_srrip_paper_pref`   | SRRIP   |
| `champsim_drrip_paper_pref`   | DRRIP   |

Matches the prefetcher configuration from the Mazumdar 2021 paper for
apples-to-apples comparison.  Built one commit earlier than the main no-pref
binaries because the paper-pref option was added before the STLB-locking fix.

---

## Special-purpose binaries

### `champsim_lru_oldcfg`

- **Config**: `champsim_config_old.json` + `configs/lru_oldcfg.json`
- **Built**: 2026-05-13, commit **706a40b5** (rebuilt from current code)
- **Build command**:
  ```
  python3 config.sh champsim_config_old.json configs/lru_oldcfg.json
  make static -j$(nproc)
  ```
- **Purpose**: Re-run the dpPred/cbPred bypass-predictor comparison under the
  pre-Mazumdar cache hierarchy (512 KB L2, 20 cy LLC) for all three suites.
  Needed to reproduce results with provenance and to compare against the current
  config (Section 3.2 of the report).
- **Current runs** (submitted 2026-05-13, jids 1401192–1401197):
  - `results/dpc3_oldcfg_20260513_2227/` — DPC3, 95 traces (baseline + pred_6_6)
  - `results/google_oldcfg_20260513_2227/` — Google, 43 traces (baseline + pred_6_6)
  - `results/qmm_oldcfg_20260513_2227/` — Qualcomm, 45 traces (baseline + pred_6_6)

### `champsim_test_berti` / `champsim_test_epi`

- **Built**: 2026-04-06, commit **61e3dfe9**
- **Purpose**: One-off sanity-check binaries used to verify that the Berti and
  EPI prefetcher integrations compiled and produced plausible output before
  including them in the paper-pref build.  Not used in any submitted sweep.
