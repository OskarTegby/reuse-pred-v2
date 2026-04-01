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
  // A has never been evicted → mid_hist_addr has no entry for A's VPN →
  // needs_mid_insertion returns false → MRU insertion.
  // DPPRED state is irrelevant: mid-insertion history is tracked independently.
  ::unsetenv("DPPRED");
  ::unsetenv("MID_KEY"); // addr-based (default)

  GIVEN("A 3-way cpu0_STLB with lru_mid and no prior eviction history for A") {
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
  // needs_mid_insertion() only fires for caches named "LLC" or "cpu0_STLB".
  // A cache named "L1D" always uses plain MRU regardless of any history.
  ::unsetenv("DPPRED");
  ::unsetenv("MID_KEY");

  GIVEN("A 3-way L1D cache with lru_mid") {
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

      // Force A to be evicted (DoA: no hits on A).
      // The NAME is "L1D" so lru_mid always uses MRU for this cache
      // (mid_hist tables are not updated and needs_mid_insertion is not called).
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

// ── Mid-insertion works without DPPRED (addr key) ────────────────────────────
// Key regression test: verifies that lru_mid uses its own mid_hist tables,
// not the predictor tables (phist/bhist), to decide on insertion position.
// With DPPRED disabled, phist is never updated — but mid_hist_addr IS updated
// at every STLB eviction.  So needs_mid_insertion should still return true.

SCENARIO("lru_mid: mid-insertion fires without DPPRED when addr has DoA history (MID_KEY=addr)") {
  ::unsetenv("DPPRED");
  ::unsetenv("MID_KEY"); // addr-based (default)

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

    WHEN("A is evicted as DoA (populating mid_hist_addr), then re-inserted") {
      uint64_t id = 1;
      constexpr uint64_t ip     = 0xCAFE;
      constexpr uint64_t addr_a = 0x1000;

      // Phase 0 – build doa_A = 1 in mid_hist_addr (DPPRED is off; phist is NOT updated).
      fill(mock_ul, elements, addr_a, ip, id);       // A: way 0
      run(elements, 30);
      fill(mock_ul, elements, 0x2000, ip, id);       // B: way 1
      run(elements, 30);
      fill(mock_ul, elements, 0x3000, ip, id);       // C: way 2
      run(elements, 30);
      fill(mock_ul, elements, 0x4000, ip, id);       // D: evicts A (LRU) as DoA → mid_hist_addr[A]++

      run(elements, 400);

      // Phase 1 – evict B to free a slot with an old timestamp.
      fill(mock_ul, elements, 0x5000, ip, id);       // E: evicts B (LRU)
      run(elements, 30);

      // Phase 2 – re-insert A; mid_hist_addr[A].doa >= mid_thd → mid-inserted.
      fill(mock_ul, elements, addr_a, ip, id);       // A: mid-inserted (ts ≈ median)

      // Phase 3 – two fills that should drive A out.
      fill(mock_ul, elements, 0x6000, ip, id);       // F: evicts D (first tie)
      fill(mock_ul, elements, 0x7000, ip, id);       // G: evicts A (now the LRU)

      const auto count_before = mock_ll.packet_count();
      fill(mock_ul, elements, addr_a, ip, id);       // probe A

      THEN("A is a miss — mid-insertion fired without DPPRED via mid_hist_addr") {
        CHECK(mock_ll.packet_count() == count_before + 1);
      }
    }
  }
}

// ── Mid-insertion with PC key (MID_KEY=1) ────────────────────────────────────
// Verifies the MID_KEY toggle: when MID_KEY=1 (pc), needs_mid_insertion reads
// from mid_hist_pc keyed by the instruction PC rather than the block address.
// Two different addresses accessed from the same PC should both trigger
// mid-insertion once the PC has accumulated DoA history.

SCENARIO("lru_mid: mid-insertion fires on same PC regardless of address (MID_KEY=pc)") {
  ::unsetenv("DPPRED");
  ::setenv("MID_KEY", "1", 1); // pc-based

  GIVEN("A 3-way cpu0_STLB with lru_mid, DPPRED disabled, and MID_KEY=pc") {
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

    WHEN("addr_X (different from addr_a) is evicted DoA from ip, then addr_a from same ip is re-inserted") {
      uint64_t id = 1;
      constexpr uint64_t ip     = 0xCAFE;  // shared PC for both addresses
      constexpr uint64_t addr_x = 0x8000;  // first address — its eviction builds pc history
      constexpr uint64_t addr_a = 0x1000;  // second address — should trigger mid-insertion via PC

      // Phase 0 – build doa for ip in mid_hist_pc via addr_x's DoA eviction.
      fill(mock_ul, elements, addr_x, ip, id);       // X: way 0, ip=0xCAFE
      run(elements, 30);
      fill(mock_ul, elements, 0x2000, ip, id);       // B: way 1
      run(elements, 30);
      fill(mock_ul, elements, 0x3000, ip, id);       // C: way 2
      run(elements, 30);
      fill(mock_ul, elements, 0x4000, ip, id);       // D: evicts X (LRU) as DoA → mid_hist_pc[ip]++

      run(elements, 400);

      // Phase 1 – evict B to free a slot.
      fill(mock_ul, elements, 0x5000, ip, id);       // E: evicts B (LRU)
      run(elements, 30);

      // Phase 2 – insert addr_a from the same ip.
      // mid_hist_pc[ip].doa >= mid_thd → needs_mid_insertion → mid-inserted.
      fill(mock_ul, elements, addr_a, ip, id);       // A: mid-inserted (ts ≈ median)

      // Phase 3 – two fills that should drive A out.
      fill(mock_ul, elements, 0x6000, ip, id);       // F: evicts D (first tie)
      fill(mock_ul, elements, 0x7000, ip, id);       // G: evicts A (now the LRU)

      const auto count_before = mock_ll.packet_count();
      fill(mock_ul, elements, addr_a, ip, id);       // probe A

      THEN("A is a miss — mid-insertion fired for addr_a because its PC has DoA history") {
        CHECK(mock_ll.packet_count() == count_before + 1);
      }
    }
  }

  ::unsetenv("MID_KEY");
}
