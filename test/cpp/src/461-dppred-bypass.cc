// Tests for the dpPred bypass mechanism (src/cache.cc: dppred_bypass).
//
// dpPred is enabled via the DPPRED environment variable.  The bypass fires
// when phist[vpn_hash][pc_hash].doa > pconf_thd.  The doa counter increments
// on every DoA eviction of the same (VPN, PC) pair and resets when the
// block is evicted as non-DoA (i.e. it had at least one hit).
//
// PCONF_THD is set to 1 in these tests to make the threshold easy to reach:
// bypass fires once doa > 1, i.e. after two DoA evictions of the same address.
//
// The cache is named "cpu0_STLB" because that is the only name that activates
// the dpPred bypass path.

#include <cstdlib>

#include <catch.hpp>
#include "mocks.hpp"
#include "cache.h"
#include "champsim_constants.h"

namespace
{
template <typename Array>
void run(Array& elems, int n = 200)
{
  for (int i = 0; i < n; ++i)
    for (auto e : elems)
      e->_operate();
}

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
} // namespace

// ── Bypass fires after sufficient DoA evictions ───────────────────────────────

SCENARIO("dpPred bypasses a fill after enough DoA evictions of the same address") {
  // pconf_thd = 1  →  bypass when doa > 1  (after two DoA evictions).
  ::setenv("DPPRED",    "1", 1);
  ::setenv("PCONF_THD", "1", 1);

  GIVEN("A cpu0_STLB with 1 set and 1 way") {
    constexpr uint64_t hit_latency  = 2;
    constexpr uint64_t fill_latency = 2;
    do_nothing_MRC mock_ll;
    CACHE::NonTranslatingQueues uut_queues{1, 32, 32, 32, 0, hit_latency, LOG2_BLOCK_SIZE, false};
    CACHE uut{"cpu0_STLB", 1, 1, 1, 32, fill_latency, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), uut_queues, &mock_ll,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul{&uut};

    std::array<champsim::operable*, 4> elements{{&mock_ll, &uut_queues, &uut, &mock_ul}};
    uut.initialize();
    uut.warmup = false;
    uut_queues.warmup = false;
    uut.begin_phase();
    uut_queues.begin_phase();

    WHEN("Addresses A and B are filled alternately with no hits (all DoA)") {
      uint64_t id = 1;
      const uint64_t ip     = 0xCAFE;
      const uint64_t addr_a = 0x1000;
      const uint64_t addr_b = 0x2000;

      // Fill A  (set was empty — no eviction).
      mock_ul.issue(make_load(addr_a, ip, id));
      run(elements);

      // Fill B  → A evicted DoA  (doa_A = 1).
      mock_ul.issue(make_load(addr_b, ip, id));
      run(elements);

      // Fill A  → B evicted DoA  (doa_B = 1); bypass check for A: doa_A=1 ≤ 1 → no bypass.
      mock_ul.issue(make_load(addr_a, ip, id));
      run(elements);

      // Fill B  → A evicted DoA  (doa_A = 2); bypass check for B: doa_B=1 ≤ 1 → no bypass.
      mock_ul.issue(make_load(addr_b, ip, id));
      run(elements);

      // Verify no bypass yet.
      THEN("No bypass has fired so far") {
        CHECK(uut.sim_stats.back().llt_bypasses == 0);
      }

      // Fill A  → bypass check for A: doa_A=2 > 1  → BYPASS.
      mock_ul.issue(make_load(addr_a, ip, id));
      run(elements);

      THEN("Exactly one bypass has been recorded") {
        CHECK(uut.sim_stats.back().llt_bypasses == 1);
      }
    }
  }

  ::unsetenv("DPPRED");
  ::unsetenv("PCONF_THD");
}

// ── No bypass when predictor is disabled ─────────────────────────────────────

SCENARIO("No bypass occurs when dpPred is not enabled") {
  // Do not set DPPRED — should default to off.
  ::unsetenv("DPPRED");
  ::unsetenv("PCONF_THD");

  GIVEN("A cpu0_STLB with 1 set and 1 way, no DPPRED") {
    constexpr uint64_t hit_latency  = 2;
    constexpr uint64_t fill_latency = 2;
    do_nothing_MRC mock_ll;
    CACHE::NonTranslatingQueues uut_queues{1, 32, 32, 32, 0, hit_latency, LOG2_BLOCK_SIZE, false};
    CACHE uut{"cpu0_STLB", 1, 1, 1, 32, fill_latency, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), uut_queues, &mock_ll,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul{&uut};

    std::array<champsim::operable*, 4> elements{{&mock_ll, &uut_queues, &uut, &mock_ul}};
    uut.initialize();
    uut.warmup = false;
    uut_queues.warmup = false;
    uut.begin_phase();
    uut_queues.begin_phase();

    WHEN("Many DoA evictions occur") {
      uint64_t id = 1;
      const uint64_t ip     = 0xCAFE;
      const uint64_t addr_a = 0x1000;
      const uint64_t addr_b = 0x2000;

      for (int i = 0; i < 20; ++i) {
        mock_ul.issue(make_load(addr_a, ip, id));
        run(elements);
        mock_ul.issue(make_load(addr_b, ip, id));
        run(elements);
      }

      THEN("llt_bypasses is zero") {
        CHECK(uut.sim_stats.back().llt_bypasses == 0);
      }
    }
  }
}

// ── DoA counter resets after a hit, disabling bypass ─────────────────────────

SCENARIO("Bypass is suppressed after a non-DoA eviction resets the doa counter") {
  // pconf_thd = 2  →  bypass fires when doa > 2 (after three DoA evictions).
  // We build doa_A to 2, then get a hit on A (making its next eviction non-DoA),
  // which resets doa_A to 0.  After the reset, further DoA evictions start from
  // zero and should not immediately trigger a bypass.
  ::setenv("DPPRED",    "1", 1);
  ::setenv("PCONF_THD", "2", 1);

  GIVEN("A cpu0_STLB with 1 set and 1 way") {
    constexpr uint64_t hit_latency  = 2;
    constexpr uint64_t fill_latency = 2;
    do_nothing_MRC mock_ll;
    CACHE::NonTranslatingQueues uut_queues{1, 32, 32, 32, 0, hit_latency, LOG2_BLOCK_SIZE, false};
    CACHE uut{"cpu0_STLB", 1, 1, 1, 32, fill_latency, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), uut_queues, &mock_ll,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul{&uut};

    std::array<champsim::operable*, 4> elements{{&mock_ll, &uut_queues, &uut, &mock_ul}};
    uut.initialize();
    uut.warmup = false;
    uut_queues.warmup = false;
    uut.begin_phase();
    uut_queues.begin_phase();

    WHEN("doa_A is built up to 2, then A is hit before its next eviction") {
      uint64_t id = 1;
      const uint64_t ip     = 0xCAFE;
      const uint64_t addr_a = 0x1000;
      const uint64_t addr_b = 0x2000;

      // Fill A (no eviction).
      mock_ul.issue(make_load(addr_a, ip, id));
      run(elements);

      // Alternate A/B fills (all DoA) until doa_A = 2.
      // Step 1: Fill B → A evicted DoA (doa_A=1), B installed.
      mock_ul.issue(make_load(addr_b, ip, id));
      run(elements);
      // Step 2: Fill A → B evicted DoA (doa_B=1), A installed; bypass check A: 1≤2 ok.
      mock_ul.issue(make_load(addr_a, ip, id));
      run(elements);
      // Step 3: Fill B → A evicted DoA (doa_A=2), B installed; bypass check B: 1≤2 ok.
      mock_ul.issue(make_load(addr_b, ip, id));
      run(elements);
      // Step 4: Fill A → B evicted DoA (doa_B=2), A installed; bypass check A: 2≤2 ok.
      mock_ul.issue(make_load(addr_a, ip, id));
      run(elements);

      // Hit A — sets accessed bit; next eviction of A will be non-DoA → doa_A resets.
      mock_ul.issue(make_load(addr_a, ip, id));
      run(elements, 20); // let the hit complete

      // Fill B — evicts A as non-DoA (accessed=true) → doa_A reset to 0.
      mock_ul.issue(make_load(addr_b, ip, id));
      run(elements);

      // Now doa_A = 0.  One more DoA eviction makes doa_A = 1, still ≤ 2.
      mock_ul.issue(make_load(addr_a, ip, id));
      run(elements);

      THEN("No bypass has fired (doa_A was reset and hasn't re-saturated)") {
        CHECK(uut.sim_stats.back().llt_bypasses == 0);
      }
    }
  }

  ::unsetenv("DPPRED");
  ::unsetenv("PCONF_THD");
}
