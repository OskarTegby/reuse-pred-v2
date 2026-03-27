// Tests for the lru_mid replacement policy (replacement/lru_mid/lru_mid.cc).
//
// Policy summary:
//   – For caches named "LLC" or "cpu0_STLB" whose associated predictor is
//     enabled: if needs_mid_insertion() is true, the block is assigned the
//     set-median timestamp (NUM_WAY/2-th smallest in last_used_cycles).
//   – Otherwise (no history, or wrong cache name): standard LRU promotion
//     (way_cycle = current_cycle = MRU position).
//   – Victim selection is always standard LRU (min timestamp).
//
// Test setup
// ----------
// All tests use a 3-way "cpu0_STLB" cache with DPPRED=1 and lru_mid.
// With 3 ways, NUM_WAY/2 = 1: nth_element at index 1 gives the median of
// the three current timestamps.
//
// Eviction-order observable
// -------------------------
// After inserting block A into a full 3-way set, two subsequent fills (F, G)
// are made.  Then A is probed:
//   • Mid-inserted A (doa_A > 0): A has a low recency → A gets evicted by G.
//     Probe is a cache miss.
//   • MRU-inserted A (doa_A = 0):  A is the most-recent block → it survives
//     F and G.  Probe is a cache hit.

#include <cstdlib>

#include <catch.hpp>
#include "mocks.hpp"
#include "cache.h"
#include "champsim_constants.h"

namespace
{
template <typename Array>
void run(Array& elems, int n = 1)
{
  for (int i = 0; i < n; ++i)
    for (auto e : elems)
      e->_operate();
}

template <typename Array, typename MRP>
void fill(MRP& ul, Array& elems, uint64_t addr, uint64_t ip, uint64_t& id)
{
  PACKET p;
  p.address   = addr;
  p.v_address = addr;
  p.ip        = ip;
  p.instr_id  = id++;
  p.cpu       = 0;
  p.type      = LOAD;
  ul.issue(p);
  run(elems, 100);
}
} // namespace

// ── Mid-insertion (DoA history): block is evicted early ──────────────────────

SCENARIO("lru_mid: block with DoA history is mid-inserted and evicted sooner than an MRU block") {
  ::setenv("DPPRED", "1", 1);
  ::unsetenv("PCONF_THD");

  GIVEN("A 3-way cpu0_STLB with lru_mid and DPPRED=1") {
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

    WHEN("A is evicted as DoA once, then re-inserted into the full set") {
      uint64_t id = 1;
      constexpr uint64_t ip     = 0xCAFE;
      constexpr uint64_t addr_a = 0x1000;

      // Phase 0 – establish doa_A = 1.
      fill(mock_ul, elements, addr_a, ip, id);       // A: way 0
      run(elements, 30);
      fill(mock_ul, elements, 0x2000, ip, id);       // B: way 1
      run(elements, 30);
      fill(mock_ul, elements, 0x3000, ip, id);       // C: way 2
      run(elements, 30);
      fill(mock_ul, elements, 0x4000, ip, id);       // D: evicts A (LRU) as DoA → doa_A=1

      // Age the set so timestamps are well separated.
      run(elements, 400);

      // Phase 1 – remove the oldest block (B) to make A's median meaningful.
      fill(mock_ul, elements, 0x5000, ip, id);       // E: evicts B (LRU)
      run(elements, 30);

      // Phase 2 – re-insert A with mid-insertion (doa_A=1 > 0).
      // C is now the LRU.  A fills C's way.
      // Median of {T_D, T_E, T_C} (T_C < T_D < T_E) = T_D.  A gets ts=T_D.
      // State: {D:T_D, E:T_E, A:T_D}.  D and A tied; D is way 0 → evicted first.
      fill(mock_ul, elements, addr_a, ip, id);       // A: mid-inserted at ts≈T_D

      // Phase 3 – two fills that should evict D then A.
      fill(mock_ul, elements, 0x6000, ip, id);       // F: evicts D (way 0, first tie)
      fill(mock_ul, elements, 0x7000, ip, id);       // G: evicts A (now the LRU)

      // Probe A: should be a miss because A was evicted.
      const auto count_before = mock_ll.packet_count();
      fill(mock_ul, elements, addr_a, ip, id);

      THEN("A is a miss — mid-insertion placed it at median, so it was evicted by G") {
        CHECK(mock_ll.packet_count() == count_before + 1);
      }
    }
  }

  ::unsetenv("DPPRED");
}

// ── MRU insertion (no history): block survives two fills ─────────────────────

SCENARIO("lru_mid: fresh block without history is inserted at MRU and survives two fills") {
  // DPPRED disabled → phist never updated → doa always 0 → MRU insertion.
  ::unsetenv("DPPRED");
  ::unsetenv("PCONF_THD");

  GIVEN("A 3-way cpu0_STLB with lru_mid but DPPRED disabled") {
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

    WHEN("A is inserted into a full set with no prior DoA history") {
      uint64_t id = 1;
      constexpr uint64_t ip     = 0xCAFE;
      constexpr uint64_t addr_a = 0x1000;

      // Fill D, E, C to saturate (A never in cache yet).
      fill(mock_ul, elements, 0x4000, ip, id);      // D: way 0
      run(elements, 30);
      fill(mock_ul, elements, 0x5000, ip, id);      // E: way 1
      run(elements, 30);
      fill(mock_ul, elements, 0x3000, ip, id);      // C: way 2

      // Age the set.
      run(elements, 400);

      // Insert A (fresh, no history → MRU).
      // D is the LRU; A evicts D.  A gets ts=current_cycle >> C, E.
      fill(mock_ul, elements, addr_a, ip, id);      // A: MRU (ts >> T_E)

      // Two fills: F evicts the new LRU (E), G evicts the next (C).
      // A is still the most-recent and should NOT be evicted yet.
      fill(mock_ul, elements, 0x6000, ip, id);      // F
      fill(mock_ul, elements, 0x7000, ip, id);      // G

      const auto count_before = mock_ll.packet_count();
      fill(mock_ul, elements, addr_a, ip, id);      // probe A

      THEN("A is a hit — inserted at MRU, it outlives F and G") {
        CHECK(mock_ll.packet_count() == count_before); // no new miss for A
      }
    }
  }
}

// ── Non-LLC/STLB cache always uses plain LRU ─────────────────────────────────

SCENARIO("lru_mid: a cache not named LLC or cpu0_STLB always uses MRU insertion") {
  // Even with DPPRED=1, a cache named e.g. "L1D" never calls needs_mid_insertion.
  // So the block is always placed at MRU regardless of any history in phist.
  ::setenv("DPPRED", "1", 1);
  ::unsetenv("PCONF_THD");

  GIVEN("A 3-way L1D cache with lru_mid and DPPRED=1") {
    constexpr uint64_t hit_latency  = 2;
    constexpr uint64_t fill_latency = 2;
    do_nothing_MRC mock_ll;
    CACHE::NonTranslatingQueues uut_queues{1, 32, 32, 32, 0, hit_latency, LOG2_BLOCK_SIZE, false};
    CACHE uut{"L1D", 1, 1, 3, 32, fill_latency, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), uut_queues, &mock_ll,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru_mid};
    to_rq_MRP mock_ul{&uut};

    std::array<champsim::operable*, 4> elements{{&mock_ll, &uut_queues, &uut, &mock_ul}};
    uut.initialize();
    uut.warmup = false;
    uut_queues.warmup = false;
    uut.begin_phase();
    uut_queues.begin_phase();

    WHEN("Blocks are inserted (even after simulating DoA evictions)") {
      uint64_t id = 1;
      constexpr uint64_t ip     = 0xCAFE;
      constexpr uint64_t addr_a = 0x1000;

      // Fill the set.
      fill(mock_ul, elements, addr_a, ip, id);      // A
      run(elements, 30);
      fill(mock_ul, elements, 0x2000, ip, id);      // B
      run(elements, 30);
      fill(mock_ul, elements, 0x3000, ip, id);      // C

      // Force A to be evicted (DoA: no hits on A). Even if phist were consulted,
      // the NAME is "L1D" so lru_mid always uses MRU for this cache.
      run(elements, 30);
      fill(mock_ul, elements, 0x4000, ip, id);      // D evicts A (DoA)

      run(elements, 400); // age the set

      fill(mock_ul, elements, 0x5000, ip, id);      // E evicts B (LRU)
      run(elements, 30);

      // Re-insert A: NAME is "L1D" → needs_mid_insertion not called → MRU.
      fill(mock_ul, elements, addr_a, ip, id);      // A: MRU (ts >> T_C, T_D, T_E)

      // Two fills after A's insertion.
      fill(mock_ul, elements, 0x6000, ip, id);      // F
      fill(mock_ul, elements, 0x7000, ip, id);      // G

      const auto count_before = mock_ll.packet_count();
      fill(mock_ul, elements, addr_a, ip, id);      // probe A

      THEN("A is a hit — lru_mid uses plain MRU for non-LLC/STLB caches") {
        CHECK(mock_ll.packet_count() == count_before);
      }
    }
  }

  ::unsetenv("DPPRED");
}
