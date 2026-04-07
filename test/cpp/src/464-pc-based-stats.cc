// Tests for per-PC liveness statistics (llt_pc_stats / llc_pc_stats).
//
// llt_pc_stats and llc_pc_stats track liveness observations aggregated
// by PC, independently of the per-address tables (phist / bhist) that drive
// bypass and mid-insertion decisions.  They are updated by the same rules as
// their per-address counterparts but are NOT consulted by dppred_bypass,
// cbpred_bypass, or needs_mid_insertion.
//
// Because the maps are private and have no effect on bypass or replacement,
// this test verifies the separation: a new address B from a PC that has
// accumulated DoA history is inserted at MRU (NOT mid-inserted), confirming
// that llt_pc_stats does not influence the replacement policy.
//
// Cache setup: 3-way cpu0_STLB, lru_mid replacement, DPPRED=1.
//
// Test shape
// ----------
//  Phase 0  Build per-PC DoA history: evict address A from PC0 as DoA.
//           llt_pc_stats[PC0].doa = 1.
//           phist has no entry for addr_b (new address) and PC0.
//  Phase 1  Age the cache.
//  Phase 2  Fill E to open a slot.
//  Phase 3  Fill B (new address, same PC0).
//           phist[h(vpn_b)][h(PC0)] is absent → needs_mid_insertion = false → B inserted at MRU.
//           llt_pc_stats[PC0].doa = 1 but uses the full IP as key and is not consulted.
//  Phase 4  Fill two more addresses.
//           B (MRU) should survive; the two older entries are evicted first.
//  Probe    Access B: should hit.

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
  run(elems, 100);
}
} // namespace

// ── Per-PC stats do not influence mid-insertion ───────────────────────────────

SCENARIO("llt_pc_stats: per-PC DoA history does not trigger mid-insertion for a new address") {
  ::setenv("DPPRED", "1", 1);
  ::unsetenv("PCONF_THD"); // keep default threshold (6) so no bypass fires

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

    WHEN("Address A from PC0 is evicted as DoA, then a new address B from the same PC0 is filled") {
      uint64_t id = 1;
      constexpr uint64_t pc0    = 0xCAFE;
      constexpr uint64_t addr_a = 0x1000; // accumulates DoA in llt_pc_stats[PC0]
      constexpr uint64_t addr_b = 0x9000; // new address — no entry in phist for (vpn_b, PC0)

      // Phase 0 – build llt_pc_stats[PC0].doa = 1.
      // Fill A, B_filler, C_filler, then D_filler → A evicted as DoA.
      fill(mock_ul, elements, addr_a, pc0, id);       // A: way 0
      run(elements, 30);
      fill(mock_ul, elements, 0x2000, pc0, id);       // B_fill: way 1
      run(elements, 30);
      fill(mock_ul, elements, 0x3000, pc0, id);       // C_fill: way 2
      run(elements, 30);
      fill(mock_ul, elements, 0x4000, pc0, id);       // D_fill: evicts A as DoA

      // Phase 1 – age the remaining entries.
      run(elements, 400);

      // Phase 2 – fill E to evict the oldest of {B_fill, C_fill, D_fill}.
      fill(mock_ul, elements, 0x5000, pc0, id);
      run(elements, 30);

      // Phase 3 – fill B (new address, same PC0).
      // phist has no entry for (vpn_b, PC0) → needs_mid_insertion = false → MRU insertion.
      // llt_pc_stats[PC0].doa = 1 but is not consulted by needs_mid_insertion.
      fill(mock_ul, elements, addr_b, pc0, id);       // B: MRU-inserted

      // Phase 4 – two more fills; B (MRU) should survive.
      fill(mock_ul, elements, 0x6000, pc0, id);       // F: evicts oldest
      fill(mock_ul, elements, 0x7000, pc0, id);       // G: evicts next oldest

      const auto count_before = mock_ll.packet_count();
      fill(mock_ul, elements, addr_b, pc0, id);       // probe B

      THEN("B is a hit — per-PC stats do not affect insertion policy; B survives at MRU") {
        CHECK(mock_ll.packet_count() == count_before);
      }
    }
  }

  ::unsetenv("DPPRED");
}
