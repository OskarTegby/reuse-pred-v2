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

#include "cache.h"
#include "hist_lru.h"

#include <algorithm>
#include <cassert>
#include <climits>
#include <cstring>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <numeric>
#include <string_view>

#include "champsim.h"
#include "champsim_constants.h"
#include "instruction.h"
#include "util.h"

// ──────────────────────────────────────────────
// dpPred-cbPred helpers
// ──────────────────────────────────────────────

uint64_t CACHE::fold_xor(uint64_t val, unsigned bits) const
{
  uint64_t result = 0;
  const uint64_t mask = (1ULL << bits) - 1;
  for (int i = 0; i < 32 / static_cast<int>(bits); ++i, val >>= bits)
    result ^= (val & mask);
  return result;
}


bool CACHE::phist_entry_exists(uint64_t pc, uint64_t vpn) const
{
  if (phist_hash) {
    const auto outer = phist.find(fold_xor(vpn, VPN_BITS));
    return outer != phist.end() && outer->second.count(fold_xor(pc, PC_BITS));
  }
  const auto outer = phist_full.find(addr_set(pc, phist_sets));
  return outer != phist_full.end() && outer->second.count(phist_key_t{addr_tag(pc, phist_sets), vpn});
}

CACHE::hist_entry& CACHE::get_phist_entry(uint64_t pc, uint64_t vpn)
{
  if (phist_hash)
    return phist[fold_xor(vpn, VPN_BITS)][fold_xor(pc, PC_BITS)];
  const uint64_t set = addr_set(pc, phist_sets);
  const uint64_t tag = addr_tag(pc, phist_sets);
  assert(addr_reconstruct(set, tag, phist_sets) == pc);
  const phist_key_t key{tag, vpn};
  hist_entry& e = (repl_pol == repl_pol_t::lfu)
    ? lfu_access(phist_full[set], key, phist_ways, lru_clock)
    : lru_access(phist_full[set], key, phist_ways, lru_clock);
  e.full_addr = pc;
  return e;
}

void CACHE::phist_clear_vpn(uint64_t vpn)
{
  if (phist_hash) {
    phist[fold_xor(vpn, VPN_BITS)].clear();
  } else {
    for (auto& [set_key, inner] : phist_full) {
      for (auto it = inner.begin(); it != inner.end(); )
        if (it->first.vpn == vpn) it = inner.erase(it);
        else                      ++it;
    }
  }
}

bool CACHE::bhist_entry_exists(uint64_t block_addr) const
{
  if (bhist_hash) return bhist.count(fold_xor(block_addr, BHT_BITS));
  const auto outer = bhist_full.find(addr_set(block_addr, bhist_sets));
  return outer != bhist_full.end() && outer->second.count(addr_tag(block_addr, bhist_sets));
}

CACHE::hist_entry& CACHE::get_bhist_entry(uint64_t block_addr)
{
  if (bhist_hash)
    return bhist[fold_xor(block_addr, BHT_BITS)];
  const uint64_t set = addr_set(block_addr, bhist_sets);
  const uint64_t tag = addr_tag(block_addr, bhist_sets);
  assert(addr_reconstruct(set, tag, bhist_sets) == block_addr);
  hist_entry& e = (repl_pol == repl_pol_t::lfu)
    ? lfu_access(bhist_full[set], tag, bhist_ways, lru_clock)
    : lru_access(bhist_full[set], tag, bhist_ways, lru_clock);
  e.full_addr = block_addr;
  return e;
}

// On a shadow table hit: reset the VPN's history row, serve the stored
// translation to all requesters, and re-insert the entry into the STLB via
// a synthetic handle_fill call (PTW is skipped entirely).
// dppred_bypass will see a cleared phist counter and allow the insertion.
bool CACHE::dppred_shadow_lookup(const PACKET& handle_pkt)
{
  const auto vpn = handle_pkt.address >> OFFSET_BITS;
  sim_stats.back().st_lookups++;
  auto it = std::find_if(shadow_table.begin(), shadow_table.end(), [vpn](const auto& e) { return e.first == vpn; });
  if (it == shadow_table.end())
    return false;
  sim_stats.back().st_hits++;

  phist_clear_vpn(vpn);
  const auto stored_data = it->second;
  shadow_table.erase(it);

  // Serve the translation to all waiting requesters.
  auto copy{handle_pkt};
  copy.data = stored_data;
  for (auto ret : copy.to_return)
    ret->return_data(copy);

  // Re-insert into the STLB. Clear to_return so handle_fill does not
  // double-serve the data it already dispatched above.
  PACKET fill_pkt = handle_pkt;
  fill_pkt.data = stored_data;
  fill_pkt.to_return = {};
  handle_fill(fill_pkt);

  return true;
}

// Returns true and records the bypass when dpPred predicts this VPN is dead.
// Only called when the set is full (otherwise there is nothing to bypass).
bool CACHE::dppred_bypass(const PACKET& fill_mshr)
{
  const auto vpn = fill_mshr.address >> OFFSET_BITS;
  const auto pc  = fill_mshr.ip;
  sim_stats.back().phist_lookups++;
  if (phist_entry_exists(pc, vpn)) sim_stats.back().phist_hits++;
  if (get_phist_entry(pc, vpn).doa <= pconf_thd)
    return false;

  // Push physical frame into the shared queue for cbPred (FIFO)
  if (pfq.size() >= pfq_cap)
    pfq.pop_front();
  pfq.push_back(fill_mshr.data >> LOG2_PAGE_SIZE);

  // Remember the bypassed (VPN, translation) for re-insertion on re-access (FIFO)
  if (shadow_table.size() >= st_size)
    shadow_table.pop_front();
  shadow_table.push_back({fill_mshr.address >> OFFSET_BITS, fill_mshr.data});

  sim_stats.back().llt_bypasses++;
  return true;
}

// Returns true when cbPred predicts this cache block is dead
// (its page was previously bypassed by dpPred and its block counter is high).
bool CACHE::cbpred_bypass(const PACKET& fill_mshr)
{
  const auto pfn        = fill_mshr.address >> LOG2_PAGE_SIZE;
  const auto block_addr = fill_mshr.address >> OFFSET_BITS;
  const bool in_pfq     = std::find(pfq.begin(), pfq.end(), pfn) != pfq.end();

  sim_stats.back().pfq_probes++;
  if (in_pfq)
    sim_stats.back().pfq_hits++;

  // Adaptive PFQ gate: update the sliding window and re-evaluate whether to
  // require PFQ membership once every pfq_adaptive_window probes.
  if (pfq_adaptive_window > 0) {
    pfq_win_probes++;
    if (in_pfq) pfq_win_hits++;
    if (pfq_win_probes >= pfq_adaptive_window) {
      const uint64_t hit_pct = (pfq_win_hits * 100) / pfq_win_probes;
      pfq_gate_on    = (hit_pct >= pfq_adaptive_thd);
      pfq_win_probes = 0;
      pfq_win_hits   = 0;
    }
  }

  // Determine whether PFQ membership is required for this fill.
  // Priority: cbpred_no_pfq (static off) > adaptive gate > always-on default.
  const bool require_pfq = !cbpred_no_pfq && (pfq_adaptive_window == 0 || pfq_gate_on);

  // Count bhist lookups whenever the gate passes (PFQ hit, or gate inactive).
  if (in_pfq || !require_pfq) {
    sim_stats.back().bhist_lookups++;
    if (bhist_entry_exists(block_addr)) sim_stats.back().bhist_hits++;
  }
  // Adaptive threshold: raise bconf proportionally to accumulated mispredict debt.
  const uint64_t effective_bconf = bconf_thd
      + (bypass_debt_scale > 0 ? bypass_debt / bypass_debt_scale : 0);
  // Gate: skip fill when PFQ membership passes (or is not required) and bconf is high.
  if ((!in_pfq && require_pfq) || get_bhist_entry(block_addr).doa <= effective_bconf)
    return false;

  assert(get_bhist_entry(block_addr).doa > effective_bconf); // bypass must fire above threshold
  if (tracing_cbpred()) {
    const uint64_t d = get_bhist_entry(block_addr).doa;
    trace_cbpred_event("bypass", block_addr, d, d);
  }
  sim_stats.back().llc_bypasses++;
  return true;
}

// ── Liveness classification ───────────────────────────────────────────────────
//
// Definitions (all in simulation cycles):
//   residence  = eviction_cycle − insert_cycle
//   dead_tail  = eviction_cycle − last_hit_cycle
//   DoA        : hit_count == 0  (never referenced after insertion)
//   Mostly-dead: hit_count > 0 AND dead_tail > residence / 2
//   Mostly-alive: otherwise (dead_tail ≤ residence / 2)
//
// Invariants asserted (violations indicate a simulator bug):
//   (A) last_hit_cycle >= insert_cycle      (last hit cannot predate insertion)
//   (B) current_cycle  >= insert_cycle      (time is monotonically increasing)
//   (C) current_cycle  >= last_hit_cycle    (same)
//   (D) dead_tail      <= residence         (arithmetic consequence of A-C;
//                                            also guards against unsigned underflow)
CACHE::liveness_class CACHE::classify_liveness(const BLOCK& victim) const
{
  assert(victim.last_hit_cycle >= victim.insert_cycle); // (A)
  assert(current_cycle >= victim.insert_cycle);         // (B)
  assert(current_cycle >= victim.last_hit_cycle);       // (C)

  const uint64_t residence = current_cycle - victim.insert_cycle;
  const uint64_t dead_tail = current_cycle - victim.last_hit_cycle;

  assert(dead_tail <= residence); // (D): unsigned underflow guard

  if (victim.hit_count == 0)
    return liveness_class::doa;

  // Use dead_tail > residence/2 rather than 2*dead_tail > residence to avoid
  // any theoretical uint64_t overflow on extraordinarily long-lived blocks.
  return (dead_tail > residence / 2) ? liveness_class::mostly_dead
                                     : liveness_class::mostly_alive;
}

// Records liveness stats for the evicted block.  No-op for caches other than
// the LLC and STLB.  Suspicious-condition (zero residence) is counted here.
void CACHE::record_eviction_liveness(const BLOCK& victim, liveness_class lv)
{
  if (NAME != "cpu0_STLB" && NAME != "LLC")
    return;

  auto& s = sim_stats.back();
  s.evict_total++;

  if (current_cycle == victim.insert_cycle)
    s.evict_zero_residence++;

  const std::size_t bin = std::min(static_cast<std::size_t>(victim.hit_count),
                                   cache_stats::HIT_HIST_BINS - 1);
  s.evict_hit_hist[bin]++;

  switch (lv) {
    case liveness_class::doa:          s.evict_doa++;          break;
    case liveness_class::mostly_dead:  s.evict_mostly_dead++;  break;
    case liveness_class::mostly_alive: s.evict_mostly_alive++; break;
  }

  // STLB: record this page's DoA status in the evict log so the LLC can
  // cross-reference it even after it leaves the STLB.
  if (NAME == "cpu0_STLB") {
    stlb_evict_log[victim.data >> LOG2_PAGE_SIZE] = (lv == liveness_class::doa);
  }

  // For LLC DoA blocks: check whether the evicted block's PFN has STLB info.
  // Coverage breakdown:
  //   live STLB, DoA    → evict_doa_on_doa_stlb_page    (true-positive)
  //   live STLB, alive  → evict_doa_stlb_resident_alive (true-negative)
  //   evict log, DoA    → evict_doa_stlb_evicted_doa    (extended true-positive)
  //   evict log, alive  → evict_doa_stlb_evicted_alive  (extended true-negative)
  //   not found         → uncovered (derived: evict_doa − the four above)
  //
  // Live-STLB check uses any_of over ALL entries for the PFN: a page is DoA
  // if any translation for it is DoA, which matches the upper-bound semantics
  // of "what could hardware learn from the STLB about this physical page?"
  // (find_if would stop at the first matching entry, giving arbitrary results
  // when multiple virtual aliases of the same PFN are resident simultaneously.)
  if (NAME == "LLC" && lv == liveness_class::doa && stlb_ptr != nullptr) {
    const uint64_t pfn = victim.address >> LOG2_PAGE_SIZE;

    const bool stlb_resident = std::any_of(
        stlb_ptr->block.begin(), stlb_ptr->block.end(),
        [pfn](const BLOCK& b) { return b.valid && (b.data >> LOG2_PAGE_SIZE) == pfn; });

    if (stlb_resident) {
      const bool stlb_doa = std::any_of(
          stlb_ptr->block.begin(), stlb_ptr->block.end(),
          [pfn](const BLOCK& b) {
            return b.valid && (b.data >> LOG2_PAGE_SIZE) == pfn && b.hit_count == 0;
          });
      if (stlb_doa) s.evict_doa_on_doa_stlb_page++;
      else          s.evict_doa_stlb_resident_alive++;
    } else {
      const auto it_log = stlb_evict_log.find(pfn);
      if (it_log != stlb_evict_log.end()) {
        if (it_log->second) s.evict_doa_stlb_evicted_doa++;
        else                s.evict_doa_stlb_evicted_alive++;
      }
      // else: uncovered — no STLB information available for this PFN
    }
  }
}

// Accumulates per-PC liveness event counts.  No-op for caches other than
// the LLC and STLB.  Unlike the history-table confidence counters in
// update_eviction_counters, these counters only ever increment — they are
// never reset — so they record total event frequencies across the whole run.
void CACHE::record_pc_liveness(const BLOCK& victim, liveness_class lv)
{
  if (NAME != "cpu0_STLB" && NAME != "LLC")
    return;

  auto& entry = (NAME == "cpu0_STLB") ? sim_stats.back().llt_pc_stats[victim.ip]
                                       : sim_stats.back().llc_pc_stats[victim.ip];
  switch (lv) {
    case liveness_class::doa:          entry.doa++;          break;
    case liveness_class::mostly_dead:  entry.mostly_dead++;  break;
    case liveness_class::mostly_alive: entry.mostly_alive++; break;
  }
}

// Updates phist (STLB) or bhist (LLC) when a valid entry is displaced.
//
// All history state is updated exclusively at eviction time — never earlier.
// This ensures that hits during the current residence do not affect the
// promotion or bypass decisions for the *next* miss of the same address.
//
// doa         – incremented on DoA; reset when the accessed bit is set at
//               eviction (equivalently: reset on mostly-dead or mostly-alive,
//               both of which imply at least one hit during residence).
//               A saturated doa counter gates the bypass decision.
// mostly_dead – incremented on mostly-dead; reset on mostly-alive.
//               Left unchanged on DoA: a DoA eviction is not a mostly-dead
//               eviction, but it does not disprove a prior mostly-dead pattern.
//
// The predictor-table updates below are gated on dppred/cbpred.
// The insertion-policy tables (llc_mid_hist_*, stlb_mid_hist_*) are always
// updated so that lru_mid maintains its history independently of whether the
// bypass predictors are enabled.
void CACHE::update_eviction_counters(const BLOCK& victim, liveness_class lv)
{
  auto update = [lv](hist_entry& e) {
    switch (lv) {
      case liveness_class::doa:
        e.doa++;
        // mostly_dead unchanged: DoA is not a mostly-dead eviction, but
        // it does not invalidate a previously observed mostly-dead pattern.
        break;
      case liveness_class::mostly_dead:
        e.mostly_dead++;
        e.doa = 0; // accessed bit was set: entry had at least one hit
        break;
      case liveness_class::mostly_alive:
        e.doa         = 0;
        e.mostly_dead = 0;
        break;
    }
  };

  // Predictor tables: phist unchanged; bhist uses weighted updates when cbpred_weighted.
  if (dppred && NAME == "cpu0_STLB") {
    update(get_phist_entry(victim.ip, victim.address >> OFFSET_BITS));
  } else if (cbpred && NAME == "LLC" && victim.dp) {
    if (cbpred_weighted) {
      // Normal-insert DoA is strong evidence; pessimistic-insert DoA is weak.
      // Smooth de-escalation: partial decrement instead of hard reset.
      assert(victim.insert_liveness_class <= 2); // must be a valid liveness_class value
      const bool conservative = victim.insert_liveness_class
                                != static_cast<uint8_t>(liveness_class::mostly_alive);
      auto& e = get_bhist_entry(victim.address >> OFFSET_BITS);
      const uint64_t doa_cap    = 2 * bconf_thd + cbpred_w_normal;
      const uint64_t doa_before = e.doa;
      switch (lv) {
        case liveness_class::doa: {
          const uint64_t delta = conservative ? cbpred_w_low : cbpred_w_normal;
          e.doa = std::min(e.doa + delta, doa_cap);
          assert(e.doa >= doa_before);  // DoA must not decrease confidence
          assert(e.doa <= doa_cap);     // must respect the saturation cap
          if (conservative) sim_stats.back().cbpred_doa_pessimistic_inserts++;
          else              sim_stats.back().cbpred_doa_normal_inserts++;
          break;
        }
        case liveness_class::mostly_dead:
          e.mostly_dead++;
          if (e.doa > 0) --e.doa;
          assert(e.doa <= doa_before); // partial de-escalation must not increase counter
          break;
        case liveness_class::mostly_alive:
          if (e.mostly_dead > 0) --e.mostly_dead;
          e.doa = (e.doa >= cbpred_w_normal) ? e.doa - cbpred_w_normal : 0;
          assert(e.doa <= doa_before); // de-escalation must not increase counter
          break;
      }
      if (tracing_cbpred())
        trace_cbpred_event("evict", victim.address >> OFFSET_BITS,
                           doa_before, e.doa, victim.insert_liveness_class);
    } else {
      update(get_bhist_entry(victim.address >> OFFSET_BITS));
    }
  }

  // Insertion-policy tables: always updated for LLC and STLB, no hashing.
  if (NAME == "LLC") {
    update(llc_mid_hist_addr[victim.address >> OFFSET_BITS]);
    update(llc_mid_hist_pc[victim.ip]);
  } else if (NAME == "cpu0_STLB") {
    update(stlb_mid_hist_addr[victim.address >> OFFSET_BITS]);
    update(stlb_mid_hist_pc[victim.ip]);
  }
}

// Emit a trace line when:
//   (a) the block matches cbpred_trace_addr (full per-block history), or
//   (b) CBPRED_TRACE=1 and doa crossed the bypass threshold (category transition).
// bypass/mispredict events are always logged when tracing is on, because they
// are category-changing by definition.
void CACHE::trace_cbpred_event(std::string_view tag, uint64_t block_addr,
                               uint64_t doa_before, uint64_t doa_after,
                               uint8_t insert_class) const
{
  const bool addr_match   = (block_addr == cbpred_trace_addr);
  const bool crossed_thd  = (doa_before <= bconf_thd) != (doa_after <= bconf_thd);
  const bool always_log   = (tag == "bypass" || tag == "mispredict");
  if (!addr_match && !crossed_thd && !always_log)
    return;

  static constexpr const char* names[] = {"doa", "mostly_dead", "mostly_alive"};
  std::clog << "[LLC cbpred] " << tag
            << " 0x" << std::hex << block_addr << std::dec
            << " class=" << (insert_class < 3 ? names[insert_class] : "?")
            << " doa=" << doa_before;
  if (doa_after != doa_before)
    std::clog << "->" << doa_after;
  std::clog << " (thd=" << bconf_thd << ")\n";
}

// Returns true when the entry's history shows its last eviction was DoA or
// mostly-dead, meaning it should be inserted at the set midpoint in lru_mid.
bool CACHE::needs_mid_insertion(uint64_t full_addr, uint64_t ip) const
{
  auto check = [this](const std::map<uint64_t, hist_entry>& tbl, uint64_t key) {
    const auto it = tbl.find(key);
    return it != tbl.end() && (it->second.doa >= mid_thd || it->second.mostly_dead >= mid_thd);
  };
  if (NAME == "LLC") {
    return (mid_key == mid_key_t::pc) ? check(llc_mid_hist_pc,    ip)
                                      : check(llc_mid_hist_addr,   full_addr >> OFFSET_BITS);
  } else if (NAME == "cpu0_STLB") {
    return (mid_key == mid_key_t::pc) ? check(stlb_mid_hist_pc,   ip)
                                      : check(stlb_mid_hist_addr,  full_addr >> OFFSET_BITS);
  }
  return false;
}

// 3-way liveness prediction for ipv_live: DoA → mostly_dead → mostly_alive.
// Uses the same history tables and mid_thd threshold as needs_mid_insertion(),
// but distinguishes DoA from mostly_dead instead of collapsing them.
// DoA takes priority: if both counters meet the threshold, returns doa.
CACHE::liveness_class CACHE::predict_liveness(uint64_t full_addr, uint64_t ip) const
{
  auto classify = [this](const std::map<uint64_t, hist_entry>& tbl, uint64_t key) -> liveness_class {
    const auto it = tbl.find(key);
    if (it == tbl.end())                      return liveness_class::mostly_alive;
    if (it->second.doa >= mid_thd)            return liveness_class::doa;
    if (it->second.mostly_dead >= mid_thd)    return liveness_class::mostly_dead;
    return liveness_class::mostly_alive;
  };
  if (NAME == "LLC")
    return (mid_key == mid_key_t::pc) ? classify(llc_mid_hist_pc,   ip)
                                      : classify(llc_mid_hist_addr,  full_addr >> OFFSET_BITS);
  if (NAME == "cpu0_STLB")
    return (mid_key == mid_key_t::pc) ? classify(stlb_mid_hist_pc,  ip)
                                      : classify(stlb_mid_hist_addr, full_addr >> OFFSET_BITS);
  return liveness_class::mostly_alive;
}

// Reads environment variables to enable dpPred/cbPred and tune their
// thresholds and table sizes. Called once from the CACHE constructor.
// Variables (all optional; defaults match the header initializers):
//   DPPRED=1           enable dead-page predictor on the STLB
//   CBPRED=1           enable dead-block predictor on the LLC
//   CBPRED_WEIGHTED=1  weight bhist updates by insertion quality (cbpred_weighted)
//   CBPRED_NO_PFQ=1           bypass on bhist confidence alone; skip PFQ check entirely (cbpred_no_pfq)
//   PFQ_ADAPTIVE_WINDOW=<n>  probes per hit-rate evaluation window; 0 = gate always on (pfq_adaptive_window)
//   PFQ_ADAPTIVE_THD=<n>     hit-rate % to keep PFQ gate active, 0–100 (default 10) (pfq_adaptive_thd)
//   CBPRED_TRACE=1          log bypass threshold crossings to stderr for all blocks
//   CBPRED_TRACE_ADDR=<hex> log all events for one specific block address (hex, no 0x prefix)
//   CBPRED_W_NORMAL=<n>     DoA-eviction bhist increment after normal insertion (default 2)
//   CBPRED_W_LOW=<n>        DoA-eviction bhist increment after pessimistic insertion (default 1)
//   CBPRED_W_MISPREDICT=<n> bhist.doa decrement per detected bypass misprediction (default 2)
//   PCONF_THD=<n>      dpPred confidence threshold (default 6)
//   BCONF_THD=<n>      cbPred confidence threshold (default 6)
//   MID_THD=<n>        min DoA-or-mostly-dead evictions before mid-insertion triggers (default 1)
//   MID_PROMOTE=<0|1>  promote mid-inserted blocks to MRU on hit (default 0 = no promotion)
//   ST_SIZE=<n>        shadow-table capacity (default 2)
//   PFQ_CAP=<n>        shared PFQ capacity (default 8)
//   PHIST_HASH=<0|1>   XOR-fold VPN+PC before phist lookup (default 1 = hash)
//   BHIST_HASH=<0|1>   XOR-fold block address before bhist lookup (default 1 = hash)
//   PHIST_SETS=<n>     number of sets in phist_full (default 1 = fully associative, full-key mode only)
//   PHIST_WAYS=<n>     ways per set in phist_full; total = sets × ways (default 64, full-key mode only)
//   BHIST_SETS=<n>     number of sets in bhist_full (default 1 = fully associative, full-key mode only)
//   BHIST_WAYS=<n>     ways per set in bhist_full; total = sets × ways (default 64, full-key mode only)
//   REPL_POL=<pol>     replacement policy for full-key tables: "lru" (default) | "lfu"
void CACHE::load_predictor_settings()
{
  auto getenv_uint64 = [](const char* var, uint64_t fallback) -> uint64_t {
    const char* val = std::getenv(var);
    return val ? static_cast<uint64_t>(std::stoull(val)) : fallback;
  };

  if (const char* v = std::getenv("DPPRED"); v && std::stoull(v))
    dppred = true;
  if (const char* v = std::getenv("CBPRED"); v && std::stoull(v))
    cbpred = true;
  cbpred_weighted     = (getenv_uint64("CBPRED_WEIGHTED",    0) != 0);
  cbpred_no_pfq        = (getenv_uint64("CBPRED_NO_PFQ",           0) != 0);
  pfq_adaptive_window  = getenv_uint64("PFQ_ADAPTIVE_WINDOW",      0);
  pfq_adaptive_thd     = getenv_uint64("PFQ_ADAPTIVE_THD",         10);
  pfq_win_probes       = 0;
  pfq_win_hits         = 0;
  pfq_gate_on          = true;
  cbpred_trace        = (getenv_uint64("CBPRED_TRACE",       0) != 0);
  if (const char* v = std::getenv("CBPRED_TRACE_ADDR"))
    cbpred_trace_addr = std::stoull(v, nullptr, 16);
  cbpred_w_normal     = getenv_uint64("CBPRED_W_NORMAL",     cbpred_w_normal);
  cbpred_w_low        = getenv_uint64("CBPRED_W_LOW",        cbpred_w_low);
  cbpred_w_mispredict = getenv_uint64("CBPRED_W_MISPREDICT", cbpred_w_mispredict);

  pconf_thd = getenv_uint64("PCONF_THD", pconf_thd);
  bconf_thd = getenv_uint64("BCONF_THD", bconf_thd);
  mid_thd   = getenv_uint64("MID_THD",   mid_thd);
  st_size   = getenv_uint64("ST_SIZE",   st_size);
  pfq_cap   = getenv_uint64("PFQ_CAP",   pfq_cap);
  bypass_debt_scale = getenv_uint64("BYPASS_DEBT_SCALE", 0);
  bypass_debt_cap   = getenv_uint64("BYPASS_DEBT_CAP",
                                    bypass_debt_scale > 0 ? bconf_thd : 0);
  bypass_debt       = 0;
  mid_key          = (getenv_uint64("MID_KEY",     0) == 1) ? mid_key_t::pc : mid_key_t::addr;
  mid_promote_on_hit = (getenv_uint64("MID_PROMOTE", 0) == 1);

  phist_hash = (getenv_uint64("PHIST_HASH", 1) != 0);
  bhist_hash = (getenv_uint64("BHIST_HASH", 1) != 0);
  phist_sets = getenv_uint64("PHIST_SETS", phist_sets);
  phist_ways = getenv_uint64("PHIST_WAYS", phist_ways);
  bhist_sets = getenv_uint64("BHIST_SETS", bhist_sets);
  bhist_ways = getenv_uint64("BHIST_WAYS", bhist_ways);
  if (const char* pol = std::getenv("REPL_POL"))
    repl_pol = (std::strcmp(pol, "lfu") == 0) ? repl_pol_t::lfu : repl_pol_t::lru;
}

bool CACHE::handle_fill(const PACKET& fill_mshr)
{
  cpu = fill_mshr.cpu;

  // find victim
  auto [set_begin, set_end] = get_set_span(fill_mshr.address);
  auto way = std::find_if_not(set_begin, set_end, [](auto x) { return x.valid; });
  if (way == set_end)
    way = std::next(set_begin, impl_find_victim(fill_mshr.cpu, fill_mshr.instr_id, get_set_index(fill_mshr.address), &*set_begin, fill_mshr.ip,
                                                fill_mshr.address, fill_mshr.type));

  // Predictor bypass: only fires when a valid entry would be displaced
  // (way->valid distinguishes eviction from filling a free slot).
  // On predictor bypass we do not redirect through the existing bypass code
  // path (way = set_end) because that path calls impl_update_replacement_state
  // with way_idx = NUM_WAY, which is out of bounds for LRU and semantically
  // wrong for any policy (no way was actually used). Instead we track the
  // bypass in a flag and handle it directly below.
  bool predictor_bypassed = false;
  if (way != set_end && way->valid) {
    const bool bypassed =
      fill_mshr.type != WRITE &&
      ((dppred && NAME == "cpu0_STLB" && dppred_bypass(fill_mshr)) ||
       (cbpred && NAME == "LLC"       && cbpred_bypass(fill_mshr)));

    if (bypassed) {
      predictor_bypassed = true;
      way = set_end;
      // Record in per-set bypass shadow for regret analysis.
      if (NAME == "cpu0_STLB" || NAME == "LLC") {
        const auto set_idx = get_set_index(fill_mshr.address);
        auto& q = bypass_shadow[set_idx];
        // Expire stale entries from the front (oldest inserted = earliest to expire).
        while (!q.empty() && bypass_per_set_fills[set_idx] - q.front().fills_at_bypass > NUM_WAY) {
          sim_stats.back().bypass_correct++;
          if (bypass_debt_scale > 0 && NAME == "LLC" && bypass_debt > 0) bypass_debt--;
          if (cbpred_trace_addr != UINT64_MAX && q.front().addr_tag == cbpred_trace_addr)
            std::clog << "[LLC cbpred] bypass_correct 0x" << std::hex << q.front().addr_tag << std::dec
                      << " (thd=" << bconf_thd << ")\n";
          q.pop_front();
        }
        // Cap at 2×NUM_WAY entries; drop oldest if full.
        if (q.size() >= 2 * NUM_WAY) {
          q.pop_front();
          sim_stats.back().bypass_shadow_overflow++;
        }
        q.push_back({fill_mshr.address >> OFFSET_BITS, bypass_per_set_fills[set_idx]});
      }
    } else {
      // Classify liveness once; share the result between stats recording and
      // history-table updates so the two stay in sync.
      // classify_liveness() runs the invariant asserts for all cache levels.
      // For caches other than LLC/STLB, hit_count is never incremented so the
      // result is always DoA, but record_eviction_liveness and
      // update_eviction_counters are both no-ops for those levels anyway.
      const auto lv = classify_liveness(*way);
      record_eviction_liveness(*way, lv);
      record_pc_liveness(*way, lv);
      update_eviction_counters(*way, lv);
    }
  }

  assert(set_begin <= way);
  assert(way <= set_end);
  const auto way_idx = static_cast<std::size_t>(std::distance(set_begin, way)); // cast protected by earlier assertion

  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "] " << __func__;
    std::cout << " instr_id: " << fill_mshr.instr_id << " address: " << std::hex << (fill_mshr.address >> OFFSET_BITS);
    std::cout << " full_addr: " << fill_mshr.address;
    std::cout << " full_v_addr: " << fill_mshr.v_address << std::dec;
    std::cout << " set: " << get_set_index(fill_mshr.address);
    std::cout << " way: " << way_idx;
    std::cout << " type: " << +fill_mshr.type;
    std::cout << " cycle_enqueued: " << fill_mshr.cycle_enqueued;
    std::cout << " cycle: " << current_cycle << std::endl;
  }

  bool success = true;
  auto metadata_thru = fill_mshr.pf_metadata;
  auto pkt_address = (virtual_prefetch ? fill_mshr.v_address : fill_mshr.address) & ~champsim::bitmask(match_offset_bits ? 0 : OFFSET_BITS);
  if (way != set_end) {
    if (way->valid && way->dirty) {
      PACKET writeback_packet;

      writeback_packet.cpu = fill_mshr.cpu;
      writeback_packet.address = way->address;
      writeback_packet.data = way->data;
      writeback_packet.instr_id = fill_mshr.instr_id;
      writeback_packet.ip = 0;
      writeback_packet.type = WRITE;
      writeback_packet.pf_metadata = way->pf_metadata;

      success = lower_level->add_wq(writeback_packet);
    }

    if (success) {
      // Track fills that evict a valid line: way->valid is still the old value here.
      if ((NAME == "cpu0_STLB" || NAME == "LLC") && way->valid) {
        const auto fill_set_idx = get_set_index(fill_mshr.address);
        bypass_per_set_fills[fill_set_idx]++;
        auto& fq = bypass_shadow[fill_set_idx];
        while (!fq.empty() && bypass_per_set_fills[fill_set_idx] - fq.front().fills_at_bypass > NUM_WAY) {
          sim_stats.back().bypass_correct++;
          if (bypass_debt_scale > 0 && NAME == "LLC" && bypass_debt > 0) bypass_debt--;
          if (cbpred_trace_addr != UINT64_MAX && fq.front().addr_tag == cbpred_trace_addr)
            std::clog << "[LLC cbpred] bypass_correct 0x" << std::hex << fq.front().addr_tag << std::dec
                      << " (thd=" << bconf_thd << ")\n";
          fq.pop_front();
        }
      }

      auto evicting_address = (ever_seen_data ? way->address : way->v_address) & ~champsim::bitmask(match_offset_bits ? 0 : OFFSET_BITS);

      if (way->prefetch)
        sim_stats.back().pf_useless++;

      if (fill_mshr.type == PREFETCH)
        sim_stats.back().pf_fill++;

      way->valid = true;
      way->prefetch = fill_mshr.prefetch_from_this;
      way->dirty = (fill_mshr.type == WRITE);
      way->accessed = false;
      way->dp = cbpred && NAME == "LLC" && std::find(pfq.begin(), pfq.end(), fill_mshr.address >> LOG2_PAGE_SIZE) != pfq.end();
      way->insert_liveness_class = (cbpred_weighted && NAME == "LLC")
          ? static_cast<uint8_t>(predict_liveness(fill_mshr.address, fill_mshr.ip))
          : static_cast<uint8_t>(liveness_class::mostly_alive);
      if (way->dp) {
        // Note: we do NOT assert doa <= bconf_thd here.  update_eviction_counters()
        // for the victim runs just before this fill, and with BHIST_HASH=1 the victim
        // and the filling block can alias to the same bhist bucket.  That aliased
        // increment can push doa above bconf_thd after the bypass decision was already
        // made correctly at check time.  The invariant is enforced at bypass-check time
        // (inside cbpred_bypass()), not here.
        if (tracing_cbpred()) {
          const uint64_t d = get_bhist_entry(fill_mshr.address >> OFFSET_BITS).doa;
          trace_cbpred_event("fill", fill_mshr.address >> OFFSET_BITS, d, d, way->insert_liveness_class);
        }
      }
      way->insert_cycle   = current_cycle;
      way->last_hit_cycle = current_cycle;
      way->hit_count      = 0;
      way->address = fill_mshr.address;
      way->v_address = fill_mshr.v_address;
      way->data = fill_mshr.data;
      way->ip = fill_mshr.ip;

      // STLB re-insertion: remove this PFN from the evict log so future LLC
      // DoA lookups use the live STLB entry instead of the stale log entry.
      if (NAME == "cpu0_STLB")
        stlb_evict_log.erase(fill_mshr.data >> LOG2_PAGE_SIZE);

      metadata_thru =
          impl_prefetcher_cache_fill(pkt_address, get_set_index(fill_mshr.address), way_idx, fill_mshr.type == PREFETCH, evicting_address, metadata_thru);
      impl_update_replacement_state(fill_mshr.cpu, get_set_index(fill_mshr.address), way_idx, fill_mshr.address, fill_mshr.ip, evicting_address, fill_mshr.type,
                                    false);

      way->pf_metadata = metadata_thru;
    }
  } else if (!predictor_bypassed) {
    assert(fill_mshr.type != WRITE);

    metadata_thru = impl_prefetcher_cache_fill(pkt_address, get_set_index(fill_mshr.address), way_idx, fill_mshr.type == PREFETCH, 0, metadata_thru);
    impl_update_replacement_state(fill_mshr.cpu, get_set_index(fill_mshr.address), way_idx, fill_mshr.address, fill_mshr.ip, 0, fill_mshr.type, false);
  }

  if (success) {
    // COLLECT STATS — skip for synthetic re-insertions (to_return is empty,
    // meaning this fill was not the result of a real miss reaching the lower level).
    if (!fill_mshr.to_return.empty())
      sim_stats.back().total_miss_latency += current_cycle - (fill_mshr.cycle_enqueued + 1);

    auto copy{fill_mshr};
    copy.pf_metadata = metadata_thru;
    for (auto ret : copy.to_return)
      ret->return_data(copy);
  }

  return success;
}

bool CACHE::try_hit(const PACKET& handle_pkt)
{
  cpu = handle_pkt.cpu;

  // access cache
  auto [set_begin, set_end] = get_set_span(handle_pkt.address);
  auto way = std::find_if(set_begin, set_end, eq_addr<BLOCK>(handle_pkt.address, OFFSET_BITS));
  const auto hit = (way != set_end);

  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "] " << __func__;
    std::cout << " instr_id: " << handle_pkt.instr_id << " address: " << std::hex << (handle_pkt.address >> OFFSET_BITS);
    std::cout << " full_addr: " << handle_pkt.address;
    std::cout << " full_v_addr: " << handle_pkt.v_address << std::dec;
    std::cout << " set: " << get_set_index(handle_pkt.address);
    std::cout << " way: " << std::distance(set_begin, way) << " (" << (hit ? "HIT" : "MISS") << ")";
    std::cout << " type: " << +handle_pkt.type;
    std::cout << " cycle: " << current_cycle << std::endl;
  }

  // update prefetcher on load instructions and prefetches from upper levels
  auto metadata_thru = handle_pkt.pf_metadata;
  if (should_activate_prefetcher(handle_pkt)) {
    uint64_t pf_base_addr = (virtual_prefetch ? handle_pkt.v_address : handle_pkt.address) & ~champsim::bitmask(match_offset_bits ? 0 : OFFSET_BITS);
    metadata_thru = impl_prefetcher_cache_operate(pf_base_addr, handle_pkt.ip, hit, handle_pkt.type, metadata_thru);
  }

  if (hit) {
    sim_stats.back().hits[handle_pkt.type][handle_pkt.cpu]++;

    // update replacement policy
    const auto way_idx = static_cast<std::size_t>(std::distance(set_begin, way)); // cast protected by earlier assertion
    impl_update_replacement_state(handle_pkt.cpu, get_set_index(handle_pkt.address), way_idx, way->address, handle_pkt.ip, 0, handle_pkt.type, true);

    auto copy{handle_pkt};
    copy.data = way->data;
    copy.pf_metadata = metadata_thru;
    for (auto ret : copy.to_return)
      ret->return_data(copy);

    way->dirty = (handle_pkt.type == WRITE);
    if (NAME == "cpu0_STLB")
      way->accessed = true;
    else if (NAME == "LLC" && way->dp)
      way->accessed = true;

    // Liveness tracking: update for all LLC and STLB blocks (not just dp).
    if (NAME == "cpu0_STLB" || NAME == "LLC") {
      way->hit_count++;
      way->last_hit_cycle = current_cycle;
    }

    // update prefetch stats and reset prefetch bit
    if (way->prefetch && !handle_pkt.prefetch_from_this) {
      sim_stats.back().pf_useful++;
      way->prefetch = false;
    }
  } else {
    sim_stats.back().misses[handle_pkt.type][handle_pkt.cpu]++;
  }

  return hit;
}

bool CACHE::handle_miss(const PACKET& handle_pkt)
{
  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "] " << __func__;
    std::cout << " instr_id: " << handle_pkt.instr_id << " address: " << std::hex << (handle_pkt.address >> OFFSET_BITS);
    std::cout << " full_addr: " << handle_pkt.address;
    std::cout << " full_v_addr: " << handle_pkt.v_address << std::dec;
    std::cout << " type: " << +handle_pkt.type;
    std::cout << " local_prefetch: " << std::boolalpha << handle_pkt.prefetch_from_this << std::noboolalpha;
    std::cout << " cycle: " << current_cycle << std::endl;
  }

  cpu = handle_pkt.cpu;

  // Bypass regret: if this demand miss is for a previously-bypassed line that
  // would still have been resident, count it as a regret.
  if ((NAME == "cpu0_STLB" || NAME == "LLC") && handle_pkt.type != PREFETCH) {
    const auto set_idx = get_set_index(handle_pkt.address);
    const uint64_t tag = handle_pkt.address >> OFFSET_BITS;
    auto& q = bypass_shadow[set_idx];
    // Expire stale front entries.
    while (!q.empty() && bypass_per_set_fills[set_idx] - q.front().fills_at_bypass > NUM_WAY) {
      sim_stats.back().bypass_correct++;
      if (bypass_debt_scale > 0 && NAME == "LLC" && bypass_debt > 0) bypass_debt--;
      if (cbpred_trace_addr != UINT64_MAX && q.front().addr_tag == cbpred_trace_addr)
        std::clog << "[LLC cbpred] bypass_correct 0x" << std::hex << q.front().addr_tag << std::dec
                  << " (thd=" << bconf_thd << ")\n";
      q.pop_front();
    }
    // Check for a matching bypassed address anywhere in the (fresh) queue.
    auto match = std::find_if(q.begin(), q.end(),
        [tag](const BypassShadowEntry& e) { return e.addr_tag == tag; });
    if (match != q.end()) {
      sim_stats.back().bypass_incorrect++;
      q.erase(match);
      // Smooth de-escalation: each misprediction reduces confidence without a hard reset.
      if (cbpred_weighted && cbpred && NAME == "LLC") {
        auto& e = get_bhist_entry(handle_pkt.address >> OFFSET_BITS);
        const uint64_t doa_before = e.doa;
        e.doa = (e.doa >= cbpred_w_mispredict) ? e.doa - cbpred_w_mispredict : 0;
        assert(e.doa <= doa_before);
        if (tracing_cbpred())
          trace_cbpred_event("mispredict", handle_pkt.address >> OFFSET_BITS, doa_before, e.doa);
        // Global adaptive gate: accumulate mispredict debt to raise the effective bconf threshold.
        if (bypass_debt_scale > 0)
          bypass_debt = std::min(bypass_debt + cbpred_w_mispredict, bypass_debt_cap);
      }
    }
  }

  // check mshr
  auto mshr_entry = std::find_if(MSHR.begin(), MSHR.end(), eq_addr<PACKET>(handle_pkt.address, OFFSET_BITS));
  bool mshr_full = (MSHR.size() == MSHR_SIZE);

  if (mshr_entry != MSHR.end()) // miss already inflight
  {
    auto instr_copy = std::move(mshr_entry->instr_depend_on_me);
    auto ret_copy = std::move(mshr_entry->to_return);

    std::set_union(std::begin(instr_copy), std::end(instr_copy), std::begin(handle_pkt.instr_depend_on_me), std::end(handle_pkt.instr_depend_on_me),
                   std::back_inserter(mshr_entry->instr_depend_on_me), ooo_model_instr::program_order);
    std::set_union(std::begin(ret_copy), std::end(ret_copy), std::begin(handle_pkt.to_return), std::end(handle_pkt.to_return),
                   std::back_inserter(mshr_entry->to_return));

    if (mshr_entry->type == PREFETCH && handle_pkt.type != PREFETCH) {
      // Mark the prefetch as useful
      if (mshr_entry->prefetch_from_this)
        sim_stats.back().pf_useful++;

      uint64_t prior_event_cycle = mshr_entry->event_cycle;
      auto to_return = std::move(mshr_entry->to_return);
      *mshr_entry = handle_pkt;

      // in case request is already returned, we should keep event_cycle
      mshr_entry->event_cycle = prior_event_cycle;
      mshr_entry->cycle_enqueued = current_cycle;
      mshr_entry->to_return = std::move(to_return);
    }
  } else {
    // dpPred shadow table: if this VPN was previously bypassed, serve the
    // stored translation and re-insert it into the STLB (PTW skipped).
    if (dppred && NAME == "cpu0_STLB" && dppred_shadow_lookup(handle_pkt))
      return true;

    if (mshr_full)  // not enough MSHR resource
      return false; // TODO should we allow prefetches anyway if they will not be filled to this level?

    auto fwd_pkt = handle_pkt;

    if (fwd_pkt.type == WRITE)
      fwd_pkt.type = RFO;

    if (handle_pkt.fill_this_level)
      fwd_pkt.to_return = {this};
    else
      fwd_pkt.to_return.clear();

    fwd_pkt.fill_this_level = true; // We will always fill the lower level
    fwd_pkt.prefetch_from_this = false;

    bool success;
    if (prefetch_as_load || handle_pkt.type != PREFETCH)
      success = lower_level->add_rq(fwd_pkt);
    else
      success = lower_level->add_pq(fwd_pkt);

    if (!success)
      return false;

    // Allocate an MSHR
    if (!std::empty(fwd_pkt.to_return)) {
      mshr_entry = MSHR.insert(std::end(MSHR), handle_pkt);
      mshr_entry->pf_metadata = fwd_pkt.pf_metadata;
      mshr_entry->cycle_enqueued = current_cycle;
      mshr_entry->event_cycle = std::numeric_limits<uint64_t>::max();
    }
  }

  return true;
}

bool CACHE::handle_write(const PACKET& handle_pkt)
{
  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "] " << __func__;
    std::cout << " instr_id: " << handle_pkt.instr_id;
    std::cout << " full_addr: " << std::hex << handle_pkt.address;
    std::cout << " full_v_addr: " << handle_pkt.v_address << std::dec;
    std::cout << " type: " << +handle_pkt.type;
    std::cout << " local_prefetch: " << std::boolalpha << handle_pkt.prefetch_from_this << std::noboolalpha;
    std::cout << " cycle: " << current_cycle << std::endl;
  }

  inflight_writes.push_back(handle_pkt);
  inflight_writes.back().event_cycle = current_cycle + (warmup ? 0 : FILL_LATENCY);
  inflight_writes.back().cycle_enqueued = current_cycle;

  return true;
}

template <typename R, typename F>
long int operate_queue(R& queue, long int sz, F&& func)
{
  auto [begin, end] = champsim::get_span_p(std::cbegin(queue), std::cend(queue), sz, std::forward<F>(func));
  auto retval = std::distance(begin, end);
  queue.erase(begin, end);
  return retval;
}

void CACHE::operate()
{
  auto tag_bw = MAX_TAG;
  auto fill_bw = MAX_FILL;

  auto do_fill = [cycle = current_cycle, this](const auto& x) {
    return x.event_cycle <= cycle && this->handle_fill(x);
  };

  auto operate_readlike = [&, this](const auto& pkt) {
    return queues.is_ready(pkt) && (this->try_hit(pkt) || this->handle_miss(pkt));
  };

  auto operate_writelike = [&, this](const auto& pkt) {
    return queues.is_ready(pkt) && (this->try_hit(pkt) || this->handle_write(pkt));
  };

  for (auto q : {std::ref(MSHR), std::ref(inflight_writes)})
    fill_bw -= operate_queue(q.get(), fill_bw, do_fill);

  if (match_offset_bits) {
    // Treat writes (that is, stores) like reads
    for (auto q : {std::ref(queues.WQ), std::ref(queues.PTWQ), std::ref(queues.RQ), std::ref(queues.PQ)})
      tag_bw -= operate_queue(q.get(), tag_bw, operate_readlike);
  } else {
    // Treat writes (that is, writebacks) like fills
    tag_bw -= operate_queue(queues.WQ, tag_bw, operate_writelike);

    for (auto q : {std::ref(queues.PTWQ), std::ref(queues.RQ), std::ref(queues.PQ)})
      tag_bw -= operate_queue(q.get(), tag_bw, operate_readlike);
  }

  impl_prefetcher_cycle_operate();
}

uint64_t CACHE::get_set(uint64_t address) const { return get_set_index(address); }

std::size_t CACHE::get_set_index(uint64_t address) const { return (address >> OFFSET_BITS) & champsim::bitmask(champsim::lg2(NUM_SET)); }

template <typename It>
std::pair<It, It> get_span(It anchor, typename std::iterator_traits<It>::difference_type set_idx, typename std::iterator_traits<It>::difference_type num_way)
{
  auto begin = std::next(anchor, set_idx * num_way);
  return {std::move(begin), std::next(begin, num_way)};
}

auto CACHE::get_set_span(uint64_t address) -> std::pair<std::vector<BLOCK>::iterator, std::vector<BLOCK>::iterator>
{
  const auto set_idx = get_set_index(address);
  assert(set_idx < NUM_SET);
  return get_span(std::begin(block), static_cast<std::vector<BLOCK>::difference_type>(set_idx), NUM_WAY); // safe cast because of prior assert
}

auto CACHE::get_set_span(uint64_t address) const -> std::pair<std::vector<BLOCK>::const_iterator, std::vector<BLOCK>::const_iterator>
{
  const auto set_idx = get_set_index(address);
  assert(set_idx < NUM_SET);
  return get_span(std::cbegin(block), static_cast<std::vector<BLOCK>::difference_type>(set_idx), NUM_WAY); // safe cast because of prior assert
}

uint64_t CACHE::get_way(uint64_t address, uint64_t) const
{
  auto [begin, end] = get_set_span(address);
  return std::distance(begin, std::find_if(begin, end, eq_addr<BLOCK>(address, OFFSET_BITS)));
}

uint64_t CACHE::invalidate_entry(uint64_t inval_addr)
{
  auto [begin, end] = get_set_span(inval_addr);
  auto inv_way = std::find_if(begin, end, eq_addr<BLOCK>(inval_addr, OFFSET_BITS));

  if (inv_way != end)
    inv_way->valid = 0;

  return std::distance(begin, inv_way);
}

bool CACHE::add_rq(const PACKET& packet)
{
  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "_RQ] " << __func__ << " instr_id: " << packet.instr_id << " address: " << std::hex << (packet.address >> OFFSET_BITS);
    std::cout << " full_addr: " << packet.address << " v_address: " << packet.v_address << std::dec << " type: " << +packet.type
              << " occupancy: " << std::size(queues.RQ) << " current_cycle: " << current_cycle << std::endl;
  }

  return queues.add_rq(packet);
}

bool CACHE::add_wq(const PACKET& packet)
{
  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "_WQ] " << __func__ << " instr_id: " << packet.instr_id << " address: " << std::hex << (packet.address >> OFFSET_BITS);
    std::cout << " full_addr: " << packet.address << " v_address: " << packet.v_address << std::dec << " type: " << +packet.type
              << " occupancy: " << std::size(queues.WQ) << " current_cycle: " << current_cycle << std::endl;
  }

  return queues.add_wq(packet);
}

bool CACHE::add_ptwq(const PACKET& packet)
{
  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "_PTWQ] " << __func__ << " instr_id: " << packet.instr_id << " address: " << std::hex << (packet.address >> OFFSET_BITS);
    std::cout << " full_addr: " << packet.address << " v_address: " << packet.v_address << std::dec << " type: " << +packet.type
              << " occupancy: " << std::size(queues.PTWQ) << " current_cycle: " << current_cycle;
  }

  return queues.add_ptwq(packet);
}

int CACHE::prefetch_line(uint64_t pf_addr, bool fill_this_level, uint32_t prefetch_metadata)
{
  sim_stats.back().pf_requested++;

  PACKET pf_packet;
  pf_packet.type = PREFETCH;
  pf_packet.prefetch_from_this = true;
  pf_packet.fill_this_level = fill_this_level;
  pf_packet.pf_metadata = prefetch_metadata;
  pf_packet.cpu = cpu;
  pf_packet.address = pf_addr;
  pf_packet.v_address = virtual_prefetch ? pf_addr : 0;

  auto success = this->add_pq(pf_packet);
  if (success)
    ++sim_stats.back().pf_issued;
  return success;
}

int CACHE::prefetch_line(uint64_t, uint64_t, uint64_t pf_addr, bool fill_this_level, uint32_t prefetch_metadata)
{
  return prefetch_line(pf_addr, fill_this_level, prefetch_metadata);
}

bool CACHE::add_pq(const PACKET& packet)
{
  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "_PQ] " << __func__ << " instr_id: " << packet.instr_id << " address: " << std::hex << (packet.address >> OFFSET_BITS);
    std::cout << " full_addr: " << packet.address << " v_address: " << packet.v_address << std::dec << " type: " << +packet.type
              << " from this: " << std::boolalpha << packet.prefetch_from_this << std::noboolalpha << " occupancy: " << std::size(queues.PQ)
              << " current_cycle: " << current_cycle;
  }

  return queues.add_pq(packet);
}

void CACHE::return_data(const PACKET& packet)
{
  // check MSHR information
  auto mshr_entry = std::find_if(MSHR.begin(), MSHR.end(), eq_addr<PACKET>(packet.address, OFFSET_BITS));
  auto first_unreturned = std::find_if(MSHR.begin(), MSHR.end(), [](auto x) { return x.event_cycle == std::numeric_limits<uint64_t>::max(); });

  // sanity check
  if (mshr_entry == MSHR.end()) {
    std::cerr << "[" << NAME << "_MSHR] " << __func__ << " instr_id: " << packet.instr_id << " cannot find a matching entry!";
    std::cerr << " address: " << std::hex << packet.address;
    std::cerr << " v_address: " << packet.v_address;
    std::cerr << " address: " << (packet.address >> OFFSET_BITS) << std::dec;
    std::cerr << " event: " << packet.event_cycle << " current: " << current_cycle << std::endl;
    assert(0);
  }

  // MSHR holds the most updated information about this request
  mshr_entry->data = packet.data;
  mshr_entry->pf_metadata = packet.pf_metadata;
  mshr_entry->event_cycle = current_cycle + (warmup ? 0 : FILL_LATENCY);

  if constexpr (champsim::debug_print) {
    std::cout << "[" << NAME << "_MSHR] " << __func__ << " instr_id: " << mshr_entry->instr_id;
    std::cout << " address: " << std::hex << mshr_entry->address;
    std::cout << " data: " << mshr_entry->data << std::dec;
    std::cout << " event: " << mshr_entry->event_cycle << " current: " << current_cycle << std::endl;
  }

  // Order this entry after previously-returned entries, but before non-returned
  // entries
  std::iter_swap(mshr_entry, first_unreturned);
}

std::size_t CACHE::get_occupancy(uint8_t queue_type, uint64_t)
{
  if (queue_type == 0)
    return std::size(MSHR);
  else if (queue_type == 1)
    return std::size(queues.RQ);
  else if (queue_type == 2)
    return std::size(queues.WQ);
  else if (queue_type == 3)
    return std::size(queues.PQ);

  return 0;
}

std::size_t CACHE::get_size(uint8_t queue_type, uint64_t)
{
  if (queue_type == 0)
    return MSHR_SIZE;
  else if (queue_type == 1)
    return queues.RQ_SIZE;
  else if (queue_type == 2)
    return queues.WQ_SIZE;
  else if (queue_type == 3)
    return queues.PQ_SIZE;
  else if (queue_type == 4)
    return queues.PTWQ_SIZE;

  return 0;
}

void CACHE::initialize()
{
  if (NAME == "cpu0_STLB")
    stlb_ptr = this;
  impl_prefetcher_initialize();
  impl_initialize_replacement();
}

void CACHE::begin_phase()
{
  roi_stats.emplace_back();
  sim_stats.emplace_back();

  roi_stats.back().name = NAME;
  sim_stats.back().name = NAME;

  // Reset only the in-progress window counters at each phase boundary so the
  // next window starts fresh.  The gate decision (pfq_gate_on) is intentionally
  // kept from the previous phase: warmup observations are a reasonable prior for
  // the start of simulation, and the first simulation window will update it.
  pfq_win_probes = 0;
  pfq_win_hits   = 0;
}

void CACHE::end_phase(unsigned finished_cpu)
{
  for (auto type : {LOAD, RFO, PREFETCH, WRITE, TRANSLATION}) {
    roi_stats.back().hits.at(type).at(finished_cpu) = sim_stats.back().hits.at(type).at(finished_cpu);
    roi_stats.back().misses.at(type).at(finished_cpu) = sim_stats.back().misses.at(type).at(finished_cpu);
  }

  roi_stats.back().pf_requested = sim_stats.back().pf_requested;
  roi_stats.back().pf_issued = sim_stats.back().pf_issued;
  roi_stats.back().pf_useful = sim_stats.back().pf_useful;
  roi_stats.back().pf_useless = sim_stats.back().pf_useless;
  roi_stats.back().pf_fill = sim_stats.back().pf_fill;

  roi_stats.back().total_miss_latency = sim_stats.back().total_miss_latency;

  roi_stats.back().llt_bypasses = sim_stats.back().llt_bypasses;
  roi_stats.back().llc_bypasses = sim_stats.back().llc_bypasses;

  roi_stats.back().bypass_incorrect          = sim_stats.back().bypass_incorrect;
  roi_stats.back().bypass_correct            = sim_stats.back().bypass_correct;
  roi_stats.back().bypass_shadow_overflow    = sim_stats.back().bypass_shadow_overflow;
  roi_stats.back().cbpred_doa_normal_inserts      = sim_stats.back().cbpred_doa_normal_inserts;
  roi_stats.back().cbpred_doa_pessimistic_inserts = sim_stats.back().cbpred_doa_pessimistic_inserts;
  roi_stats.back().pfq_probes   = sim_stats.back().pfq_probes;
  roi_stats.back().pfq_hits     = sim_stats.back().pfq_hits;

  roi_stats.back().phist_lookups = sim_stats.back().phist_lookups;
  roi_stats.back().phist_hits    = sim_stats.back().phist_hits;
  roi_stats.back().bhist_lookups = sim_stats.back().bhist_lookups;
  roi_stats.back().bhist_hits    = sim_stats.back().bhist_hits;
  roi_stats.back().st_lookups    = sim_stats.back().st_lookups;
  roi_stats.back().st_hits       = sim_stats.back().st_hits;

  roi_stats.back().evict_total        = sim_stats.back().evict_total;
  roi_stats.back().evict_doa          = sim_stats.back().evict_doa;
  roi_stats.back().evict_mostly_dead  = sim_stats.back().evict_mostly_dead;
  roi_stats.back().evict_mostly_alive = sim_stats.back().evict_mostly_alive;
  roi_stats.back().evict_zero_residence = sim_stats.back().evict_zero_residence;
  roi_stats.back().evict_hit_hist     = sim_stats.back().evict_hit_hist;
  roi_stats.back().evict_doa_on_doa_stlb_page    = sim_stats.back().evict_doa_on_doa_stlb_page;
  roi_stats.back().evict_doa_stlb_resident_alive = sim_stats.back().evict_doa_stlb_resident_alive;
  roi_stats.back().evict_doa_stlb_evicted_doa    = sim_stats.back().evict_doa_stlb_evicted_doa;
  roi_stats.back().evict_doa_stlb_evicted_alive  = sim_stats.back().evict_doa_stlb_evicted_alive;

  roi_stats.back().llt_pc_stats = std::move(sim_stats.back().llt_pc_stats);
  roi_stats.back().llc_pc_stats = std::move(sim_stats.back().llc_pc_stats);
}

bool CACHE::should_activate_prefetcher(const PACKET& pkt) const { return ((1 << pkt.type) & pref_activate_mask) && !pkt.prefetch_from_this; }

void CACHE::print_deadlock()
{
  if (!std::empty(MSHR)) {
    std::cout << NAME << " MSHR Entry" << std::endl;
    std::size_t j = 0;
    for (PACKET entry : MSHR) {
      std::cout << "[" << NAME << " MSHR] entry: " << j++ << " instr_id: " << entry.instr_id;
      std::cout << " address: " << std::hex << entry.address << " v_addr: " << entry.v_address << std::dec << " type: " << +entry.type;
      std::cout << " event_cycle: " << entry.event_cycle << std::endl;
    }
  } else {
    std::cout << NAME << " MSHR empty" << std::endl;
  }

  if (!std::empty(queues.RQ)) {
    for (const auto& entry : queues.RQ) {
      std::cout << "[" << NAME << " RQ] "
                << " instr_id: " << entry.instr_id;
      std::cout << " address: " << std::hex << entry.address << " v_addr: " << entry.v_address << std::dec << " type: " << +entry.type;
      std::cout << " event_cycle: " << entry.event_cycle << std::endl;
    }
  } else {
    std::cout << NAME << " RQ empty" << std::endl;
  }

  if (!std::empty(queues.WQ)) {
    for (const auto& entry : queues.WQ) {
      std::cout << "[" << NAME << " WQ] "
                << " instr_id: " << entry.instr_id;
      std::cout << " address: " << std::hex << entry.address << " v_addr: " << entry.v_address << std::dec << " type: " << +entry.type;
      std::cout << " event_cycle: " << entry.event_cycle << std::endl;
    }
  } else {
    std::cout << NAME << " WQ empty" << std::endl;
  }

  if (!std::empty(queues.PQ)) {
    for (const auto& entry : queues.PQ) {
      std::cout << "[" << NAME << " PQ] "
                << " instr_id: " << entry.instr_id;
      std::cout << " address: " << std::hex << entry.address << " v_addr: " << entry.v_address << std::dec << " type: " << +entry.type;
      std::cout << " event_cycle: " << entry.event_cycle << std::endl;
    }
  } else {
    std::cout << NAME << " PQ empty" << std::endl;
  }
}
