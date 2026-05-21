/*
 *    Copyright 2023 The ChampSim Contributors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#ifndef CACHE_H
#define CACHE_H

#include <array>
#include <bitset>
#include <cassert>
#include <climits>
#include <deque>
#include <functional>
#include <list>
#include <map>
#include <string>
#include <string_view>
#include <vector>

#include "champsim.h"
#include "champsim_constants.h"
#include "memory_class.h"
#include "operable.h"

// Cumulative per-PC liveness event counts.  Only ever incremented, never
// reset, so they record total event frequencies across the whole simulation.
struct pc_liveness_entry {
  uint64_t doa          = 0;
  uint64_t mostly_dead  = 0;
  uint64_t mostly_alive = 0;
  uint64_t total() const { return doa + mostly_dead + mostly_alive; }
};

// Merged per-PC liveness counts from both STLB (page-level) and LLC (block-level).
// STLB columns are updated on every STLB eviction when dppred=1.
// LLC columns are updated on every LLC eviction when cbpred=1, regardless of victim.dp.
// Stored as an inline static so both STLB and LLC CACHE instances share it.
struct merged_pc_entry {
  uint64_t stlb_doa         = 0;
  uint64_t stlb_mostly_dead  = 0;
  uint64_t stlb_mostly_alive = 0;
  uint64_t llc_doa          = 0;
  uint64_t llc_mostly_dead   = 0;
  uint64_t llc_mostly_alive  = 0;
  uint64_t stlb_total() const { return stlb_doa + stlb_mostly_dead + stlb_mostly_alive; }
  uint64_t llc_total()  const { return llc_doa  + llc_mostly_dead  + llc_mostly_alive;  }
};

struct cache_stats {
  std::string name;
  // prefetch stats
  uint64_t pf_requested = 0;
  uint64_t pf_issued = 0;
  uint64_t pf_useful = 0;
  uint64_t pf_useless = 0;
  uint64_t pf_fill = 0;

  std::array<std::array<uint64_t, NUM_CPUS>, NUM_TYPES> hits = {};
  std::array<std::array<uint64_t, NUM_CPUS>, NUM_TYPES> misses = {};

  uint64_t total_miss_latency = 0;

  uint64_t llt_bypasses = 0;
  uint64_t llc_bypasses = 0;
  uint64_t pfq_probes    = 0;   // LLC fills checked against PFQ by PFN (CBPRED=1 only)
  uint64_t pfq_hits      = 0;   // subset of pfq_probes whose PFN was in PFQ
  uint64_t pc_pfq_probes = 0;   // LLC fills checked against PC-PFQ by PC (CBPRED=1 only)
  uint64_t pc_pfq_hits   = 0;   // subset of pc_pfq_probes whose PC was in PC-PFQ

  // ── Bypass regret (LLC and STLB only; only populated when bypass is active) ──
  // bypass_incorrect – bypassed line demanded while it would still have been resident
  // bypass_correct   – bypassed line aged out (≥ NUM_WAY set-accesses) without being demanded
  // bypass_shadow_overflow – shadow was full; entry dropped unresolved
  uint64_t bypass_incorrect          = 0;
  uint64_t bypass_correct         = 0;
  uint64_t bypass_shadow_overflow = 0;

  // Weighted-bhist DoA eviction breakdown (CBPRED_WEIGHTED=1 only).
  // normal_inserts:      class=mostly_alive at insert → bhist.doa += W_NORMAL
  // pessimistic_inserts: class=doa/mostly_dead at insert → bhist.doa += W_LOW
  uint64_t cbpred_doa_normal_inserts      = 0;
  uint64_t cbpred_doa_pessimistic_inserts = 0;

  uint64_t phist_lookups          = 0, phist_hits          = 0;  // dpPred prediction queries (DPPRED=1 only)
  uint64_t bhist_lookups          = 0, bhist_hits          = 0;  // cbPred addr-indexed queries (CBPRED=1 only)
  uint64_t pc_bhist_lookups       = 0, pc_bhist_hits       = 0;  // cbPred PC-indexed queries   (CBPRED_IDX=pc)
  uint64_t pc_addr_bhist_lookups  = 0, pc_addr_bhist_hits  = 0;  // cbPred combined queries     (CBPRED_IDX=pc_addr|pc_or_addr)
  uint64_t merged_pc_hist_lookups = 0, merged_pc_hist_hits = 0;  // cbPred merged queries       (CBPRED_IDX=merged)
  uint64_t st_lookups             = 0, st_hits             = 0;  // shadow-table lookups (DPPRED=1 only)

  // ── Block/page liveness stats (LLC and STLB only) ─────────────────────────
  // Recorded at every valid eviction during the ROI.
  //   DoA        – hit_count == 0 (never referenced after insertion)
  //   Mostly-dead  – hit_count > 0 but dead_tail > residence/2
  //   Mostly-alive – dead_tail ≤ residence/2
  uint64_t evict_total        = 0;
  uint64_t evict_doa          = 0;
  uint64_t evict_mostly_dead  = 0;
  uint64_t evict_mostly_alive = 0;

  // Suspicious-condition counters (not errors, but worth investigating if nonzero).
  //   zero_residence – block installed and evicted in the same cycle;
  //                    dead_tail is always 0 here so classification is still
  //                    valid, but the measurement carries no useful timing info.
  uint64_t evict_zero_residence = 0;

  // LLC DoA blocks cross-referenced against STLB state.  Denominator is
  // evict_doa for all four.  Only meaningful for LLC.
  //
  // Lookup order: live STLB first; if not found, stlb_evict_log (pages
  // recently evicted from the STLB that have not yet been re-inserted).
  // "alive" means the STLB entry had at least one hit (hit_count > 0).
  uint64_t evict_doa_on_doa_stlb_page    = 0; // live STLB, page was DoA
  uint64_t evict_doa_stlb_resident_alive = 0; // live STLB, page had hits
  uint64_t evict_doa_stlb_evicted_doa    = 0; // evict log, was DoA on STLB eviction
  uint64_t evict_doa_stlb_evicted_alive  = 0; // evict log, had hits on STLB eviction
  // uncovered = evict_doa − sum of the four above (derived at print time)

  // Hit-count distribution at eviction.
  // Bin i = evicted with exactly i hits; bin HIT_HIST_BINS-1 = that many or more.
  static constexpr std::size_t HIT_HIST_BINS = 9; // bins 0..7 + "8+"
  std::array<uint64_t, HIT_HIST_BINS> evict_hit_hist = {};

  // Per-PC liveness event counts (cumulative, never reset).
  std::map<uint64_t, pc_liveness_entry> llt_pc_stats; // STLB: [ip] → counts
  std::map<uint64_t, pc_liveness_entry> llc_pc_stats; // LLC:  [ip] → counts
};

struct cache_queue_stats {
  uint64_t RQ_ACCESS = 0;
  uint64_t RQ_MERGED = 0;
  uint64_t RQ_FULL = 0;
  uint64_t RQ_TO_CACHE = 0;
  uint64_t PQ_ACCESS = 0;
  uint64_t PQ_MERGED = 0;
  uint64_t PQ_FULL = 0;
  uint64_t PQ_TO_CACHE = 0;
  uint64_t WQ_ACCESS = 0;
  uint64_t WQ_MERGED = 0;
  uint64_t WQ_FULL = 0;
  uint64_t WQ_TO_CACHE = 0;
  uint64_t WQ_FORWARD = 0;
  uint64_t PTWQ_ACCESS = 0;
  uint64_t PTWQ_MERGED = 0;
  uint64_t PTWQ_FULL = 0;
  uint64_t PTWQ_TO_CACHE = 0;
};

class CACHE : public champsim::operable, public MemoryRequestConsumer, public MemoryRequestProducer
{
  enum [[deprecated(
      "Prefetchers may not specify arbitrary fill levels. Use CACHE::prefetch_line(pf_addr, fill_this_level, prefetch_metadata) instead.")]] FILL_LEVEL{
      FILL_L1 = 1, FILL_L2 = 2, FILL_LLC = 4, FILL_DRC = 8, FILL_DRAM = 16};

  bool try_hit(const PACKET& handle_pkt);
  bool handle_fill(const PACKET& fill_mshr);
  bool handle_miss(const PACKET& handle_pkt);
  bool handle_write(const PACKET& handle_pkt);

  struct BLOCK {
    bool valid = false;
    bool prefetch = false;
    bool dirty = false;
    bool accessed = false; // set on hit; read and cleared on eviction
    bool dp = false;       // dead-page bit: set on LLC fill when the block's PFN is in the PFQ;
                           // gates accessed tracking and bHIST updates (cbPred only)
    uint8_t insert_liveness_class = 2; // liveness_class at insertion time (2 = mostly_alive default);
                                       // used by cbpred_weighted to scale bhist evidence

    uint64_t address = 0;
    uint64_t v_address = 0;
    uint64_t data = 0;
    uint64_t ip = 0; // PC that caused the miss that filled this block

    uint32_t pf_metadata = 0;

    // ── Liveness tracking (LLC and STLB; all blocks, not just dp) ───────────
    uint64_t insert_cycle   = 0; // current_cycle at insertion
    uint64_t last_hit_cycle = 0; // current_cycle at most recent hit (== insert_cycle if never hit)
    uint32_t hit_count      = 0; // demand hits while resident (uint32_t: no artificial cap)
  };
  using set_type = std::vector<BLOCK>;

  std::pair<set_type::iterator, set_type::iterator> get_set_span(uint64_t address);
  std::pair<set_type::const_iterator, set_type::const_iterator> get_set_span(uint64_t address) const;
  std::size_t get_set_index(uint64_t address) const;

  // ── dpPred-cbPred predictor ──────────────────────────────────────────────

  // Liveness classification produced by classify_liveness() and shared
  // between record_eviction_liveness() and update_eviction_counters().
  enum class liveness_class { doa, mostly_dead, mostly_alive };

  // History-table entry.  The two counters have independent update rules:
  //   doa          – incremented on DoA eviction; reset when the accessed bit
  //                  is set at eviction (i.e. on mostly-dead or mostly-alive
  //                  eviction, both of which imply at least one hit).
  //                  Gates dppred_bypass / cbpred_bypass: bypass when doa
  //                  exceeds pconf_thd / bconf_thd.
  //   mostly_dead  – incremented on mostly-dead eviction, reset on mostly-alive
  //                  eviction; unchanged on DoA.
  // The two counters never both increment on the same eviction, but a DoA
  // eviction leaves mostly_dead untouched (it neither confirms nor disproves
  // that the block was mostly-dead on a prior eviction).
  // needs_mid_insertion() returns true when either doa or mostly_dead is >= mid_thd.
  struct hist_entry {
    uint64_t doa         = 0;
    uint64_t mostly_dead = 0;
    uint64_t last_access = 0;  // recency timestamp for LRU eviction (full-key mode only)
    uint64_t freq        = 0;  // access frequency for LFU eviction (full-key mode only)
    uint64_t full_addr   = 0;  // original PC (phist) or block address (bhist) before set/tag split
  };

  // Inner key for phist_full.  pc_tag stores the high bits of the PC after
  // stripping the set-index bits (addr_tag(pc, phist_sets)); vpn is unsplit.
  struct phist_key_t {
    uint64_t pc_tag, vpn;
    bool operator<(const phist_key_t& o) const { if (pc_tag != o.pc_tag) return pc_tag < o.pc_tag; return vpn < o.vpn; }
    bool operator==(const phist_key_t& o) const { return pc_tag == o.pc_tag && vpn == o.vpn; }
  };


  // Shared physical-frame queue: dpPred fills it; cbPred reads it.
  // pfq     — PFN-only entries; cbPred matches by physical page (existing design).
  // pc_pfq  — (PC, PFN) pairs; cbPred can match by PC, PFN, or both.
  // Both queues are populated simultaneously on every dpPred bypass and share pfq_cap.
  inline static std::deque<uint64_t>                       pfq{};
  inline static std::deque<std::pair<uint64_t, uint64_t>>  pc_pfq{};  // (PC, PFN)
  inline static uint64_t pfq_cap = 8;

  // Shadow table entry: records the context of a bypassed fill so that
  // a subsequent demand on the same VPN can be identified as a misprediction.
  struct shadow_entry_t {
    uint64_t vpn;          // virtual page number of the bypassed block
    uint64_t pc;           // instruction PC that triggered the bypass
    uint64_t translation;  // physical translation data (PFN + flags)
  };

  // Per-instance state
  bool dppred = false;
  bool cbpred = false;
  bool     cbpred_weighted     = false; // weight bhist updates by insertion quality (CBPRED_WEIGHTED=1)
  bool     cbpred_no_pfq       = false; // bypass on bhist confidence alone; skip PFQ membership check (CBPRED_NO_PFQ=1)
  // Adaptive PFQ gate: exponential moving average of the PFQ hit rate.
  // α = 1/pfq_adaptive_window; the gate requires PFQ membership when the
  // EMA exceeds pfq_adaptive_thd (%).  0 = gate always on (no adaptation).
  uint64_t pfq_adaptive_window = 10000; // EMA memory length in probes; 0 = gate always on
  uint64_t pfq_adaptive_thd    = 30;    // hit-rate % threshold; gate on iff ema >= thd
  double   pfq_hit_rate_ema    = 1.0;   // running EMA; starts at 1 (gate on) and adapts
  bool     cbpred_trace        = false;        // log bypass threshold crossings to stderr (CBPRED_TRACE=1)
  uint64_t cbpred_trace_addr   = UINT64_MAX;   // full per-block trace for one address (CBPRED_TRACE_ADDR=<hex>)
  bool     tracing_cbpred()    const { return cbpred_trace || cbpred_trace_addr != UINT64_MAX; }
  uint64_t cbpred_w_normal     = 2;     // bhist.doa increment for DoA eviction after normal insertion
  uint64_t cbpred_w_low        = 1;     // bhist.doa increment for DoA eviction after pessimistic insertion
  uint64_t cbpred_w_mispredict = 2;     // bhist.doa decrement per detected bypass misprediction
  uint64_t pconf_thd = 6; // phist confidence threshold
  uint64_t bconf_thd = 6; // bhist confidence threshold
  // Bypass-debt adaptive gate: accumulated mispredict penalty raises the effective bypass threshold.
  // Correct bypasses drain the debt; mispredictions grow it.  When BYPASS_DEBT_SCALE > 0:
  //   effective_bconf = bconf_thd + bypass_debt / bypass_debt_scale
  // This makes the predictor self-suppressing when its recent accuracy is poor.
  uint64_t bypass_debt       = 0;  // running mispredict penalty (resets on warmup end)
  uint64_t bypass_debt_cap   = 0;  // max debt = max threshold increase (0 = disabled)
  uint64_t bypass_debt_scale = 0;  // 0 = feature disabled; 1+ = divisor for debt → threshold
  uint64_t mid_thd        = 1;     // min DoA-or-mostly-dead evictions before mid-insertion triggers
  bool     mid_promote_on_hit = false; // promote mid-inserted blocks to MRU on hit (MID_PROMOTE=1)
  uint64_t st_size    = 2;    // shadow table capacity
  uint64_t phist_sets = 1;     // number of sets in phist_full (1 = fully associative)
  uint64_t phist_ways = 1024;  // ways per set in phist_full; total capacity = sets × ways
  uint64_t bhist_sets = 1;     // number of sets in bhist_full (1 = fully associative)
  uint64_t bhist_ways = 4096;  // ways per set in bhist_full; total capacity = sets × ways
  uint64_t lru_clock  = 0;    // monotonic counter for LRU timestamps

  // Replacement policy for the full-key history tables (no effect in hashed mode).
  // Controlled by the REPL_POL env var ("lru" (default) | "lfu").
  enum class repl_pol_t : uint8_t { lru, lfu };
  repl_pol_t repl_pol = repl_pol_t::lru;

  // Set by cpu0_STLB at initialize(); used by LLC to scan for DoA page correlations.
  inline static const CACHE* stlb_ptr = nullptr;

  // PFN → was_doa: populated when an STLB entry is evicted; entries removed
  // when the page is re-inserted into the STLB.  Gives LLC the ability to
  // cross-reference against pages that have already left the STLB.
  inline static std::map<uint64_t, bool> stlb_evict_log{};

  std::map<uint64_t, std::map<uint64_t,    hist_entry>> phist;      // [vpn_hash][pc_hash] → entry  (hashed)
  std::map<uint64_t, std::map<phist_key_t, hist_entry>> phist_full; // [pc_set][{pc_tag,vpn}] → entry (full-key)
  std::deque<shadow_entry_t> shadow_table;                          // recently bypassed {vpn, pc, translation}
  std::map<uint64_t, hist_entry> bhist;                             // [block_hash] → entry           (hashed)
  std::map<uint64_t, std::map<uint64_t, hist_entry>> bhist_full;   // [addr_set][addr_tag] → entry   (full-key)
  std::map<uint64_t, hist_entry> pc_bhist;                                      // [PC] → entry
  std::map<std::pair<uint64_t,uint64_t>, hist_entry> pc_addr_bhist;            // [{PC, block_addr}] → entry

  // (declared public below — needs to be read by the plain_printer)

  // Selects the indexing key for cbPred's history table and PFQ match.
  // Controlled by the CBPRED_IDX env var.
  //   addr        — existing: bhist keyed by block addr,  PFQ matched by PFN
  //   pc          — new:      pc_bhist keyed by PC,       pc_pfq matched by PC
  //   pc_addr     — combined: pc_addr_bhist keyed by (PC,addr),  strict AND: both PFN and PC must hit
  //   pc_or_addr  — combined: pc_addr_bhist keyed by (PC,addr), permissive OR: PFN or PC suffices
  //   merged      — new:      merged_pc_hist[PC].llc_doa, PFQ matched by PFN (same gate as addr)
  enum class cbpred_idx_t : uint8_t { addr, pc, pc_addr, pc_or_addr, merged };
  cbpred_idx_t cbpred_idx = cbpred_idx_t::addr;

  // Selects which history signal drives needs_mid_insertion() / predict_liveness().
  // Controlled by the MID_KEY env var (0 = addr, 1 = pc; default 0).
  enum class mid_key_t : uint8_t { addr = 0, pc = 1 };
  mid_key_t mid_key = mid_key_t::addr;

  // When true, predict_liveness() / needs_mid_insertion() also require PFQ
  // membership before returning a non-alive prediction.  The queue checked
  // follows mid_key: addr → pfq (PFN-based), pc → pc_pfq (PC-based).
  // Controlled by the MID_PFQ_GATE env var (0 = off (default), 1 = on).
  bool mid_pfq_gate = false;

  // Unbounded insertion-policy tables: always updated at eviction regardless
  // of predictor state.  No hashing — no collisions.  Budget is intentionally
  // unrealistic for now.  LLC and STLB keep separate tables because they track
  // different address granularities (cache lines vs pages) and have independent
  // liveness behaviour.
  //   llc_mid_hist_addr  : LLC, keyed by block address (full_addr >> OFFSET_BITS)
  //   llc_mid_hist_pc    : LLC, keyed by the PC that triggered the access
  //   stlb_mid_hist_addr : STLB, keyed by VPN (full_addr >> OFFSET_BITS)
  //   stlb_mid_hist_pc   : STLB, keyed by the PC that triggered the access
  // needs_mid_insertion() consults only the table selected by mid_key.
  std::map<uint64_t, hist_entry> llc_mid_hist_addr;
  std::map<uint64_t, hist_entry> llc_mid_hist_pc;
  std::map<uint64_t, hist_entry> stlb_mid_hist_addr;
  std::map<uint64_t, hist_entry> stlb_mid_hist_pc;

  static constexpr unsigned VPN_BITS = 4;
  static constexpr unsigned PC_BITS  = 6;
  static constexpr unsigned BHT_BITS = 12;

  bool phist_hash = true;   // PHIST_HASH=0 disables XOR-folding, uses full VPN+PC as key
  bool bhist_hash = true;   // BHIST_HASH=0 disables XOR-folding, uses full block address as key

  uint64_t fold_xor(uint64_t val, unsigned bits) const;
  bool        phist_entry_exists(uint64_t pc, uint64_t vpn) const;
  hist_entry& get_phist_entry(uint64_t pc, uint64_t vpn);     // dispatches to phist or phist_full
  void        phist_clear_vpn(uint64_t vpn);                  // invalidate all entries for a VPN
  bool        bhist_entry_exists(uint64_t block_addr) const;
  hist_entry& get_bhist_entry(uint64_t block_addr);           // dispatches to bhist or bhist_full
  void load_predictor_settings();                               // reads env vars to configure dpPred/cbPred at construction
  bool dppred_shadow_lookup(const PACKET& handle_pkt);          // true → shadow hit: history reset, data served, entry re-inserted into STLB, PTW skipped
  bool dppred_bypass(const PACKET& fill_mshr);                  // true → skip STLB fill
  bool cbpred_bypass(const PACKET& fill_mshr);                  // true → skip LLC fill
  liveness_class classify_liveness(const BLOCK& victim) const;  // compute liveness class + run invariant asserts
  void update_eviction_counters(const BLOCK& victim, liveness_class lv); // update phist/bhist counters
  void record_eviction_liveness(const BLOCK& victim, liveness_class lv); // record aggregate liveness stats
  void record_pc_liveness(const BLOCK& victim, liveness_class lv);       // accumulate per-PC liveness event counts
  bool needs_mid_insertion(uint64_t full_addr, uint64_t ip) const;        // true → insert/refresh at set midpoint
  liveness_class predict_liveness(uint64_t full_addr, uint64_t ip) const; // 3-way insertion prediction for ipv_live
  void trace_cbpred_event(std::string_view tag, uint64_t block_addr,
                          uint64_t doa_before, uint64_t doa_after,
                          uint8_t insert_class = 2) const;               // stderr trace (CBPRED_TRACE=1 only)

public:
  // Merged per-PC history shared across STLB and LLC instances.
  // STLB writes stlb_* columns; LLC writes llc_* columns (neither dp-gated).
  // Public so the plain_printer can read it without a friend declaration.
  inline static std::map<uint64_t, merged_pc_entry> merged_pc_hist{};

  struct NonTranslatingQueues : public champsim::operable {
    std::deque<PACKET> RQ, PQ, WQ, PTWQ;
    const std::size_t RQ_SIZE, PQ_SIZE, WQ_SIZE, PTWQ_SIZE;
    const uint64_t HIT_LATENCY;
    const unsigned OFFSET_BITS;
    const bool match_offset_bits;

    using stats_type = cache_queue_stats;

    std::vector<stats_type> sim_stats, roi_stats;

    NonTranslatingQueues(double freq_scale, std::size_t rq_size, std::size_t pq_size, std::size_t wq_size, std::size_t ptwq_size, uint64_t hit_latency,
                         unsigned offset_bits, bool match_offset)
        : champsim::operable(freq_scale), RQ_SIZE(rq_size), PQ_SIZE(pq_size), WQ_SIZE(wq_size), PTWQ_SIZE(ptwq_size), HIT_LATENCY(hit_latency),
          OFFSET_BITS(offset_bits), match_offset_bits(match_offset)
    {
    }
    void operate() override;

    template <typename R>
    bool do_add_queue(R& queue, std::size_t queue_size, const PACKET& packet);

    bool add_rq(const PACKET& packet);
    bool add_wq(const PACKET& packet);
    bool add_pq(const PACKET& packet);
    bool add_ptwq(const PACKET& packet);

    virtual bool is_ready(const PACKET& pkt) const;

    bool rq_has_ready() const;
    bool wq_has_ready() const;
    bool pq_has_ready() const;
    bool ptwq_has_ready() const;

    void begin_phase() override;
    void end_phase(unsigned cpu) override;

  private:
    void check_collision();
  };

  struct TranslatingQueues : public NonTranslatingQueues, public MemoryRequestProducer {
    void operate() override final;

    void issue_translation();
    void detect_misses();

    template <typename R>
    void do_issue_translation(R& queue);

    template <typename R>
    void do_detect_misses(R& queue);

    virtual bool is_ready(const PACKET& pkt) const override final;

    void return_data(const PACKET& packet) override final;

    using NonTranslatingQueues::NonTranslatingQueues;
  };

  uint32_t cpu = 0;
  const std::string NAME;
  const uint32_t NUM_SET, NUM_WAY, MSHR_SIZE;
  const uint32_t FILL_LATENCY;
  const unsigned OFFSET_BITS;
  set_type block{NUM_SET * NUM_WAY};
  const long int MAX_TAG, MAX_FILL;
  const bool prefetch_as_load;
  const bool match_offset_bits;
  const bool virtual_prefetch;
  bool ever_seen_data = false;
  const unsigned pref_activate_mask = (1 << static_cast<int>(LOAD)) | (1 << static_cast<int>(PREFETCH));

  using stats_type = cache_stats;

  std::vector<stats_type> sim_stats{}, roi_stats{};

  NonTranslatingQueues& queues;
  std::deque<PACKET> MSHR;
  std::deque<PACKET> inflight_writes;

  // functions
  bool add_rq(const PACKET& packet) override final;
  bool add_wq(const PACKET& packet) override final;
  bool add_pq(const PACKET& packet) override final;
  bool add_ptwq(const PACKET& packet) override final;

  void return_data(const PACKET& packet) override final;
  void operate() override final;

  void initialize() override final;
  void begin_phase() override final;
  void end_phase(unsigned cpu) override final;

  std::size_t get_occupancy(uint8_t queue_type, uint64_t address) override final;
  std::size_t get_size(uint8_t queue_type, uint64_t address) override final;

  [[deprecated("Use get_set_index() instead.")]] uint64_t get_set(uint64_t address) const;
  [[deprecated("This function should not be used to access the blocks directly.")]] uint64_t get_way(uint64_t address, uint64_t set) const;

  uint64_t invalidate_entry(uint64_t inval_addr);
  int prefetch_line(uint64_t pf_addr, bool fill_this_level, uint32_t prefetch_metadata);

  [[deprecated("Use CACHE::prefetch_line(pf_addr, fill_this_level, prefetch_metadata) instead.")]] int
  prefetch_line(uint64_t ip, uint64_t base_addr, uint64_t pf_addr, bool fill_this_level, uint32_t prefetch_metadata);

  bool should_activate_prefetcher(const PACKET& pkt) const;

  void print_deadlock() override;

#include "cache_modules.inc"

  // ── Bypass regret tracking (LLC and STLB only) ───────────────────────────────
  // Per-set fill counter (incremented each time a valid line is evicted by a new
  // fill).  Used to decide whether a bypassed line would still be resident:
  // > NUM_WAY fills since bypass → line would have been evicted (correct bypass).
  // Per-set shadow: FIFO of at most 2×NUM_WAY bypass records; front = oldest.
  struct BypassShadowEntry {
    uint64_t addr_tag;           // address >> OFFSET_BITS
    uint64_t fills_at_bypass; // bypass_per_set_fills[set] at bypass time
  };
  std::vector<uint64_t>                      bypass_per_set_fills;
  std::vector<std::deque<BypassShadowEntry>> bypass_shadow;  // per-set FIFO, oldest = front

  const std::bitset<NUM_REPLACEMENT_MODULES> repl_type;
  const std::bitset<NUM_PREFETCH_MODULES> pref_type;

  ~CACHE() { if (stlb_ptr == this) { stlb_ptr = nullptr; stlb_evict_log.clear(); } }

  // constructor
  CACHE(std::string v1, double freq_scale, uint32_t v2, uint32_t v3, uint32_t v8, uint32_t fill_lat, long int max_tag, long int max_fill, unsigned offset_bits,
        bool pref_load, bool wq_full_addr, bool va_pref, unsigned pref_mask, NonTranslatingQueues& queue_set, MemoryRequestConsumer* ll,
        std::bitset<NUM_PREFETCH_MODULES> pref, std::bitset<NUM_REPLACEMENT_MODULES> repl)
      : champsim::operable(freq_scale), MemoryRequestProducer(ll), NAME(v1), NUM_SET(v2), NUM_WAY(v3), MSHR_SIZE(v8), FILL_LATENCY(fill_lat),
        OFFSET_BITS(offset_bits), MAX_TAG(max_tag), MAX_FILL(max_fill), prefetch_as_load(pref_load), match_offset_bits(wq_full_addr), virtual_prefetch(va_pref),
        pref_activate_mask(pref_mask), queues(queue_set),
        bypass_per_set_fills(v2, 0), bypass_shadow(v2),
        repl_type(repl), pref_type(pref)
  {
    load_predictor_settings();
  }
};

#endif
