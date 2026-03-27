// Tests for liveness classification and eviction stats recorded in
// record_eviction_liveness() (cache.cc).
//
// Liveness is only tracked for caches named "LLC" or "cpu0_STLB".
// All test caches below are named "LLC" to activate that path.
//
// Definitions (all in simulation cycles):
//   residence  = eviction_cycle − insert_cycle
//   dead_tail  = eviction_cycle − last_hit_cycle
//   DoA        : hit_count == 0
//   mostly_dead: hit_count > 0  AND  dead_tail > residence / 2
//   mostly_alive: hit_count > 0 AND dead_tail ≤ residence / 2

#include <catch.hpp>
#include "mocks.hpp"
#include "cache.h"
#include "champsim_constants.h"

// ── helpers ─────────────────────────────────────────────────────────────────

// Advance all elements by N cycles.
template <typename Array>
static void run(Array& elems, int n = 1)
{
  for (int i = 0; i < n; ++i)
    for (auto e : elems)
      e->_operate();
}

// Issue a LOAD to the RQ and return the packet (to_return not set).
static PACKET make_load(uint64_t addr, uint64_t ip, uint64_t& next_id)
{
  PACKET p;
  p.address   = addr;
  p.v_address = addr;
  p.ip        = ip;
  p.instr_id  = next_id++;
  p.cpu       = 0;
  p.type      = LOAD;
  return p;
}

// ── DoA eviction ─────────────────────────────────────────────────────────────

SCENARIO("A block evicted without any hit is classified as DoA") {
  GIVEN("An LLC with 1 set, 1 way") {
    constexpr uint64_t hit_latency  = 2;
    constexpr uint64_t fill_latency = 2;
    do_nothing_MRC mock_ll;
    CACHE::NonTranslatingQueues uut_queues{1, 32, 32, 32, 0, hit_latency, LOG2_BLOCK_SIZE, false};
    CACHE uut{"LLC", 1, 1, 1, 32, fill_latency, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), uut_queues, &mock_ll,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul{&uut};

    std::array<champsim::operable*, 4> elements{{&mock_ll, &uut_queues, &uut, &mock_ul}};
    uut.initialize();
    uut.warmup = false;
    uut_queues.warmup = false;
    uut.begin_phase();
    uut_queues.begin_phase();

    WHEN("Block A is filled then immediately evicted by block B (no hit on A)") {
      uint64_t id = 1;
      const uint64_t ip = 0xABCD;
      // Fill block A.
      mock_ul.issue(make_load(0x1000, ip, id));
      run(elements, 100);

      // Fill block B — evicts A (DoA: zero hits on A).
      mock_ul.issue(make_load(0x2000, ip, id));
      run(elements, 100);

      THEN("evict_total == 1, evict_doa == 1, evict_hit_hist[0] == 1") {
        CHECK(uut.sim_stats.back().evict_total == 1);
        CHECK(uut.sim_stats.back().evict_doa   == 1);
        CHECK(uut.sim_stats.back().evict_mostly_dead  == 0);
        CHECK(uut.sim_stats.back().evict_mostly_alive == 0);
        CHECK(uut.sim_stats.back().evict_hit_hist[0]  == 1);
      }

      THEN("class counts sum to evict_total") {
        const auto& s = uut.sim_stats.back();
        CHECK(s.evict_doa + s.evict_mostly_dead + s.evict_mostly_alive == s.evict_total);
      }
    }
  }
}

// ── Mostly-dead eviction ──────────────────────────────────────────────────────

SCENARIO("A block hit once early then left cold is classified as mostly-dead") {
  GIVEN("An LLC with 1 set, 1 way") {
    constexpr uint64_t hit_latency  = 2;
    constexpr uint64_t fill_latency = 2;
    do_nothing_MRC mock_ll;
    CACHE::NonTranslatingQueues uut_queues{1, 32, 32, 32, 0, hit_latency, LOG2_BLOCK_SIZE, false};
    CACHE uut{"LLC", 1, 1, 1, 32, fill_latency, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), uut_queues, &mock_ll,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul{&uut};

    std::array<champsim::operable*, 4> elements{{&mock_ll, &uut_queues, &uut, &mock_ul}};
    uut.initialize();
    uut.warmup = false;
    uut_queues.warmup = false;
    uut.begin_phase();
    uut_queues.begin_phase();

    WHEN("Block A is filled, hit once near insertion, then evicted after a long cold period") {
      uint64_t id = 1;
      const uint64_t ip = 0xABCD;
      const uint64_t addr_a = 0x1000;

      // Fill A.
      mock_ul.issue(make_load(addr_a, ip, id));
      run(elements, 20); // let the fill complete

      // Hit A once shortly after filling.
      mock_ul.issue(make_load(addr_a, ip, id));
      run(elements, 10); // hit processed

      // Long cold period — A sits unused.
      run(elements, 300);

      // Fill B — evicts A.  dead_tail ≈ 300 >> residence/2.
      mock_ul.issue(make_load(0x2000, ip, id));
      run(elements, 100);

      THEN("evict_mostly_dead == 1") {
        CHECK(uut.sim_stats.back().evict_total       == 1);
        CHECK(uut.sim_stats.back().evict_mostly_dead == 1);
        CHECK(uut.sim_stats.back().evict_doa         == 0);
        CHECK(uut.sim_stats.back().evict_mostly_alive == 0);
        CHECK(uut.sim_stats.back().evict_hit_hist[1] == 1);
      }
    }
  }
}

// ── Mostly-alive eviction ─────────────────────────────────────────────────────

SCENARIO("A block hit shortly before eviction is classified as mostly-alive") {
  GIVEN("An LLC with 1 set, 1 way") {
    constexpr uint64_t hit_latency  = 2;
    constexpr uint64_t fill_latency = 2;
    do_nothing_MRC mock_ll;
    CACHE::NonTranslatingQueues uut_queues{1, 32, 32, 32, 0, hit_latency, LOG2_BLOCK_SIZE, false};
    CACHE uut{"LLC", 1, 1, 1, 32, fill_latency, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), uut_queues, &mock_ll,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul{&uut};

    std::array<champsim::operable*, 4> elements{{&mock_ll, &uut_queues, &uut, &mock_ul}};
    uut.initialize();
    uut.warmup = false;
    uut_queues.warmup = false;
    uut.begin_phase();
    uut_queues.begin_phase();

    WHEN("Block A is filled, let to age, hit just before eviction") {
      uint64_t id = 1;
      const uint64_t ip = 0xABCD;
      const uint64_t addr_a = 0x1000;

      // Fill A.
      mock_ul.issue(make_load(addr_a, ip, id));
      run(elements, 20);

      // Long cold period before the hit.
      run(elements, 300);

      // Hit A right before the evicting fill.
      mock_ul.issue(make_load(addr_a, ip, id));
      run(elements, 10); // hit processed, last_hit_cycle ≈ now

      // Fill B — evicts A immediately.  dead_tail is tiny, residence is large.
      mock_ul.issue(make_load(0x2000, ip, id));
      run(elements, 100);

      THEN("evict_mostly_alive == 1") {
        CHECK(uut.sim_stats.back().evict_total        == 1);
        CHECK(uut.sim_stats.back().evict_mostly_alive == 1);
        CHECK(uut.sim_stats.back().evict_doa          == 0);
        CHECK(uut.sim_stats.back().evict_mostly_dead  == 0);
        CHECK(uut.sim_stats.back().evict_hit_hist[1]  == 1);
      }
    }
  }
}

// ── Hit histogram ────────────────────────────────────────────────────────────

SCENARIO("Hit histogram bin matches the number of hits before eviction") {
  using namespace std::literals;
  auto [num_hits, bin] = GENERATE(table<unsigned, std::size_t>({
        std::pair{0u, 0u},
        std::pair{1u, 1u},
        std::pair{3u, 3u},
  }));

  GIVEN("An LLC with 1 set, 1 way") {
    constexpr uint64_t hit_latency  = 2;
    constexpr uint64_t fill_latency = 2;
    do_nothing_MRC mock_ll;
    CACHE::NonTranslatingQueues uut_queues{1, 32, 32, 32, 0, hit_latency, LOG2_BLOCK_SIZE, false};
    CACHE uut{"LLC", 1, 1, 1, 32, fill_latency, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), uut_queues, &mock_ll,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul{&uut};

    std::array<champsim::operable*, 4> elements{{&mock_ll, &uut_queues, &uut, &mock_ul}};
    uut.initialize();
    uut.warmup = false;
    uut_queues.warmup = false;
    uut.begin_phase();
    uut_queues.begin_phase();

    WHEN("Block A is filled, hit " + std::to_string(num_hits) + " time(s), then evicted") {
      uint64_t id = 1;
      const uint64_t ip = 0xABCD;
      const uint64_t addr_a = 0x1000;

      // Fill A.
      mock_ul.issue(make_load(addr_a, ip, id));
      run(elements, 50);

      // Issue the requested number of hits to A.
      for (unsigned h = 0; h < num_hits; ++h) {
        mock_ul.issue(make_load(addr_a, ip, id));
        run(elements, 20);
      }

      // Fill B — evicts A.
      mock_ul.issue(make_load(0x2000, ip, id));
      run(elements, 50);

      THEN("evict_hit_hist[" + std::to_string(bin) + "] == 1 and all other bins are 0") {
        CHECK(uut.sim_stats.back().evict_total == 1);
        CHECK(uut.sim_stats.back().evict_hit_hist[bin] == 1);
        uint64_t other_sum = 0;
        for (std::size_t i = 0; i < cache_stats::HIT_HIST_BINS; ++i)
          if (i != bin)
            other_sum += uut.sim_stats.back().evict_hit_hist[i];
        CHECK(other_sum == 0);
      }
    }
  }
}

// ── Consistency invariant ────────────────────────────────────────────────────

SCENARIO("Liveness class counts always sum to evict_total") {
  GIVEN("An LLC with 1 set and 2 ways") {
    constexpr uint64_t hit_latency  = 2;
    constexpr uint64_t fill_latency = 2;
    do_nothing_MRC mock_ll;
    CACHE::NonTranslatingQueues uut_queues{1, 32, 32, 32, 0, hit_latency, LOG2_BLOCK_SIZE, false};
    CACHE uut{"LLC", 1, 2, 1, 32, fill_latency, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), uut_queues, &mock_ll,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul{&uut};

    std::array<champsim::operable*, 4> elements{{&mock_ll, &uut_queues, &uut, &mock_ul}};
    uut.initialize();
    uut.warmup = false;
    uut_queues.warmup = false;
    uut.begin_phase();
    uut_queues.begin_phase();

    WHEN("Several blocks are filled and evicted with mixed hit patterns") {
      uint64_t id = 1;
      const uint64_t ip = 0xABCD;

      // Fill A (no hits → DoA on eviction).
      mock_ul.issue(make_load(0x1000, ip, id));
      run(elements, 30);

      // Fill B, hit it once near the start (→ mostly-dead on eviction).
      mock_ul.issue(make_load(0x2000, ip, id));
      run(elements, 20);
      mock_ul.issue(make_load(0x2000, ip, id)); // hit B
      run(elements, 10);

      // Fill C — evicts A (DoA).
      mock_ul.issue(make_load(0x3000, ip, id));
      run(elements, 200); // long wait so B's dead_tail > residence/2

      // Fill D — evicts B (mostly-dead).
      mock_ul.issue(make_load(0x4000, ip, id));
      run(elements, 50);

      THEN("class sum equals evict_total") {
        const auto& s = uut.sim_stats.back();
        CHECK(s.evict_doa + s.evict_mostly_dead + s.evict_mostly_alive == s.evict_total);
      }

      THEN("histogram sum equals evict_total") {
        const auto& s = uut.sim_stats.back();
        uint64_t hist_sum = 0;
        for (auto v : s.evict_hit_hist)
          hist_sum += v;
        CHECK(hist_sum == s.evict_total);
      }
    }
  }
}
