// Tests for evict_doa_on_doa_stlb_page — the correlation counter incremented
// when an LLC block is evicted as DoA and the STLB has a currently-resident,
// never-hit entry whose physical page (PFN) matches the LLC block's page.
//
// PFN extraction rules (mirror record_eviction_liveness in cache.cc):
//   LLC block : victim.address >> LOG2_PAGE_SIZE
//   STLB block: block.data    >> LOG2_PAGE_SIZE   (data holds the PA / PFN<<offset)
//
// Test matrix:
//   1. LLC DoA + STLB resident DoA entry, same PFN     → counter increments
//   2. LLC DoA + STLB resident DoA entry, different PFN → counter stays 0
//   3. LLC DoA + STLB resident entry that was hit (not DoA) → counter stays 0
//   4. LLC eviction is NOT DoA (block was hit)          → counter stays 0

#include <deque>
#include <limits>

#include <catch.hpp>
#include "mocks.hpp"
#include "cache.h"
#include "champsim_constants.h"

namespace {

// MRC that always fills the data field with a fixed value.
// Used to give the STLB a controlled physical-address translation.
class fixed_data_MRC : public MemoryRequestConsumer, public champsim::operable
{
  std::deque<PACKET> packets;
  const uint64_t fixed_data;
public:
  explicit fixed_data_MRC(uint64_t d)
    : MemoryRequestConsumer(), champsim::operable(1), fixed_data(d) {}

  void operate() override {
    for (auto& pkt : packets)
      for (auto ret : pkt.to_return)
        ret->return_data(pkt);
    packets.clear();
  }
  bool add_rq(const PACKET& p) override { auto c = p; c.data = fixed_data; packets.push_back(c); return true; }
  bool add_wq(const PACKET&)   override { return true; }
  bool add_pq(const PACKET&)   override { return true; }
  bool add_ptwq(const PACKET&) override { return true; }
  std::size_t get_occupancy(uint8_t, uint64_t) override { return packets.size(); }
  std::size_t get_size(uint8_t, uint64_t)      override { return std::numeric_limits<uint32_t>::max(); }
};

template <typename Array>
void run(Array& elems, int n = 200)
{
  for (int i = 0; i < n; ++i)
    for (auto e : elems)
      e->_operate();
}

PACKET make_load(uint64_t addr, uint64_t ip, uint64_t& next_id)
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

// ── Shared address constants ──────────────────────────────────────────────────
//
// PFN 1 → physical byte address 0x1000 (LOG2_PAGE_SIZE == 12).
// PFN 2 → physical byte address 0x2000.
//
// LLC_ADDR_A and LLC_ADDR_B are on different pages so they both map to
// set 0 in a 1-set LLC and B evicts A.
static constexpr uint64_t PFN1_PA = 1ULL << LOG2_PAGE_SIZE; // 0x1000
static constexpr uint64_t PFN2_PA = 2ULL << LOG2_PAGE_SIZE; // 0x2000

static constexpr uint64_t LLC_ADDR_A = PFN1_PA; // PFN 1
static constexpr uint64_t LLC_ADDR_B = PFN2_PA; // PFN 2 – evicts A

// ── Scenario 1 ───────────────────────────────────────────────────────────────

SCENARIO("LLC DoA block on a DoA STLB page increments evict_doa_on_doa_stlb_page") {
  GIVEN("A cpu0_STLB and an LLC, each 1 set × 1 way") {
    // STLB lower level returns PFN 1 as the physical translation.
    fixed_data_MRC mock_ll_stlb{PFN1_PA};
    CACHE::NonTranslatingQueues stlb_queues{1, 32, 32, 32, 0, 2, LOG2_BLOCK_SIZE, false};
    CACHE stlb{"cpu0_STLB", 1, 1, 1, 32, 2, 1, 1, 0, false, false, false,
               (1 << LOAD) | (1 << PREFETCH), stlb_queues, &mock_ll_stlb,
               CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul_stlb{&stlb};
    std::array<champsim::operable*, 4> stlb_elems{{&mock_ll_stlb, &stlb_queues, &stlb, &mock_ul_stlb}};

    do_nothing_MRC mock_ll_llc;
    CACHE::NonTranslatingQueues llc_queues{1, 32, 32, 32, 0, 2, LOG2_BLOCK_SIZE, false};
    CACHE llc{"LLC", 1, 1, 1, 32, 2, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), llc_queues, &mock_ll_llc,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul_llc{&llc};
    std::array<champsim::operable*, 4> llc_elems{{&mock_ll_llc, &llc_queues, &llc, &mock_ul_llc}};

    // STLB must be initialized first so stlb_ptr is set before LLC evictions.
    stlb.initialize(); stlb.warmup = false; stlb_queues.warmup = false;
    stlb.begin_phase(); stlb_queues.begin_phase();
    llc.initialize(); llc.warmup = false; llc_queues.warmup = false;
    llc.begin_phase(); llc_queues.begin_phase();

    uint64_t id = 1;
    const uint64_t ip = 0xBEEF;

    WHEN("STLB holds a never-hit PFN 1 entry and LLC evicts a DoA block on PFN 1") {
      // Fill STLB: VPN 0xAAAA000 → data = PFN1_PA = 0x1000 → PFN = 1.
      mock_ul_stlb.issue(make_load(0xAAAA000, ip, id));
      run(stlb_elems);

      // Fill LLC with PFN 1 address (no eviction, slot was free).
      mock_ul_llc.issue(make_load(LLC_ADDR_A, ip, id));
      run(llc_elems);

      // Fill PFN 2 → evicts PFN 1 as DoA (hit_count == 0).
      mock_ul_llc.issue(make_load(LLC_ADDR_B, ip, id));
      run(llc_elems);

      THEN("evict_doa_on_doa_stlb_page == 1") {
        CHECK(llc.sim_stats.back().evict_doa_on_doa_stlb_page == 1);
      }
      THEN("evict_doa == 1 (sanity: exactly one DoA eviction)") {
        CHECK(llc.sim_stats.back().evict_doa == 1);
      }
    }
  }
}

// ── Scenario 2 ───────────────────────────────────────────────────────────────

SCENARIO("LLC DoA block whose PFN has no matching STLB entry does not increment the counter") {
  GIVEN("A cpu0_STLB (holding PFN 2) and an LLC, each 1 set × 1 way") {
    // STLB returns PFN 2 — different page from the LLC DoA block.
    fixed_data_MRC mock_ll_stlb{PFN2_PA};
    CACHE::NonTranslatingQueues stlb_queues{1, 32, 32, 32, 0, 2, LOG2_BLOCK_SIZE, false};
    CACHE stlb{"cpu0_STLB", 1, 1, 1, 32, 2, 1, 1, 0, false, false, false,
               (1 << LOAD) | (1 << PREFETCH), stlb_queues, &mock_ll_stlb,
               CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul_stlb{&stlb};
    std::array<champsim::operable*, 4> stlb_elems{{&mock_ll_stlb, &stlb_queues, &stlb, &mock_ul_stlb}};

    do_nothing_MRC mock_ll_llc;
    CACHE::NonTranslatingQueues llc_queues{1, 32, 32, 32, 0, 2, LOG2_BLOCK_SIZE, false};
    CACHE llc{"LLC", 1, 1, 1, 32, 2, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), llc_queues, &mock_ll_llc,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul_llc{&llc};
    std::array<champsim::operable*, 4> llc_elems{{&mock_ll_llc, &llc_queues, &llc, &mock_ul_llc}};

    stlb.initialize(); stlb.warmup = false; stlb_queues.warmup = false;
    stlb.begin_phase(); stlb_queues.begin_phase();
    llc.initialize(); llc.warmup = false; llc_queues.warmup = false;
    llc.begin_phase(); llc_queues.begin_phase();

    uint64_t id = 1;
    const uint64_t ip = 0xBEEF;

    WHEN("STLB holds PFN 2 but LLC evicts a DoA block on PFN 1 (different page)") {
      // Fill STLB with PFN 2.
      mock_ul_stlb.issue(make_load(0xBBBB000, ip, id));
      run(stlb_elems);

      // LLC evicts PFN 1 as DoA.
      mock_ul_llc.issue(make_load(LLC_ADDR_A, ip, id));
      run(llc_elems);
      mock_ul_llc.issue(make_load(LLC_ADDR_B, ip, id));
      run(llc_elems);

      THEN("evict_doa_on_doa_stlb_page == 0 (PFN mismatch)") {
        CHECK(llc.sim_stats.back().evict_doa_on_doa_stlb_page == 0);
      }
      THEN("evict_doa == 1 (sanity: DoA eviction still counted)") {
        CHECK(llc.sim_stats.back().evict_doa == 1);
      }
    }
  }
}

// ── Scenario 3 ───────────────────────────────────────────────────────────────

SCENARIO("LLC DoA block on a page whose STLB entry was hit (not DoA) does not increment") {
  GIVEN("A cpu0_STLB and an LLC, each 1 set × 1 way") {
    fixed_data_MRC mock_ll_stlb{PFN1_PA};
    CACHE::NonTranslatingQueues stlb_queues{1, 32, 32, 32, 0, 2, LOG2_BLOCK_SIZE, false};
    CACHE stlb{"cpu0_STLB", 1, 1, 1, 32, 2, 1, 1, 0, false, false, false,
               (1 << LOAD) | (1 << PREFETCH), stlb_queues, &mock_ll_stlb,
               CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul_stlb{&stlb};
    std::array<champsim::operable*, 4> stlb_elems{{&mock_ll_stlb, &stlb_queues, &stlb, &mock_ul_stlb}};

    do_nothing_MRC mock_ll_llc;
    CACHE::NonTranslatingQueues llc_queues{1, 32, 32, 32, 0, 2, LOG2_BLOCK_SIZE, false};
    CACHE llc{"LLC", 1, 1, 1, 32, 2, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), llc_queues, &mock_ll_llc,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul_llc{&llc};
    std::array<champsim::operable*, 4> llc_elems{{&mock_ll_llc, &llc_queues, &llc, &mock_ul_llc}};

    stlb.initialize(); stlb.warmup = false; stlb_queues.warmup = false;
    stlb.begin_phase(); stlb_queues.begin_phase();
    llc.initialize(); llc.warmup = false; llc_queues.warmup = false;
    llc.begin_phase(); llc_queues.begin_phase();

    uint64_t id = 1;
    const uint64_t ip = 0xBEEF;

    WHEN("STLB PFN 1 entry is hit once before the LLC DoA eviction") {
      // Fill STLB with PFN 1.
      mock_ul_stlb.issue(make_load(0xAAAA000, ip, id));
      run(stlb_elems);

      // Hit the STLB entry → hit_count becomes 1 (no longer DoA).
      mock_ul_stlb.issue(make_load(0xAAAA000, ip, id));
      run(stlb_elems);

      // LLC evicts PFN 1 as DoA.
      mock_ul_llc.issue(make_load(LLC_ADDR_A, ip, id));
      run(llc_elems);
      mock_ul_llc.issue(make_load(LLC_ADDR_B, ip, id));
      run(llc_elems);

      THEN("evict_doa_on_doa_stlb_page == 0 (STLB entry had a hit, hit_count == 1)") {
        CHECK(llc.sim_stats.back().evict_doa_on_doa_stlb_page == 0);
      }
    }
  }
}

// ── Scenario 4 ───────────────────────────────────────────────────────────────

SCENARIO("Non-DoA LLC eviction does not increment evict_doa_on_doa_stlb_page") {
  GIVEN("A cpu0_STLB (DoA PFN 1 entry) and an LLC, each 1 set × 1 way") {
    fixed_data_MRC mock_ll_stlb{PFN1_PA};
    CACHE::NonTranslatingQueues stlb_queues{1, 32, 32, 32, 0, 2, LOG2_BLOCK_SIZE, false};
    CACHE stlb{"cpu0_STLB", 1, 1, 1, 32, 2, 1, 1, 0, false, false, false,
               (1 << LOAD) | (1 << PREFETCH), stlb_queues, &mock_ll_stlb,
               CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul_stlb{&stlb};
    std::array<champsim::operable*, 4> stlb_elems{{&mock_ll_stlb, &stlb_queues, &stlb, &mock_ul_stlb}};

    do_nothing_MRC mock_ll_llc;
    CACHE::NonTranslatingQueues llc_queues{1, 32, 32, 32, 0, 2, LOG2_BLOCK_SIZE, false};
    CACHE llc{"LLC", 1, 1, 1, 32, 2, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), llc_queues, &mock_ll_llc,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul_llc{&llc};
    std::array<champsim::operable*, 4> llc_elems{{&mock_ll_llc, &llc_queues, &llc, &mock_ul_llc}};

    stlb.initialize(); stlb.warmup = false; stlb_queues.warmup = false;
    stlb.begin_phase(); stlb_queues.begin_phase();
    llc.initialize(); llc.warmup = false; llc_queues.warmup = false;
    llc.begin_phase(); llc_queues.begin_phase();

    uint64_t id = 1;
    const uint64_t ip = 0xBEEF;

    WHEN("LLC block on PFN 1 is hit before eviction (not DoA), STLB entry is DoA") {
      // Fill STLB with PFN 1 (never hit → DoA in STLB).
      mock_ul_stlb.issue(make_load(0xAAAA000, ip, id));
      run(stlb_elems);

      // Fill LLC with PFN 1.
      mock_ul_llc.issue(make_load(LLC_ADDR_A, ip, id));
      run(llc_elems);

      // Hit the LLC block → hit_count = 1, so eviction will not be DoA.
      mock_ul_llc.issue(make_load(LLC_ADDR_A, ip, id));
      run(llc_elems);

      // Evict LLC block by filling PFN 2 → classified mostly-alive, not DoA.
      mock_ul_llc.issue(make_load(LLC_ADDR_B, ip, id));
      run(llc_elems);

      THEN("evict_doa_on_doa_stlb_page == 0 (LLC eviction class is not DoA)") {
        CHECK(llc.sim_stats.back().evict_doa_on_doa_stlb_page == 0);
      }
      THEN("evict_doa == 0 (sanity)") {
        CHECK(llc.sim_stats.back().evict_doa == 0);
      }
    }
  }
}
