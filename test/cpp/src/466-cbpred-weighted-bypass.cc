// Tests for the weighted cbPred bypass state machine (CBPRED_WEIGHTED=1).
//
// With W_NORMAL=2, W_LOW=1, BCONF_THD=2:
//   1st DoA eviction (after normal/mostly-alive insert):     bhist.doa += 2
//   2nd DoA eviction (after pessimistic/doa-class insert):   bhist.doa += 1 = 3
//   3rd fill attempt: bhist.doa=3 > bconf_thd=2 → bypass fires.
//
// Unweighted cbpred (CBPRED_WEIGHTED=0) would need 3 evictions at +1 each
// (reaching doa=3) for the same bconf_thd.  The weighted variant reaches
// threshold one eviction sooner because normal-insert DoA is stronger evidence.
//
// PFQ is populated by a cpu0_STLB with DPPRED=1, PCONF_THD=0:
//   Fill VA_A  → STLB inserts (phist.doa=0).
//   Fill VA_B  → evicts VA_A as DoA → phist[VA_A].doa=1.
//   Fill VA_A  → dppred_bypass fires (doa=1 > PCONF_THD=0) → PFQ ← {PFN=0xAA}.
//
// PFN 0xAA is chosen to avoid collision with PFQ state left by earlier tests
// (test 461 uses do_nothing_MRC, which returns data ≈ 0x11111112 → PFN ≈ 0x11111;
//  test 465 uses fixed PFNs 1 and 2).

#include <cstdlib>
#include <deque>
#include <limits>

#include <catch.hpp>
#include "mocks.hpp"
#include "cache.h"
#include "champsim_constants.h"

namespace {

// MRC that always returns pkt.data = fixed_pa, regardless of pkt.address.
// Gives the STLB a deterministic physical-address translation so dppred_bypass
// adds a known PFN to the shared static PFQ.
class fixed_data_MRC : public MemoryRequestConsumer, public champsim::operable
{
  std::deque<PACKET> pending;
  const uint64_t pa;
public:
  explicit fixed_data_MRC(uint64_t pa_)
    : MemoryRequestConsumer(), champsim::operable(1), pa(pa_) {}

  void operate() override {
    for (auto& pkt : pending)
      for (auto ret : pkt.to_return)
        ret->return_data(pkt);
    pending.clear();
  }
  bool add_rq(const PACKET& p) override { auto c = p; c.data = pa; pending.push_back(c); return true; }
  bool add_wq(const PACKET&)   override { return true; }
  bool add_pq(const PACKET&)   override { return true; }
  bool add_ptwq(const PACKET&) override { return true; }
  std::size_t get_occupancy(uint8_t, uint64_t) override { return pending.size(); }
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

// Target PFN = 0xAA.  LLC_ADDR and LLC_ADDR_2 are on different pages so each
// new fill evicts the other in a 1-set/1-way LLC.  Only LLC_ADDR is on PFN 0xAA
// so only its evictions gate bhist updates (via the dp flag).
constexpr uint64_t TARGET_PA  = 0xAA000ULL; // PFN = TARGET_PA >> LOG2_PAGE_SIZE = 0xAA
constexpr uint64_t LLC_ADDR   = 0xAA000ULL; // PFN 0xAA — matches TARGET_PA
constexpr uint64_t LLC_ADDR_2 = 0xBB000ULL; // PFN 0xBB — NOT in PFQ → dp=false
constexpr uint64_t STLB_VA_A  = 0xAA000ULL;
constexpr uint64_t STLB_VA_B  = 0xCC000ULL;

} // namespace

// ── Scenario 1: weighted bypass fires earlier than unweighted ─────────────────

SCENARIO("cbpred_weighted: bypass fires after 1 normal-insert + 1 pessimistic-insert DoA eviction") {
  ::setenv("DPPRED",          "1", 1);
  ::setenv("PCONF_THD",       "0", 1);
  ::setenv("CBPRED",          "1", 1);
  ::setenv("CBPRED_WEIGHTED", "1", 1);
  ::setenv("CBPRED_W_NORMAL", "2", 1);
  ::setenv("CBPRED_W_LOW",    "1", 1);
  ::setenv("BCONF_THD",       "2", 1);
  ::setenv("MID_THD",         "1", 1);
  ::setenv("MID_KEY",         "0", 1);

  GIVEN("A cpu0_STLB and a 1-set/1-way LLC") {
    constexpr uint64_t lat = 2;
    uint64_t id = 1;
    const uint64_t ip = 0xF00D;

    fixed_data_MRC mock_ll_stlb{TARGET_PA};
    CACHE::NonTranslatingQueues stlb_queues{1, 32, 32, 32, 0, lat, LOG2_BLOCK_SIZE, false};
    CACHE stlb{"cpu0_STLB", 1, 1, 1, 32, lat, 1, 1, 0, false, false, false,
               (1 << LOAD) | (1 << PREFETCH), stlb_queues, &mock_ll_stlb,
               CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul_stlb{&stlb};
    std::array<champsim::operable*, 4> stlb_elems{{&mock_ll_stlb, &stlb_queues, &stlb, &mock_ul_stlb}};
    stlb.initialize();  stlb.warmup = false;  stlb_queues.warmup = false;
    stlb.begin_phase(); stlb_queues.begin_phase();

    do_nothing_MRC mock_ll_llc;
    CACHE::NonTranslatingQueues llc_queues{1, 32, 32, 32, 0, lat, LOG2_BLOCK_SIZE, false};
    CACHE llc{"LLC", 1, 1, 1, 32, lat, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), llc_queues, &mock_ll_llc,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul_llc{&llc};
    std::array<champsim::operable*, 4> llc_elems{{&mock_ll_llc, &llc_queues, &llc, &mock_ul_llc}};
    llc.initialize();  llc.warmup = false;  llc_queues.warmup = false;
    llc.begin_phase(); llc_queues.begin_phase();

    // ── STLB phase: populate PFQ with PFN=0xAA ─────────────────────────────
    // Fill VA_A: empty STLB, inserted with phist.doa=0.
    mock_ul_stlb.issue(make_load(STLB_VA_A, ip, id)); run(stlb_elems);
    // Fill VA_B: evicts VA_A as DoA → phist[VA_A].doa = 1.
    mock_ul_stlb.issue(make_load(STLB_VA_B, ip, id)); run(stlb_elems);
    // Fill VA_A: dppred_bypass fires (doa=1 > PCONF_THD=0) → PFQ ← {0xAA}.
    mock_ul_stlb.issue(make_load(STLB_VA_A, ip, id)); run(stlb_elems);

    WHEN("Round 1: LLC_ADDR fills (class=mostly_alive) then evicts DoA — bhist.doa becomes 2") {
      // LLC empty: LLC_ADDR fills.  PFN=0xAA in PFQ → dp=true.
      // predict_liveness: llc_mid_hist empty → mostly_alive → insert_liveness_class=2.
      mock_ul_llc.issue(make_load(LLC_ADDR,   ip, id)); run(llc_elems);
      // LLC_ADDR_2 evicts LLC_ADDR (DoA).  dp=true, class=mostly_alive → conservative=false.
      // bhist.doa += W_NORMAL=2  →  bhist.doa = 2.
      mock_ul_llc.issue(make_load(LLC_ADDR_2, ip, id)); run(llc_elems);

      THEN("No bypass yet (bhist.doa=2 is not > bconf_thd=2)") {
        CHECK(llc.sim_stats.back().llc_bypasses == 0);
      }

      WHEN("Round 2: LLC_ADDR refills (class=doa/pessimistic) then evicts DoA — bhist.doa becomes 3") {
        // LLC_ADDR fills.  dp=true.
        // predict_liveness: llc_mid_hist[LLC_ADDR>>6].doa=1 >= MID_THD=1 → doa → class=0.
        mock_ul_llc.issue(make_load(LLC_ADDR,   ip, id)); run(llc_elems);
        // LLC_ADDR_2 evicts LLC_ADDR (DoA).  dp=true, class=doa → conservative=true.
        // bhist.doa += W_LOW=1  →  bhist.doa = 3.
        mock_ul_llc.issue(make_load(LLC_ADDR_2, ip, id)); run(llc_elems);

        THEN("Still no bypass (bhist.doa=3 > bconf_thd=2 is checked on the NEXT fill)") {
          CHECK(llc.sim_stats.back().llc_bypasses == 0);
        }

        WHEN("Round 3: fill attempt for LLC_ADDR triggers cbpred_bypass") {
          // cbpred_bypass: PFN=0xAA in PFQ, bhist.doa=3 > bconf_thd=2 → BYPASS.
          mock_ul_llc.issue(make_load(LLC_ADDR, ip, id)); run(llc_elems);

          THEN("Bypass fired; PFQ chain, STLB phase, and per-class counters all confirmed") {
            // STLB phase: dppred_bypass must have fired to populate PFQ.
            CHECK(stlb.sim_stats.back().llt_bypasses >= 1);
            // LLC cbpred: PFQ must have been consulted and hit.
            CHECK(llc.sim_stats.back().pfq_hits > 0);
            // Weighted accumulation: exactly 1 normal-insert DoA (+W_NORMAL)
            // and 1 pessimistic-insert DoA (+W_LOW).
            CHECK(llc.sim_stats.back().cbpred_doa_normal_inserts      == 1);
            CHECK(llc.sim_stats.back().cbpred_doa_pessimistic_inserts  == 1);
            // One bypass in total.
            CHECK(llc.sim_stats.back().llc_bypasses == 1);
          }
        }
      }
    }
  }

  ::unsetenv("DPPRED");
  ::unsetenv("PCONF_THD");
  ::unsetenv("CBPRED");
  ::unsetenv("CBPRED_WEIGHTED");
  ::unsetenv("CBPRED_W_NORMAL");
  ::unsetenv("CBPRED_W_LOW");
  ::unsetenv("BCONF_THD");
  ::unsetenv("MID_THD");
  ::unsetenv("MID_KEY");
}

// ── Scenario 2: misprediction de-escalates bhist and prevents re-bypass ───────

SCENARIO("cbpred_weighted: misprediction de-escalates bhist and prevents immediate re-bypass") {
  ::setenv("DPPRED",          "1", 1);
  ::setenv("PCONF_THD",       "0", 1);
  ::setenv("CBPRED",          "1", 1);
  ::setenv("CBPRED_WEIGHTED", "1", 1);
  ::setenv("CBPRED_W_NORMAL", "2", 1);
  ::setenv("CBPRED_W_LOW",    "1", 1);
  ::setenv("CBPRED_W_MISPREDICT", "2", 1);
  ::setenv("BCONF_THD",       "2", 1);
  ::setenv("MID_THD",         "1", 1);
  ::setenv("MID_KEY",         "0", 1);

  GIVEN("A cpu0_STLB and a 1-set/1-way LLC (same setup as scenario 1)") {
    constexpr uint64_t lat = 2;
    uint64_t id = 1;
    const uint64_t ip = 0xF00D;

    fixed_data_MRC mock_ll_stlb{TARGET_PA};
    CACHE::NonTranslatingQueues stlb_queues{1, 32, 32, 32, 0, lat, LOG2_BLOCK_SIZE, false};
    CACHE stlb{"cpu0_STLB", 1, 1, 1, 32, lat, 1, 1, 0, false, false, false,
               (1 << LOAD) | (1 << PREFETCH), stlb_queues, &mock_ll_stlb,
               CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul_stlb{&stlb};
    std::array<champsim::operable*, 4> stlb_elems{{&mock_ll_stlb, &stlb_queues, &stlb, &mock_ul_stlb}};
    stlb.initialize();  stlb.warmup = false;  stlb_queues.warmup = false;
    stlb.begin_phase(); stlb_queues.begin_phase();

    do_nothing_MRC mock_ll_llc;
    CACHE::NonTranslatingQueues llc_queues{1, 32, 32, 32, 0, lat, LOG2_BLOCK_SIZE, false};
    CACHE llc{"LLC", 1, 1, 1, 32, lat, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), llc_queues, &mock_ll_llc,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul_llc{&llc};
    std::array<champsim::operable*, 4> llc_elems{{&mock_ll_llc, &llc_queues, &llc, &mock_ul_llc}};
    llc.initialize();  llc.warmup = false;  llc_queues.warmup = false;
    llc.begin_phase(); llc_queues.begin_phase();

    // STLB phase: populate PFQ with PFN=0xAA.
    mock_ul_stlb.issue(make_load(STLB_VA_A, ip, id)); run(stlb_elems);
    mock_ul_stlb.issue(make_load(STLB_VA_B, ip, id)); run(stlb_elems);
    mock_ul_stlb.issue(make_load(STLB_VA_A, ip, id)); run(stlb_elems);

    // LLC escalation: 1 normal-insert DoA + 1 pessimistic-insert DoA → bhist.doa=3.
    mock_ul_llc.issue(make_load(LLC_ADDR,   ip, id)); run(llc_elems);
    mock_ul_llc.issue(make_load(LLC_ADDR_2, ip, id)); run(llc_elems);
    mock_ul_llc.issue(make_load(LLC_ADDR,   ip, id)); run(llc_elems);
    mock_ul_llc.issue(make_load(LLC_ADDR_2, ip, id)); run(llc_elems);

    // Bypass fires for LLC_ADDR (bhist.doa=3 > 2).
    // bypass_shadow ← {LLC_ADDR>>OFFSET_BITS, fills_at_bypass=3}.
    mock_ul_llc.issue(make_load(LLC_ADDR,   ip, id)); run(llc_elems);

    WHEN("The bypassed address is immediately demanded again") {
      // handle_miss: shadow entry still fresh (0 fills since bypass < NUM_WAY=1).
      // → misprediction detected: bhist.doa -= W_MISPREDICT=2 → bhist.doa=1.
      // handle_fill (triggered by do_nothing_MRC): cbpred_bypass: 1 ≤ bconf_thd=2 → no bypass.
      mock_ul_llc.issue(make_load(LLC_ADDR, ip, id)); run(llc_elems);

      THEN("One misprediction recorded and the refill is not bypassed") {
        CHECK(llc.sim_stats.back().bypass_incorrect == 1);
        CHECK(llc.sim_stats.back().llc_bypasses     == 1); // no new bypass
      }
    }
  }

  ::unsetenv("DPPRED");
  ::unsetenv("PCONF_THD");
  ::unsetenv("CBPRED");
  ::unsetenv("CBPRED_WEIGHTED");
  ::unsetenv("CBPRED_W_NORMAL");
  ::unsetenv("CBPRED_W_LOW");
  ::unsetenv("CBPRED_W_MISPREDICT");
  ::unsetenv("BCONF_THD");
  ::unsetenv("MID_THD");
  ::unsetenv("MID_KEY");
}

// ── Scenario 3: bypass_correct fires when shadow expires without re-demand ────
//
// With NUM_WAY=1 the shadow entry expires when bypass_per_set_fills exceeds
// fills_at_bypass + NUM_WAY (strictly, > NUM_WAY).  Two filler fills after the
// bypass push the counter to fills_at_bypass+2 > 1=NUM_WAY, expiring the entry
// and incrementing bypass_correct.  A subsequent demand for the bypassed address
// is then treated as a plain miss (bypass_incorrect stays zero).

SCENARIO("cbpred_weighted: bypass shadow expires correctly as bypass_correct when block never re-demanded") {
  ::setenv("DPPRED",          "1", 1);
  ::setenv("PCONF_THD",       "0", 1);
  ::setenv("CBPRED",          "1", 1);
  ::setenv("CBPRED_WEIGHTED", "1", 1);
  ::setenv("CBPRED_W_NORMAL", "2", 1);
  ::setenv("CBPRED_W_LOW",    "1", 1);
  ::setenv("BCONF_THD",       "2", 1);
  ::setenv("MID_THD",         "1", 1);
  ::setenv("MID_KEY",         "0", 1);

  GIVEN("A cpu0_STLB and a 1-set/1-way LLC (same setup as scenarios 1 and 2)") {
    constexpr uint64_t lat = 2;
    uint64_t id = 1;
    const uint64_t ip = 0xF00D;

    fixed_data_MRC mock_ll_stlb{TARGET_PA};
    CACHE::NonTranslatingQueues stlb_queues{1, 32, 32, 32, 0, lat, LOG2_BLOCK_SIZE, false};
    CACHE stlb{"cpu0_STLB", 1, 1, 1, 32, lat, 1, 1, 0, false, false, false,
               (1 << LOAD) | (1 << PREFETCH), stlb_queues, &mock_ll_stlb,
               CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul_stlb{&stlb};
    std::array<champsim::operable*, 4> stlb_elems{{&mock_ll_stlb, &stlb_queues, &stlb, &mock_ul_stlb}};
    stlb.initialize();  stlb.warmup = false;  stlb_queues.warmup = false;
    stlb.begin_phase(); stlb_queues.begin_phase();

    do_nothing_MRC mock_ll_llc;
    CACHE::NonTranslatingQueues llc_queues{1, 32, 32, 32, 0, lat, LOG2_BLOCK_SIZE, false};
    CACHE llc{"LLC", 1, 1, 1, 32, lat, 1, 1, 0, false, false, false,
              (1 << LOAD) | (1 << PREFETCH), llc_queues, &mock_ll_llc,
              CACHE::pprefetcherDno, CACHE::rreplacementDlru};
    to_rq_MRP mock_ul_llc{&llc};
    std::array<champsim::operable*, 4> llc_elems{{&mock_ll_llc, &llc_queues, &llc, &mock_ul_llc}};
    llc.initialize();  llc.warmup = false;  llc_queues.warmup = false;
    llc.begin_phase(); llc_queues.begin_phase();

    // STLB phase: populate PFQ.
    mock_ul_stlb.issue(make_load(STLB_VA_A, ip, id)); run(stlb_elems);
    mock_ul_stlb.issue(make_load(STLB_VA_B, ip, id)); run(stlb_elems);
    mock_ul_stlb.issue(make_load(STLB_VA_A, ip, id)); run(stlb_elems);

    // LLC escalation: 1 normal-insert + 1 pessimistic-insert DoA → bhist.doa=3.
    mock_ul_llc.issue(make_load(LLC_ADDR,   ip, id)); run(llc_elems);
    mock_ul_llc.issue(make_load(LLC_ADDR_2, ip, id)); run(llc_elems);
    mock_ul_llc.issue(make_load(LLC_ADDR,   ip, id)); run(llc_elems);
    mock_ul_llc.issue(make_load(LLC_ADDR_2, ip, id)); run(llc_elems);

    // Bypass fires for LLC_ADDR → shadow = {LLC_ADDR_tag, fills_at_bypass=3}.
    // Cache now holds LLC_ADDR_2.  bypass_per_set_fills = 3.
    mock_ul_llc.issue(make_load(LLC_ADDR, ip, id)); run(llc_elems);

    WHEN("Two filler fills push bypass_per_set_fills past fills_at_bypass + NUM_WAY") {
      // Filler address 1: evicts LLC_ADDR_2 → bypass_per_set_fills=4; 4-3=1, 1>1? NO.
      constexpr uint64_t FILLER_A = 0xEE000ULL;
      constexpr uint64_t FILLER_B = 0xFF000ULL;
      mock_ul_llc.issue(make_load(FILLER_A, ip, id)); run(llc_elems);
      // Filler address 2: evicts FILLER_A → bypass_per_set_fills=5; 5-3=2, 2>1? YES → expires.
      mock_ul_llc.issue(make_load(FILLER_B, ip, id)); run(llc_elems);

      THEN("Shadow expired as bypass_correct; re-demand is not a misprediction") {
        CHECK(llc.sim_stats.back().bypass_correct   == 1);
        CHECK(llc.sim_stats.back().bypass_incorrect == 0);
        CHECK(llc.sim_stats.back().llc_bypasses     == 1); // no re-bypass either
      }
    }
  }

  ::unsetenv("DPPRED");
  ::unsetenv("PCONF_THD");
  ::unsetenv("CBPRED");
  ::unsetenv("CBPRED_WEIGHTED");
  ::unsetenv("CBPRED_W_NORMAL");
  ::unsetenv("CBPRED_W_LOW");
  ::unsetenv("BCONF_THD");
  ::unsetenv("MID_THD");
  ::unsetenv("MID_KEY");
}
