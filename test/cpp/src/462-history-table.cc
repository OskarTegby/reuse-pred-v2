// Tests that the mid-insertion history tables (stlb_mid_hist_addr and
// stlb_mid_hist_pc for the STLB, llc_mid_hist_addr and llc_mid_hist_pc for
// the LLC) accumulate the correct doa and mostly_dead counters and that
// needs_mid_insertion() reflects them.
//
// These tables are updated unconditionally at every LLC/STLB eviction,
// regardless of whether the bypass predictors (DPPRED/CBPRED) are enabled.
// DPPRED is left unset in these tests to confirm that mid-insertion history
// is independent of the predictor.
//
// The counters are private, so they are tested through their sole observable
// effect: needs_mid_insertion() returning true causes lru_mid to place the
// block at the set median rather than at MRU.  A block placed at median
// occupies a lower recency position and therefore gets evicted sooner than
// one inserted at MRU.
//
// Cache setup: 3-way cpu0_STLB, lru_mid replacement, DPPRED=0 (default).
// With 3 ways, NUM_WAY/2 = 1.  nth_element at index 1 returns the median of
// the three current last_used timestamps.
//
// Common test shape
// -----------------
//  Phase 0  Build history for address A (DoA or mostly-dead eviction).
//  Phase 1  Run many cycles so the remaining ways have old timestamps.
//  Phase 2  Fill a new block E that takes the oldest slot (evicts B).
//           E gets a very recent timestamp >> all others.
//  Phase 3  Fill A.
//           With history (doa>0 or mostly_dead>0): A mid-inserted at median.
//           Without: A inserted at MRU (ts >> everything).
//  Phase 4  Fill F and G.
//           With mid-insertion: A should be the LRU and gets evicted by G.
//           Without mid-insertion: A survives (F evicts the next oldest, G
//           the one after that; A is only evicted much later).
//  Probe    Issue a LOAD for A.
//           If A was evicted: it goes to mock_ll → packet_count increases.
//           If A is still resident: it hits → packet_count unchanged.

#include <cstdlib>

#include <catch.hpp>
#include "mocks.hpp"
#include "cache.h"
#include "champsim_constants.h"

namespace
{
// Convenience: advance every element by n cycles.
template <typename Array>
void run(Array& elems, int n = 1)
{
  for (int i = 0; i < n; ++i)
    for (auto e : elems)
      e->_operate();
}

// Issue a LOAD and wait for it to resolve (miss + fill, or hit).
template <typename Array, typename MRP>
void fill(MRP& ul, Array& elems, uint64_t addr, uint64_t ip, uint64_t& next_id)
{
  PACKET p;
  p.address   = addr;
  p.v_address = addr;
  p.ip        = ip;
  p.instr_id  = next_id++;
  p.cpu       = 0;
  p.type      = LOAD;
  ul.issue(p);
  run(elems, 100); // enough to complete miss + fill
}
} // namespace

// ── doa counter increments on DoA eviction ───────────────────────────────────
// If doa_A > 0 after Phase 0, A is mid-inserted in Phase 3.
// Two subsequent fills (F, G) should evict A; if A is gone, the probe misses.

SCENARIO("doa counter: after a DoA eviction needs_mid_insertion is true for that address") {
  ::unsetenv("DPPRED"); // mid-insertion history is populated regardless of predictor state
  ::unsetenv("MID_KEY"); // default: addr-based (MID_KEY=0)

  GIVEN("A 3-way cpu0_STLB with lru_mid and DPPRED disabled") {
    constexpr uint64_t hit_latency  = 2;
    constexpr uint64_t fill_latency = 2;
    do_nothing_MRC mock_ll;
    CACHE::NonTranslatingQueues uut_queues{1, 32, 32, 32, 0, hit_latency, LOG2_BLOCK_SIZE, false};
    CACHE uut{"cpu0_STLB", 1, 1, 3, 32, fill_latency, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), uut_queues, &mock_ll,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru_mid};
    to_rq_MRP mock_ul{&uut};

    std::array<champsim::operable*, 4> elements{{&mock_ll, &uut_queues, &uut, &mock_ul}};
    uut.initialize();
    uut.warmup = false;
    uut_queues.warmup = false;
    uut.begin_phase();
    uut_queues.begin_phase();

    WHEN("A is evicted once as DoA (establishing doa_A = 1)") {
      uint64_t id = 1;
      constexpr uint64_t ip     = 0xCAFE;
      constexpr uint64_t addr_a = 0x1000;

      // Phase 0 – build doa_A = 1.
      // Fill A, B, C to saturate the 3-way set, then fill D → A (LRU) evicted DoA.
      fill(mock_ul, elements, addr_a, ip, id);       // A: way 0, ts=T_A
      run(elements, 30);
      fill(mock_ul, elements, 0x2000, ip, id);        // B: way 1, ts=T_B > T_A
      run(elements, 30);
      fill(mock_ul, elements, 0x3000, ip, id);        // C: way 2, ts=T_C > T_B
      run(elements, 30);
      fill(mock_ul, elements, 0x4000, ip, id);        // D: evicts A (LRU) as DoA → doa_A=1

      // Phase 1 – age the cache so B, C, D all have OLD timestamps.
      run(elements, 400);

      // Phase 2 – fill E to evict B (oldest after A was evicted).
      // E gets a very recent timestamp >> C's and D's.
      fill(mock_ul, elements, 0x5000, ip, id);        // E: evicts B (LRU), ts=T_E >> T_C, T_D
      run(elements, 30);

      // Phase 3 – fill A again (doa_A=1 → needs_mid_insertion → median ts).
      // LRU at this point is C (ts=T_C < T_D < T_E).
      // A fills C's way; median of {T_D, T_E, T_C} = T_D.  A gets ts=T_D.
      // State: {D:T_D, E:T_E, A:T_D}.  LRU = tie D/A; way 0 (D) first.
      fill(mock_ul, elements, addr_a, ip, id);        // A: mid-inserted at ts≈T_D

      // Phase 4 – two more fills that should drive A out.
      // Fill F → evicts D (way 0, first min): {F:T_F, E:T_E, A:T_D}; A is now LRU.
      fill(mock_ul, elements, 0x6000, ip, id);        // F
      // Fill G → evicts A (LRU): {F, E, G:T_G}.
      fill(mock_ul, elements, 0x7000, ip, id);        // G

      // Probe: access A.  A should have been evicted → miss → packet count goes up.
      const auto count_before = mock_ll.packet_count();
      fill(mock_ul, elements, addr_a, ip, id);

      THEN("A is a miss (evicted by lru_mid mid-insertion)") {
        CHECK(mock_ll.packet_count() == count_before + 1);
      }
    }
  }

}

// ── doa counter resets after a non-DoA eviction ──────────────────────────────
// Build doa_A=1, then evict A as non-DoA (it has a hit → mostly-dead or
// mostly-alive).  After the reset, A is inserted at MRU on the next fill and
// should survive two subsequent fills.

SCENARIO("doa counter: resets after a non-DoA eviction (block was hit)") {
  ::unsetenv("DPPRED");
  ::unsetenv("MID_KEY");

  GIVEN("A 3-way cpu0_STLB with lru_mid and DPPRED disabled") {
    constexpr uint64_t hit_latency  = 2;
    constexpr uint64_t fill_latency = 2;
    do_nothing_MRC mock_ll;
    CACHE::NonTranslatingQueues uut_queues{1, 32, 32, 32, 0, hit_latency, LOG2_BLOCK_SIZE, false};
    CACHE uut{"cpu0_STLB", 1, 1, 3, 32, fill_latency, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), uut_queues, &mock_ll,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru_mid};
    to_rq_MRP mock_ul{&uut};

    std::array<champsim::operable*, 4> elements{{&mock_ll, &uut_queues, &uut, &mock_ul}};
    uut.initialize();
    uut.warmup = false;
    uut_queues.warmup = false;
    uut.begin_phase();
    uut_queues.begin_phase();

    WHEN("doa_A is built to 1, then A is evicted as mostly-alive (both doa and mostly_dead reset)") {
      uint64_t id = 1;
      constexpr uint64_t ip     = 0xCAFE;
      constexpr uint64_t addr_a = 0x1000;

      // Phase 0 – build doa_A = 1 (same as first scenario).
      fill(mock_ul, elements, addr_a, ip, id);
      run(elements, 30);
      fill(mock_ul, elements, 0x2000, ip, id);
      run(elements, 30);
      fill(mock_ul, elements, 0x3000, ip, id);
      run(elements, 30);
      fill(mock_ul, elements, 0x4000, ip, id); // evicts A as DoA → doa_A=1

      run(elements, 200);

      // Phase 0b – evict A as mostly-alive so BOTH doa and mostly_dead reset to 0.
      //
      // B is LRU (T_B < T_C < T_D).  Fill E to evict B, then mid-insert A
      // (doa_A=1 → ts = median = T_D).  Age A for a long time to build large
      // residence, then hit A once.  The hit leaves A's ts at T_D (median
      // unchanged) but records A.last_hit_cycle = now.  Fill F → evicts D
      // (way 0 tie-break with A).  Fill G → evicts A (now the unique LRU).
      // dead_tail ≈ 200 cycles; residence ≈ 700 cycles →  dead_tail < residence/2
      // → classified mostly_alive → doa_A = 0, mostly_dead_A = 0.
      fill(mock_ul, elements, 0x5000, ip, id); // E: evicts B (LRU). State: {C, D, E}.
      run(elements, 30);

      // A fills C's way (mid-inserted). State: {D:T_D, E:T_E, A:T_D}.
      fill(mock_ul, elements, addr_a, ip, id);

      run(elements, 500); // long wait — builds up A's residence

      // Hit A (last_hit_cycle = now; ts stays T_D since needs_mid_insertion still true).
      fill(mock_ul, elements, addr_a, ip, id); // hit A

      // F evicts D (way 0 — same ts T_D as A). State: {F:T_F, E:T_E, A:T_D}. A is LRU.
      fill(mock_ul, elements, 0x6000, ip, id); // F: evicts D

      // G evicts A (unique LRU). dead_tail ≈ 200 cycles; residence ≈ 700 → mostly_alive.
      // doa_A = 0, mostly_dead_A = 0.
      fill(mock_ul, elements, 0x7000, ip, id); // G: evicts A as mostly_alive → counters reset

      run(elements, 400);

      fill(mock_ul, elements, 0x9000, ip, id); // I: evicts LRU of {F, E, G}
      run(elements, 30);

      // Fill A: doa_A=0, mostly_dead_A=0 → needs_mid_insertion=false → MRU insertion.
      fill(mock_ul, elements, addr_a, ip, id); // A: MRU (ts >> everything)

      fill(mock_ul, elements, 0xA000, ip, id); // J
      fill(mock_ul, elements, 0xB000, ip, id); // K

      const auto count_before = mock_ll.packet_count();
      fill(mock_ul, elements, addr_a, ip, id); // probe A

      THEN("A is a hit (doa was reset; A is at MRU and survives two fills)") {
        CHECK(mock_ll.packet_count() == count_before);
      }
    }
  }

}

// ── mostly_dead counter increments on mostly-dead eviction ───────────────────
// After A is evicted as mostly-dead (hit early, then long dead tail),
// mostly_dead_A = 1 → needs_mid_insertion = true → A is mid-inserted on
// the next fill → A is evicted sooner than if it were at MRU.

SCENARIO("mostly_dead counter: after a mostly-dead eviction needs_mid_insertion is true") {
  ::unsetenv("DPPRED");
  ::unsetenv("MID_KEY");

  GIVEN("A 3-way cpu0_STLB with lru_mid and DPPRED disabled") {
    constexpr uint64_t hit_latency  = 2;
    constexpr uint64_t fill_latency = 2;
    do_nothing_MRC mock_ll;
    CACHE::NonTranslatingQueues uut_queues{1, 32, 32, 32, 0, hit_latency, LOG2_BLOCK_SIZE, false};
    CACHE uut{"cpu0_STLB", 1, 1, 3, 32, fill_latency, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), uut_queues, &mock_ll,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru_mid};
    to_rq_MRP mock_ul{&uut};

    std::array<champsim::operable*, 4> elements{{&mock_ll, &uut_queues, &uut, &mock_ul}};
    uut.initialize();
    uut.warmup = false;
    uut_queues.warmup = false;
    uut.begin_phase();
    uut_queues.begin_phase();

    WHEN("A is hit once early then evicted as mostly-dead (establishing mostly_dead_A = 1)") {
      uint64_t id = 1;
      constexpr uint64_t ip     = 0xCAFE;
      constexpr uint64_t addr_a = 0x1000;

      // Phase 0 – build mostly_dead_A = 1.
      // Fill A, hit A immediately (so last_hit_cycle ≈ T_A and A.accessed=true),
      // then fill B and C.  B and C have newer timestamps than A's post-hit ts,
      // making A the LRU.  After a long cold period D evicts A.
      // dead_tail = eviction_cycle − last_hit_cycle ≈ 400+ >> residence/2 → mostly_dead.
      fill(mock_ul, elements, addr_a, ip, id);       // A fills; insert_cycle=T_A
      run(elements, 5);
      fill(mock_ul, elements, addr_a, ip, id);       // hit A; A.hit_count=1, A.accessed=true
      run(elements, 5);
      fill(mock_ul, elements, 0x2000, ip, id);       // B; ts=T_B > T_A_hit
      run(elements, 5);
      fill(mock_ul, elements, 0x3000, ip, id);       // C; ts=T_C > T_B

      // Long cold period: dead_tail >> residence/2.
      run(elements, 400);

      // Fill D → A is LRU (ts=T_A_hit, oldest) → A evicted as mostly-dead → mostly_dead_A=1.
      fill(mock_ul, elements, 0x4000, ip, id);

      // Phase 1 – age the remaining set.
      run(elements, 400);

      // Phase 2 – fill E to remove the oldest (B).
      fill(mock_ul, elements, 0x5000, ip, id);
      run(elements, 30);

      // Phase 3 – fill A (mostly_dead_A=1 → needs_mid_insertion → median ts).
      fill(mock_ul, elements, addr_a, ip, id);

      // Phase 4 – two fills to drive A out.
      fill(mock_ul, elements, 0x6000, ip, id); // F
      fill(mock_ul, elements, 0x7000, ip, id); // G

      const auto count_before = mock_ll.packet_count();
      fill(mock_ul, elements, addr_a, ip, id); // probe A

      THEN("A is a miss (evicted by mid-insertion due to mostly_dead history)") {
        CHECK(mock_ll.packet_count() == count_before + 1);
      }
    }
  }

}
