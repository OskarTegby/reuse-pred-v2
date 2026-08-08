# Architecture Configuration

Research and configuration decisions for anchoring the paper's simulated
configuration (Table III) to a real, modern CPU core, per the professor's
guidance: "Choose a setting that is valid. Choose an example core... Use a
modern one to avoid reviewers' criticism."

`architectures.csv` (same directory) is a broad historical database of real
microarchitectures covering pipeline widths and L0/L1/L2/L3 cache
sizes/latencies -- but it has **no TLB/STLB column at all**. Since this
paper's contribution is specifically about LLC *and* STLB liveness/bypass,
the STLB numbers below were researched separately and are not in that CSV.

## Selection criteria

1. Real, currently-shipping product (not a roadmap/unreleased part).
2. Complete L1/L2/L3 cache size *and* latency data (many recent CSV rows,
   especially ARM Cortex-X-series 2022+, have `?` gaps in L2/L3 latency).
3. Modern (2022+) to pre-empt reviewer criticism of an outdated baseline.
4. One example each from Intel and AMD (per the professor's own suggestion),
   plus ARM for a third vendor if useful.

This ruled out: Cougar Cove (unreleased at the time -- since shipped, see
below), Lion Cove (2024, initially thought to have a CSV data-entry error
in its L1D figure -- also since resolved, see below), and every ARM
Cortex-X row from X1 through X925 except where noted below (most have `?`
in L2/L3 latency in the CSV).

## Recommended configuration(s)

Two additional considerations beyond the criteria above: how closely a
candidate matches the paper's *current* (generic academic) config -- for
continuity with everything already simulated -- versus how differently a
candidate behaves, to see whether the paper's conclusions hold under a
meaningfully different cache balance.

**Current config (Table III):** L1I 32KB/8-way/4cyc, L1D 32KB/8-way/5cyc,
L2 256KB/8-way/11cyc, LLC 2MB/16-way/40cyc, STLB 1,024/8-way/8cyc.

| | L1I | L1D | L2 | L3/LLC | STLB |
|---|---|---|---|---|---|
| **Current (generic)** | 32KB | 32KB | 256KB | 2,048KB | 1,024 |
| **AMD Zen 4** | 32KB | 32KB | 1,000KB | 4,000KB | 3,072 (DTLB) |
| **Intel Redwood Cove** | 64KB | 48KB | 2,048KB | 3,000KB | 2,048 |

- **Zen 4 is the closest match**: L1I and L1D are *exact* matches to the
  current config, and L2/L3 scale up moderately rather than radically --
  good for a real-core validation that stays close to what every other
  figure in the paper was already run against.
- **Redwood Cove is the strongest contrast**: 2-8x larger L1 and L2 than
  either the current config or Zen 4, a fundamentally different cache
  balance (much more mid-level buffering ahead of the LLC), good for
  testing whether the paper's liveness-guidance conclusions are an
  artifact of a particular cache balance or hold more generally.
- **ARM Cortex-X925 is deprioritized** for actual simulation: its L3 is an
  SoC-integrator decision (no single correct value the way Intel/AMD have
  a fixed per-core L3), which undercuts the "valid, sourced" framing the
  professor asked for. Kept below for reference in case that changes.

Recommendation: rerun the existing (mostly-dead/mostly-alive/DoA) results
under **Zen 4** and **Redwood Cove**.

## Candidates

### Intel: Golden Cove / Redwood Cove lineage

`architectures.csv` row for **Redwood Cove (2023)**: L1I 64KB, L1D 48KB,
L2 2,048KB, L3 3,000KB/core; latencies L1D=5, L2=16, L3=~75 cycles.

Redwood Cove is the successor of Golden Cove (Intel's own manual, Section
2.1.1: "The Redwood Cove microarchitecture is the successor of the Golden
Cove microarchitecture"), and its changelog vs. Golden Cove lists no TLB
changes (only instruction cache 32K->64K, MLC size, branch prediction,
prefetchers) -- so it inherits Golden Cove's TLB structure unchanged.

Golden Cove's TLB, in turn, is documented as a set of deltas over its own
predecessor, Ice Lake Client (Section 2.4.1.1): the ITLB and load-DTLB grew;
everything else (including the L2/STLB) is not listed as changed, so it
carries over from Ice Lake's own table (Table 2-10) unchanged.

**TLB parameters (official, Intel Optimization Reference Manual, Table 2-10
+ Section 2.4.1.1 deltas):**

| Level | Page size | Entries | Associativity |
|---|---|---|---|
| L1 ITLB | 4K | 256 (128 in Ice Lake, doubled in Golden Cove) | 8-way |
| L1 ITLB | 2M/4M | 32 (16 in Ice Lake, doubled in Golden Cove) | 8-way |
| L1 DTLB (loads) | 4K | 96 (64 in Ice Lake, +50% in Golden Cove) | 4-way |
| L1 DTLB (loads) | 2M/4M | 32 (unchanged from Ice Lake) | 4-way |
| L1 DTLB (loads) | 1G | 8 (unchanged from Ice Lake) | 8-way |
| L1 DTLB (stores) | all | 16 (unchanged from Ice Lake) | 16-way |
| **L2 / STLB** | all (shared) | **2,048** (unchanged from Ice Lake) | 16-way |

STLB latency is **not published** in the official manual (Intel doesn't list
cycle counts for TLB hits/misses). Third-party microbenchmarking
(Chips and Cheese) puts the L2 TLB latency at **~7 cycles** for the
Redwood Cove / Lion Cove lineage.

### Intel: Cougar Cove (Panther Lake, 2026)

Reconsidered after initially being ruled out as "unreleased" -- it has since
shipped (Panther Lake, broad availability since Q1 2026) and is the direct
successor of Redwood Cove in the same P-core lineage (Golden Cove -> Redwood
Cove -> Lion Cove -> Cougar Cove).

`architectures.csv` row: L0D 48KB, L1I 64KB, L1 ("L1.5") 192KB, L2 3,072KB,
L3 3,000KB/core; latencies L0D=4, L1=9, L2=22, L3=~68 cycles.

**Cache hierarchy note:** starting with Lion Cove, Intel added a genuine
extra cache level -- the CSV's "L1D=192KB" figure looked like a data-entry
error on first read (a jump from every prior generation's 32-64KB), but
Chips and Cheese confirms it is real: a new 48KB L0 (the fastest,
closest-to-core cache) sits ahead of a 192KB level Intel calls "L1" (some
reviewers call it "L1.5" since they disagree with the naming), which is
ahead of a 3MB "L2". That is four cache levels before/including L3, but
ChampSim's config model only has three slots (L1D/L2C/LLC). The mapping
used here: **ChampSim L1D = the 48KB L0** (same size as Redwood Cove's L1D,
maximum continuity), **ChampSim L2C = the actual 3,072KB "L2"** (the level
Intel itself still calls L2, playing the same structural role as Redwood
Cove's L2C), **ChampSim LLC = 3,000KB, unchanged from Redwood Cove**. The
192KB intermediate level is omitted from the model -- the same kind of
simplification ChampSim already makes for micro-op caches and other
structures it doesn't represent.

**TLB parameters:** Chips and Cheese states Lion Cove's *only* TLB change
vs. Redwood Cove is the load DTLB growing from 96 to 128 entries -- "none
of the other TLB sizes have changed." So Redwood Cove's ITLB (256 entries,
8-way) and STLB (2,048 entries, 16-way) carry forward into Lion Cove
unchanged. Cougar Cove is described as a refinement of Lion Cove ("no part
of the core undergoing a fundamental redesign") with "TLB capacity
increased by 50% compared to Lion Cove" -- no source gives a level-by-level
breakdown of that 50%, so it is applied here specifically to the **STLB**
(2,048 -> 3,072 entries, same 16-way associativity), since that is both the
parameter this paper's contribution is actually about and the one these
generational writeups most commonly headline as "the TLB." The L1 DTLB is
assumed to hold at Lion Cove's 128 entries (no source claims further growth
in Cougar Cove specifically), and the ITLB is assumed unchanged, matching
the "no change noted -> carries over" convention used throughout this file.
STLB latency reuses the same ~7-cycle third-party estimate as the rest of
the lineage.

| Level | Entries | Associativity | Confidence |
|---|---|---|---|
| L1 ITLB | 256 | 8-way | assumed unchanged from Redwood Cove |
| L1 DTLB (loads, 4K) | 128 | 4-way | Chips and Cheese (Lion Cove), assumed to hold |
| **L2 / STLB** | **3,072** | 16-way | **estimated**: 2,048 x 1.5, per Cougar Cove's "+50% TLB capacity" claim applied to STLB |

This is the least-confirmed config in this file -- both the STLB entry
count and the L1 DTLB carry-forward assumption are inferred rather than
directly sourced. Flagging here so results using this config are read with
that caveat.

### AMD: Zen 4

`architectures.csv` row: L1I 32KB, L1D 32KB, L2 1,000KB, L3 4,000KB/core;
latencies L1D=4, L2=14, L3=~50 cycles.

**TLB parameters (official, AMD Software Optimization Guide for the Zen4
Microarchitecture, doc #57647, Section 2.7):**

| Level | Entries | Associativity | Page sizes |
|---|---|---|---|
| L1 ITLB | 64 | Fully associative | 4K, 2M, 1G |
| L1 DTLB | 72 | Fully associative | 4K, 16K, 2M, 1G |
| L2 ITLB | 512 | 8-way | 4K, 2M |
| **L2 DTLB** | **3,072** | 24-way | 4K, 16K, 2M (unified; also holds PDEs for table-walk acceleration) |

Note: AMD's L2 TLB is **split** into separate I/D structures, unlike
Intel's and ARM's unified STLB. ChampSim's STLB is a single unified
structure, so modeling AMD requires picking one number to stand in --
see "Open questions" below.

### AMD: Zen 5

`architectures.csv` row: L1I 32KB, L1D 48KB, L2 1,000KB, L3 4,000KB/core;
latencies L1D=4, L2=14, L3=~50 cycles.

**L1 TLB (official; a search-engine snippet quotes AMD's Software
Optimization Guide for Zen5, doc #58455, in the exact same template wording
as the verified Zen4 doc -- high confidence, but I could not independently
fetch the raw Zen5 PDF myself to re-verify word-for-word, since docs.amd.com
serves it through a gated portal viewer, not a direct file link):**

| Level | Entries | Associativity |
|---|---|---|
| L1 ITLB | 64 | Fully associative |
| L1 DTLB | 96 | Fully associative |

**L2 TLB (third-party only, Chips and Cheese -- not independently verified
against the official SOG):** L2 DTLB 4,096 entries, L2 ITLB 2,048 entries,
7-cycle latency (same as Zen 4).

### ARM: Cortex-X925

`architectures.csv` row has gaps: L1I/L1D 64KB, L2 3,000KB, L3 4,000KB;
L1D latency=4, **L2 and L3 latency are `?` in the CSV**. Filled in from
Chips and Cheese: L2 latency = 12 cycles. L3 is a system-level cache (SLC)
shared via the DSU-120 cluster interconnect -- its size/latency is SoC-vendor
-defined (Qualcomm/MediaTek/Samsung each implement their own), so there is
no single universal number the way Intel/AMD have a fixed per-core L3.

**TLB parameters:**

| Level | Entries | Associativity | Source |
|---|---|---|---|
| L1 DTLB | 96 | Fully associative | Search-snippet-attributed to the official Cortex-X925 TRM |
| L1 ITLB | fully associative, confirmed page-size support (4K/16K/64K/2M) | Fully associative | **Entry count not found anywhere** -- ARM's TRM is a JS-rendered SPA that the fetch tool cannot extract tables from |
| **L2 TLB** | **2,048** | 8-way | Chips and Cheese (third-party only); unified I+D, unlike AMD's split design |

L2 TLB latency: 6 cycles (Chips and Cheese).

## Open questions / gaps

1. **AMD's split L2 TLB vs. ChampSim's unified STLB.** Need a decision: use
   just the L2 DTLB entry count (3,072 for Zen4 / 4,096 for Zen5), matching
   that this paper's STLB work is specifically about *data*-page
   liveness/bypass (the same framing as the Mazumdar `dppred` comparison
   already in the paper) -- or some combined figure.
2. **Zen 5 L2 TLB size is third-party-only.** Could not independently fetch
   the official SOG (doc #58455) past AMD's portal viewer to re-verify the
   4,096/2,048 figures myself.
3. **ARM Cortex-X925 L1 ITLB entry count** is not documented in any source
   found so far.
4. **ARM Cortex-X925 L3 latency** has no single "correct" value -- it's an
   SoC-integrator decision, not part of the core IP itself.
5. **No official STLB *latency* numbers exist for any of these** (only
   Intel/AMD/ARM structural sizes are published; all latency figures above
   are third-party microbenchmarks from Chips and Cheese).
6. **Cougar Cove's STLB entry count is a derived estimate, not a sourced
   figure.** "TLB capacity +50% vs. Lion Cove" is the only number any
   source gives; no writeup breaks it down by TLB level. Applied here to
   the STLB on the reasoning that it's the parameter this paper actually
   needs, but this is the weakest-sourced number in this file.
7. **Cougar Cove's L1 DTLB is assumed to hold at Lion Cove's 128 entries**
   -- no source confirms whether it grew further in Cougar Cove.

## References

- [Intel® 64 and IA-32 Architectures Optimization Reference Manual](https://cdrdv2-public.intel.com/821613/355308-Optimization-Reference-Manual-050-Changes-Doc.pdf) -- official; Table 2-10 (Ice Lake TLB parameters) and Section 2.4.1.1 (Golden Cove cache/TLB deltas), Section 2.1.1 (Redwood Cove changelog, no TLB changes listed)
- [Software Optimization Guide for the AMD Zen4 Microarchitecture, doc #57647](https://www.numberworld.org/blogs/2024_8_7_zen5_avx512_teardown/57647_zen4_sog.pdf) -- official; Section 2.7 (Memory Address Translation)
- [Software Optimization Guide for the AMD Zen5 Microarchitecture, doc #58455 (AMD Technical Information Portal)](https://docs.amd.com/v/u/en-US/58455_1.00) -- official, portal-gated (could not fetch raw text directly)
- [Arm Cortex-X925 Core Technical Reference Manual](https://developer.arm.com/documentation/102807/0002/Technical-overview/Core-components) -- official, JS-rendered (could not fetch table content directly; L1 DTLB=96 figure is search-snippet-attributed to this document)
- [Arm's Cortex X925: Reaching Desktop Performance (Chips and Cheese)](https://chipsandcheese.com/p/arms-cortex-x925-reaching-desktop) -- third-party microbenchmarks; L2 cache latency, L2 TLB size/latency
- [Intel's Redwood Cove: Baby Steps are Still Steps (Chips and Cheese)](https://chipsandcheese.com/p/intels-redwood-cove-baby-steps-are-still-steps)
- [Lion Cove: Intel's P-Core Roars (Chips and Cheese)](https://chipsandcheese.com/p/lion-cove-intels-p-core-roars) -- source for the ~7-cycle L2 TLB latency figure ("matches Zen 5")
- [AMD's Ryzen 9950X: Zen 5 on Desktop (Chips and Cheese)](https://chipsandcheese.com/p/amds-ryzen-9950x-zen-5-on-desktop) -- source for Zen 5 L2 TLB entry counts (third-party)
- [AMD's Strix Point: Zen 5 Hits Mobile (Chips and Cheese)](https://chipsandcheese.com/p/amds-strix-point-zen-5-hits-mobile)
- [Intel's Lion Cove Architecture Preview (Chips and Cheese)](https://chipsandcheese.com/p/intels-lion-cove-architecture-preview) -- source for the 48KB L0 / 192KB "L1" cache hierarchy and the "only the load DTLB changed, 96->128 entries" TLB statement
- [Panther Lake's Reveal at ITT 2025 (Chips and Cheese)](https://chipsandcheese.com/p/panther-lakes-reveal-at-itt-2025) -- source for Cougar Cove's "+50% TLB capacity vs. Lion Cove" claim (no per-level breakdown given)
- [Inside Panther Lake: How Intel's Cougar Cove & Darkmont Architectures Deliver 50% More Performance](https://www.intelstartyourengines.com/inside-panther-lake-how-intels-cougar-cove-darkmont-architectures-deliver-50-more-performance) -- Cougar Cove release/availability timeline
- [Intel Panther Lake Deep-Dive (wccftech)](https://wccftech.com/intel-panther-lake-deep-dive-18a-compute-tile-cougar-cove-p-cores-darkmont-e-cores/) -- corroborates Cougar Cove as an incremental refinement of Lion Cove, not a redesign
