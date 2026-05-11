// Tests for the LLC DoA / STLB correlation counters.
//
// PFN extraction rules (mirror record_eviction_liveness in cache.cc):
//   LLC block : victim.address >> LOG2_PAGE_SIZE
//   STLB block: block.data    >> LOG2_PAGE_SIZE   (data holds the PA / PFN<<offset)
//
// Test matrix:
//   1. LLC DoA + STLB resident DoA entry, same PFN     → resident_doa++
//   2. LLC DoA + STLB resident DoA entry, different PFN → all zero
//   3. LLC DoA + STLB resident entry that was hit       → resident_alive++
//   4. LLC eviction is NOT DoA (block was hit)          → all zero
//   5. LLC DoA + page evicted from STLB (DoA)           → evicted_doa++
//   6. LLC DoA + page evicted from STLB (alive)         → evicted_alive++
//   7. Re-insertion into STLB clears the evict log entry
//      (page evicted DoA then re-inserted → live lookup wins)

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

// MRC that maps virtual page numbers to physical addresses.
// Key: VPN = pkt.address >> LOG2_PAGE_SIZE.  Default returned if not found.
class vpn_mapped_MRC : public MemoryRequestConsumer, public champsim::operable
{
  std::deque<PACKET> packets;
  std::map<uint64_t, uint64_t> vpn_to_pa;
  uint64_t default_pa;
public:
  vpn_mapped_MRC(std::map<uint64_t, uint64_t> m, uint64_t dflt)
    : MemoryRequestConsumer(), champsim::operable(1), vpn_to_pa(std::move(m)), default_pa(dflt) {}

  void operate() override {
    for (auto& pkt : packets) {
      auto it = vpn_to_pa.find(pkt.address >> LOG2_PAGE_SIZE);
      pkt.data = (it != vpn_to_pa.end()) ? it->second : default_pa;
      for (auto ret : pkt.to_return) ret->return_data(pkt);
    }
    packets.clear();
  }
  bool add_rq(const PACKET& p) override { packets.push_back(p); return true; }
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
      THEN("evict_doa_stlb_resident_alive == 1 (page found in live STLB but had hits)") {
        CHECK(llc.sim_stats.back().evict_doa_stlb_resident_alive == 1);
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

// ── Scenario 5 ───────────────────────────────────────────────────────────────
// Setup: vpn_mapped_MRC maps VPN 0xAAAA → PFN 1, VPN 0xBBBB → PFN 2.
// After filling 0xBBBB the STLB evicts 0xAAAA (PFN 1) and holds only PFN 2.
// A subsequent LLC DoA eviction on PFN 1 must fall through to the evict log.

SCENARIO("LLC DoA block whose page was evicted from STLB as DoA → evicted_doa") {
  GIVEN("A cpu0_STLB (1 set × 1 way) and an LLC (1 set × 1 way)") {
    vpn_mapped_MRC mock_ll_stlb({{0xAAAA, PFN1_PA}, {0xBBBB, PFN2_PA}}, PFN1_PA);
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

    WHEN("PFN 1 is evicted DoA from the STLB, then LLC evicts a DoA block on PFN 1") {
      // Fill STLB with VPN 0xAAAA → PFN 1 (never hit → DoA on eviction).
      mock_ul_stlb.issue(make_load(0xAAAA000, ip, id));
      run(stlb_elems);

      // Evict VPN 0xAAAA (PFN 1) by filling VPN 0xBBBB → PFN 2.
      // STLB is 1-way so the old entry is displaced; PFN 1 goes into evict log as DoA.
      mock_ul_stlb.issue(make_load(0xBBBB000, ip, id));
      run(stlb_elems);

      // LLC: fill PFN 1 block, then evict it as DoA.
      mock_ul_llc.issue(make_load(LLC_ADDR_A, ip, id));
      run(llc_elems);
      mock_ul_llc.issue(make_load(LLC_ADDR_B, ip, id));
      run(llc_elems);

      THEN("evict_doa_stlb_evicted_doa == 1 (page was DoA when evicted from STLB)") {
        CHECK(llc.sim_stats.back().evict_doa_stlb_evicted_doa == 1);
      }
      THEN("evict_doa_on_doa_stlb_page == 0 (page not in live STLB at LLC eviction)") {
        CHECK(llc.sim_stats.back().evict_doa_on_doa_stlb_page == 0);
      }
      THEN("evict_doa == 1 (sanity)") {
        CHECK(llc.sim_stats.back().evict_doa == 1);
      }
    }
  }
}

// ── Scenario 6 ───────────────────────────────────────────────────────────────

SCENARIO("LLC DoA block whose page was evicted from STLB as alive → evicted_alive") {
  GIVEN("A cpu0_STLB (1 set × 1 way) and an LLC (1 set × 1 way)") {
    vpn_mapped_MRC mock_ll_stlb({{0xAAAA, PFN1_PA}, {0xBBBB, PFN2_PA}}, PFN1_PA);
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

    WHEN("PFN 1 is hit in STLB before eviction (not DoA), then LLC evicts a DoA block on PFN 1") {
      // Fill STLB with VPN 0xAAAA → PFN 1, then hit it (hit_count = 1 → alive).
      mock_ul_stlb.issue(make_load(0xAAAA000, ip, id));
      run(stlb_elems);
      mock_ul_stlb.issue(make_load(0xAAAA000, ip, id));
      run(stlb_elems);

      // Evict VPN 0xAAAA (PFN 1) as alive by filling VPN 0xBBBB → PFN 2.
      mock_ul_stlb.issue(make_load(0xBBBB000, ip, id));
      run(stlb_elems);

      // LLC: fill PFN 1 block, then evict it as DoA.
      mock_ul_llc.issue(make_load(LLC_ADDR_A, ip, id));
      run(llc_elems);
      mock_ul_llc.issue(make_load(LLC_ADDR_B, ip, id));
      run(llc_elems);

      THEN("evict_doa_stlb_evicted_alive == 1 (page had hits when evicted from STLB)") {
        CHECK(llc.sim_stats.back().evict_doa_stlb_evicted_alive == 1);
      }
      THEN("evict_doa_stlb_evicted_doa == 0") {
        CHECK(llc.sim_stats.back().evict_doa_stlb_evicted_doa == 0);
      }
      THEN("evict_doa_on_doa_stlb_page == 0 (page not in live STLB)") {
        CHECK(llc.sim_stats.back().evict_doa_on_doa_stlb_page == 0);
      }
      THEN("evict_doa == 1 (sanity)") {
        CHECK(llc.sim_stats.back().evict_doa == 1);
      }
    }
  }
}

// ── Scenario 7 ───────────────────────────────────────────────────────────────

SCENARIO("Re-inserting a page into the STLB removes it from the evict log") {
  GIVEN("A cpu0_STLB (1 set × 1 way) and an LLC (1 set × 1 way)") {
    vpn_mapped_MRC mock_ll_stlb({{0xAAAA, PFN1_PA}, {0xBBBB, PFN2_PA}}, PFN1_PA);
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

    WHEN("PFN 1 evicted DoA from STLB, re-inserted (live again), then LLC evicts DoA on PFN 1") {
      // Fill VPN 0xAAAA → PFN 1 (DoA). Evict it with VPN 0xBBBB → PFN 2.
      mock_ul_stlb.issue(make_load(0xAAAA000, ip, id));
      run(stlb_elems);
      mock_ul_stlb.issue(make_load(0xBBBB000, ip, id));
      run(stlb_elems);
      // PFN 1 is now in evict log as DoA. STLB holds PFN 2.

      // Re-insert PFN 1: miss on 0xAAAA000 fills it again (evict log entry removed).
      mock_ul_stlb.issue(make_load(0xAAAA000, ip, id));
      run(stlb_elems);
      // STLB holds PFN 1 (DoA, never hit since re-insert). Evict log for PFN 1 cleared.

      // LLC: fill PFN 1 block, then evict it as DoA.
      mock_ul_llc.issue(make_load(LLC_ADDR_A, ip, id));
      run(llc_elems);
      mock_ul_llc.issue(make_load(LLC_ADDR_B, ip, id));
      run(llc_elems);

      THEN("evict_doa_on_doa_stlb_page == 1 (live STLB wins; entry is DoA after re-insert)") {
        CHECK(llc.sim_stats.back().evict_doa_on_doa_stlb_page == 1);
      }
      THEN("evict_doa_stlb_evicted_doa == 0 (evict log cleared on re-insertion)") {
        CHECK(llc.sim_stats.back().evict_doa_stlb_evicted_doa == 0);
      }
      THEN("evict_doa == 1 (sanity)") {
        CHECK(llc.sim_stats.back().evict_doa == 1);
      }
    }
  }
}
