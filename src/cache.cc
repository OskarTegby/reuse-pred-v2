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

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <numeric>
#include <unordered_set>

#include "champsim.h"
#include "champsim_constants.h"
#include "instruction.h"
#include "util.h"

// ──────────────────────────────────────────────
// Shared replacement-history infrastructure
// ──────────────────────────────────────────────

namespace {

// PC subset tracker (REPL_HIST_PC_SUBSET=1).
// Collects unique fill-PCs per cache level and reports at program exit whether
// the LLC PC set is a subset of the STLB PC set. If it isn't, something is
// wrong: every LLC fill must have gone through address translation first.
struct PCSubsetTracker {
  std::unordered_set<uint64_t> llc_pcs, stlb_pcs;
  bool enabled = false;
  ~PCSubsetTracker() {
    if (!enabled || (llc_pcs.empty() && stlb_pcs.empty()))
      return;
    const uint64_t n_llc  = static_cast<uint64_t>(llc_pcs.size());
    const uint64_t n_stlb = static_cast<uint64_t>(stlb_pcs.size());
    uint64_t in_both = 0;
    for (auto ip : llc_pcs)
      if (stlb_pcs.count(ip)) ++in_both;
    const uint64_t llc_only = n_llc - in_both;
    std::printf("\n=== PC subset analysis (REPL_HIST_PC_SUBSET) ===\n");
    std::printf("  STLB unique PCs  : %lu\n", n_stlb);
    std::printf("  LLC  unique PCs  : %lu\n", n_llc);
    std::printf("  LLC ∩ STLB       : %lu\n", in_both);
    std::printf("  LLC ⊆ STLB       : %s  (%.1f%% of LLC PCs appear in STLB)\n",
                llc_only == 0 ? "YES" : "NO",
                n_llc ? 100.0 * in_both / n_llc : 0.0);
    if (llc_only > 0)
      std::printf("  LLC-only PCs     : %lu  <-- these should not exist\n", llc_only);
  }
};
PCSubsetTracker g_pc_subset;

// Merged replacement history table (REPL_HIST_MERGED=1).
// One HistTable shared by both LLC and cpu0_STLB. Both levels call update()
// on the same object at eviction and classify() on it at fill time. Each
// level still uses its own thd_doa/thd_dead for the classify call, so the
// per-level threshold tuning continues to apply.
// ChampSim is single-threaded, so sharing the table is race-condition-free.
HistTable g_merged_repl_hist;
bool      g_merged_hist_ready = false;
bool      g_use_merged_hist   = false;

} // namespace

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

// On a shadow table hit: reset the VPN's history row, serve the stored
// translation to all requesters, and re-insert the entry into the STLB via
// a synthetic handle_fill call (PTW is skipped entirely).
// dppred_bypass will see a cleared phist counter and allow the insertion.
bool CACHE::dppred_shadow_lookup(const PACKET& handle_pkt)
{
  const auto vpn = handle_pkt.address >> OFFSET_BITS;
  auto it = std::find_if(shadow_table.begin(), shadow_table.end(),
                         [vpn](const auto& e) { return std::get<0>(e) == vpn; });
  if (it == shadow_table.end())
    return false;

  phist.reset(std::get<2>(*it));   // clear confidence for the PC that caused this bypass
  const auto stored_data = std::get<1>(*it);
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
  if (phist.get_score(fill_mshr.ip) <= (int64_t)pconf_thd)
    return false;

  if (pfq.size() >= pfq_cap)
    pfq.pop_front();
  pfq.push_back({fill_mshr.data >> LOG2_PAGE_SIZE, fill_mshr.ip});

  // Remember the bypassed (VPN, data, PC) for re-insertion on re-access (FIFO)
  if (shadow_table.size() >= st_size)
    shadow_table.pop_front();
  shadow_table.push_back({fill_mshr.address >> OFFSET_BITS, fill_mshr.data, fill_mshr.ip});

  sim_stats.back().llt_bypasses++;
  return true;
}

// Record a block our liveness predictor just bypassed, with its data, so a later
// re-reference can be detected and recovered. FIFO eviction.
void CACHE::shadow_record_bypass(uint64_t block_addr, uint64_t pc, uint64_t data)
{
  if (bypass_shadow_cap_ == 0) return;
  if (bypass_shadow_.count(block_addr)) return;  // already tracked
  while (bypass_shadow_fifo_.size() >= bypass_shadow_cap_) {
    bypass_shadow_.erase(bypass_shadow_fifo_.front());  // no-op if already removed by a hit
    bypass_shadow_fifo_.pop_front();
  }
  bypass_shadow_[block_addr] = {pc, data};
  bypass_shadow_fifo_.push_back(block_addr);
}

// On a re-reference to a block we bypassed: a confirmed bypass mistake. Delete
// the offending PC's history entry (so it must re-earn DoA) and reinsert the
// block. STLB: serve the stored translation and re-insert, skipping the page
// walk (translations are stable, so the stored mapping is safe to serve) →
// returns true, miss satisfied. LLC: returns false so the miss refetches fresh
// data and reinserts it normally (the erased history entry means it is no longer
// bypassed) — avoids serving potentially-stale line data from a victim buffer.
bool CACHE::liveness_bypass_shadow_hit(const PACKET& handle_pkt)
{
  if (bypass_shadow_cap_ == 0) return false;
  const uint64_t addr = handle_pkt.address >> OFFSET_BITS;
  auto it = bypass_shadow_.find(addr);
  if (it == bypass_shadow_.end()) return false;
  const uint64_t pc = it->second.first, data = it->second.second;
  bypass_shadow_.erase(it);            // stale fifo slot cleaned on later eviction
  repl_hist_pc.erase_key(pc);          // delete the offending PC's history entry
  sim_stats.back().liveness_bypass_shadow_hits++;
  if (NAME == "cpu0_STLB") {
    auto copy{handle_pkt};
    copy.data = data;
    for (auto ret : copy.to_return)
      ret->return_data(copy);          // serve the recovered translation
    PACKET fill_pkt = handle_pkt;
    fill_pkt.data = data;
    fill_pkt.to_return = {};
    handle_fill(fill_pkt);             // re-insert into the STLB (PTW skipped)
    return true;
  }
  return false;  // LLC: miss proceeds, refetches fresh data, reinserts (not bypassed)
}

// Returns true when cbPred predicts this cache block is dead
// (its page was previously bypassed by dpPred and its block counter is high).
bool CACHE::cbpred_bypass(const PACKET& fill_mshr)
{
  if (cbpred_access_pc_) {
    // Morph rung: clean ungated predictor. Key by block address (CBPRED_KEY=block_addr)
    // or the demand-access PC (CBPRED_KEY=access_pc) so indexing can be varied alone.
    // bconf_thd plays the role of (bypass_thd - 1).
    const uint64_t key = cbpred_key_addr_ ? (fill_mshr.address >> OFFSET_BITS) : fill_mshr.ip;
    const uint64_t conf = (uint64_t)std::max(int64_t{0}, bhist_flat.get_score(key));
    if (conf <= bconf_thd)
      return false;
    sim_stats.back().llc_bypasses++;
    return true;
  }
  const auto pfn    = fill_mshr.address >> LOG2_PAGE_SIZE;
  const auto pfq_it = std::find_if(pfq.begin(), pfq.end(),
                                   [pfn](const auto& e){ return e.first == pfn; });
  const bool in_pfq = pfq_it != pfq.end();

  if (pfq_ema_mode) {
    pfq_ema_val = pfq_ema_alpha * (in_pfq ? 1.0 : 0.0) + (1.0 - pfq_ema_alpha) * pfq_ema_val;
    pfq_gate    = (pfq_ema_val >= pfq_ema_thd);
  }

  const uint64_t block_addr = fill_mshr.address >> OFFSET_BITS;
  uint64_t confidence;
  uint64_t dp_pc = 0;
  if (cbpred_pc_only_) {
    // PC-only: aggregate per dpPred PC (needs a PFQ hit for the PC), keyed in bhist_flat.
    if (!in_pfq) return false;
    dp_pc = pfq_it->second;
    confidence = (uint64_t)std::max(int64_t{0}, bhist_flat.get_score(dp_pc));
    record_characterization(dp_pc, block_addr);
  } else if (use_pc_bhist) {
    // PC-indexed mode requires a PFQ hit to obtain the dpPred PC.
    if (!in_pfq) return false;
    dp_pc = pfq_it->second;
    confidence = bhist_pc.get(dp_pc, block_addr);
    record_characterization(dp_pc, block_addr);
  } else {
    if (pfq_gate && !in_pfq) return false;
    confidence = (uint64_t)std::max(int64_t{0}, bhist_flat.get_score(block_addr));
    record_characterization(0, block_addr);
  }

  if (confidence <= bconf_thd)
    return false;

  sim_stats.back().llc_bypasses++;
  if (!use_pc_bhist && !in_pfq)
    sim_stats.back().cbpred_nogate_bypasses++;
  return true;
}

// Updates the history table when a valid entry is displaced: phist for a
// translation entry evicted from the STLB, bhist for a cache block evicted
// from the LLC.  Increments the confidence counter if the entry was never
// accessed since insertion; resets it to zero otherwise.
void CACHE::update_eviction_counters(const BLOCK& victim, liveness_class evict_lv)
{
  // cbpred / dppred bypass-predictor tables.
  // phist and bhist_flat are HistTable (take liveness_class); bhist_pc is
  // PCPartitionedTable and still uses bool accessed.
  const liveness_class bypass_lv = victim.accessed ? liveness_class::mostly_alive : liveness_class::doa;
  if (dppred && NAME == "cpu0_STLB")
    phist.update(victim.ip, bypass_lv);
  else if (cbpred && NAME == "LLC") {
    if (cbpred_access_pc_) {
      // Morph rung: learn on every eviction, same classification (evict_lv) + thresholds
      // for both key choices, so only the key (and BHIST_SCORING) varies between rungs.
      const uint64_t key = cbpred_key_addr_ ? (victim.address >> OFFSET_BITS) : victim.ip;
      bhist_flat.update(key, evict_lv, thd_dead, thd_doa, 0);
    } else if (cbpred_pc_only_) {
      if (victim.dp) bhist_flat.update(victim.dp_pc, bypass_lv);  // PC-only: per dp_pc (needs PFQ)
    } else if (use_pc_bhist) {
      if (victim.dp) bhist_pc.update(victim.dp_pc, victim.address >> OFFSET_BITS, bypass_lv);
    } else if (victim.dp || !pfq_gate) {
      // Per-address: when the PFQ gate is off (CBPRED_NO_PFQ) learn on every
      // eviction so the ungated rung has data even with dpPred disabled.
      bhist_flat.update(victim.address >> OFFSET_BITS, bypass_lv);
    }
  }

  // Replacement-guidance history: delegated to HistTable (bounded or unbounded).
  if (NAME == "LLC" || NAME == "cpu0_STLB") {
    bool do_update = true;
    uint64_t repl_key = 0;
    if (stlb_llc_prop_ && NAME == "LLC") {
      const uint64_t own_key = repl_hist_use_addr ? (victim.address >> OFFSET_BITS) : victim.ip;
      if (prop_ownpc_) {
        // Version D: gate by the PFN match (prop_pc!=0 = page was STLB-bypassed),
        // but index by the LLC's own PC.
        if (victim.prop_pc != 0) repl_key = own_key;
        else                     do_update = false;
      } else if (victim.prop_pc != 0) {
        repl_key = victim.prop_pc;   // A/B propagated → STLB PC
      } else if (prop_hybrid_) {
        repl_key = own_key;          // version B: own PC on miss
      } else {
        do_update = false;           // version A: no update on miss
      }
    } else {
      repl_key = repl_hist_use_addr
          ? ((NAME == "LLC") ? (victim.address >> OFFSET_BITS) : victim.address)
          : victim.ip;
    }
    const uint64_t lifespan = (victim.install_cycle > 0 && current_cycle >= victim.install_cycle)
                             ? current_cycle - victim.install_cycle : 0;
    if (do_update) {
      if (::g_use_merged_hist)
        ::g_merged_repl_hist.update(repl_key, evict_lv, thd_dead, thd_doa, lifespan);
      else
        repl_hist_pc.update(repl_key, evict_lv, thd_dead, thd_doa, lifespan);
    }

    if (::g_pc_subset.enabled && victim.ip != 0) {
      if (NAME == "LLC")       ::g_pc_subset.llc_pcs.insert(victim.ip);
      else                     ::g_pc_subset.stlb_pcs.insert(victim.ip);
    }
  }
}

// Reads environment variables to enable dpPred/cbPred and tune their
// thresholds and table sizes. Called once from the CACHE constructor.
// Variables (all optional; defaults match the header initializers):
//   DPPRED=1             enable dead-page predictor on the STLB
//   CBPRED=1             enable dead-block predictor on the LLC
//   PCONF_THD=<n>        dpPred confidence threshold (default 6)
//   BCONF_THD=<n>        cbPred confidence threshold (default 6)
//   ST_SIZE=<n>          shadow-table capacity (default 2)
//   PFQ_CAP=<n>          shared PFQ capacity (default 8)
//   HIST_REPL=lru|lfu|lfu_doa|srrip  replacement for both phist and flat bhist (default: lru)
//   PHIST_REPL=...       override HIST_REPL for pHIST only
//   BHIST_REPL=...       override HIST_REPL for flat bHIST only
//   PHIST_BUF_CAP=<n>    promotion buffer size for pHIST (default 0 = off)
//   BHIST_MODE=flat|pc   bHIST indexing: flat=addr-indexed HistTable (default),
//                        pc=PC-partitioned PCPartitionedTable (requires PFQ hit)
//   BHIST_WAYS=<n>       flat bHIST capacity (default 4096)
//   BHIST_BUF_CAP=<n>    promotion buffer size for flat bHIST (default 0 = off)
//   BHIST_PC_WAYS=<n>    PC slots for pc-mode bHIST (default 256)
//   BHIST_ADDR_WAYS=<n>  addr slots per PC (default 16)
//   BHIST_ADDR_BUF=<n>   per-PC addr promotion buffer size (default 0 = off)
//   CBPRED_NO_PFQ=1      disable the PFQ gate: cbPred fires on flat bhist alone
//   PFQ_EMA=1            dynamically adapt the PFQ gate via an EMA of hit rate
//   PFQ_EMA_ALPHA=<f>    EMA decay factor (default 1/1024 ≈ 0.001)
//   PFQ_EMA_THD=<pct>    gate turns OFF when EMA < pct/100 (default 10 → 10%)
void CACHE::load_predictor_settings()
{
  auto getenv_uint64 = [](const char* var, uint64_t fallback) -> uint64_t {
    const char* val = std::getenv(var);
    return val ? static_cast<uint64_t>(std::stoull(val)) : fallback;
  };
  auto getenv_double = [](const char* var, double fallback) -> double {
    const char* val = std::getenv(var);
    return val ? std::stod(val) : fallback;
  };

  if (const char* v = std::getenv("DPPRED"); v && std::stoull(v))
    dppred = true;
  if (const char* v = std::getenv("CBPRED"); v && std::stoull(v))
    cbpred = true;

  pconf_thd = getenv_uint64("PCONF_THD", pconf_thd);
  bconf_thd = getenv_uint64("BCONF_THD", bconf_thd);
  st_size   = getenv_uint64("ST_SIZE",   st_size);
  pfq_cap   = getenv_uint64("PFQ_CAP",   pfq_cap);

  {
    auto parse_policy = [](const char* v) -> HistTable::Policy {
      if (!v) return HistTable::Policy::LRU;
      if (std::string_view(v) == "lfu")     return HistTable::Policy::LFU;
      if (std::string_view(v) == "lfu_doa") return HistTable::Policy::LFU_DOA;
      if (std::string_view(v) == "srrip")   return HistTable::Policy::SRRIP;
      if (std::string_view(v) == "tiered")  return HistTable::Policy::TIERED;
      return HistTable::Policy::LRU;
    };
    // PHIST_REPL and BHIST_REPL override HIST_REPL for their respective table.
    const char* hist_repl  = std::getenv("HIST_REPL");
    const char* phist_repl = std::getenv("PHIST_REPL") ? std::getenv("PHIST_REPL") : hist_repl;
    const char* bhist_repl = std::getenv("BHIST_REPL") ? std::getenv("BHIST_REPL") : hist_repl;

    // Morph study (branch maz-morph-unbounded): flags to gradually turn Mazumdar's
    // bounded/hashed/gated predictor into our idealized one.
    //   MAZ_UNBOUNDED=1   → bhist/phist become unbounded (idealized, like ours)
    //   {B,P}HIST_HASH=1  → bounded table hashes the key into log2(ways) bits
    //                       (faithful Mazumdar: finite hashed index with aliasing)
    const bool maz_unbounded = getenv_uint64("MAZ_UNBOUNDED", 0) != 0;
    auto log2_floor = [](uint64_t n) { unsigned b = 0; while (n > 1) { n >>= 1; ++b; } return b; };

    const uint64_t pw        = getenv_uint64("PHIST_WAYS",    1024);
    const uint64_t phist_buf = getenv_uint64("PHIST_BUF_CAP",    0);
    phist = maz_unbounded ? HistTable() : HistTable(pw, parse_policy(phist_repl), phist_buf);
    if (!maz_unbounded && getenv_uint64("PHIST_HASH", 0))
      phist.set_hash(log2_floor(pw));

    if (const char* v = std::getenv("BHIST_MODE"); v && std::string_view(v) == "pc") {
      use_pc_bhist = true;
      const uint64_t bpc_ways   = getenv_uint64("BHIST_PC_WAYS",   256);
      const uint64_t baddr_ways = getenv_uint64("BHIST_ADDR_WAYS",  16);
      const uint64_t baddr_buf  = getenv_uint64("BHIST_ADDR_BUF",    0);
      bhist_pc = PCPartitionedTable(bpc_ways, baddr_ways, baddr_buf);
    } else {
      use_pc_bhist = false;
      const uint64_t bw      = getenv_uint64("BHIST_WAYS",    4096);
      const uint64_t buf_cap = getenv_uint64("BHIST_BUF_CAP",    0);
      bhist_flat = maz_unbounded ? HistTable() : HistTable(bw, parse_policy(bhist_repl), buf_cap);
      if (!maz_unbounded && getenv_uint64("BHIST_HASH", 0))
        bhist_flat.set_hash(log2_floor(bw));
      // bhist scoring mode (default 2 = Mazumdar dead-counter). Set BHIST_SCORING=5
      // to give cbPred our liveness scoring, used by the access-PC convergence rung.
      bhist_flat.set_scoring_mode(static_cast<int>(getenv_uint64("BHIST_SCORING", 2)));
      // pconly: same bhist_flat HistTable, but keyed by the dpPred PC alone (set below).
      if (const char* m = std::getenv("BHIST_MODE"); m && std::string_view(m) == "pconly")
        cbpred_pc_only_ = true;
    }
  }
  if (const char* v = std::getenv("CBPRED_KEY"); v) {
    const std::string_view k(v);
    if      (k == "access_pc")  cbpred_access_pc_ = true;
    else if (k == "block_addr") { cbpred_access_pc_ = true; cbpred_key_addr_ = true; }
  }

  if (const char* v = std::getenv("CBPRED_NO_PFQ"); v && std::stoull(v))
    pfq_gate = false;
  if (const char* v = std::getenv("PFQ_EMA"); v && std::stoull(v))
    pfq_ema_mode = true;

  pfq_ema_alpha = getenv_double("PFQ_EMA_ALPHA", pfq_ema_alpha);
  pfq_ema_thd   = getenv_double("PFQ_EMA_THD", 10.0) / 100.0;

  // Liveness-guided replacement: score thresholds θ_doa and θ_dead.
  // Per-level vars (LLC_THD_DOA / STLB_THD_DOA) override THD_DOA for a specific
  // cache level, allowing LLC and STLB to use different optimal thresholds in a
  // combined run. Falls back to THD_DOA / THD_DEAD if the level-specific var is unset.
  const char* level_doa  = (NAME == "LLC")      ? std::getenv("LLC_THD_DOA")
                         : (NAME == "cpu0_STLB") ? std::getenv("STLB_THD_DOA")
                         : nullptr;
  const char* level_dead = (NAME == "LLC")      ? std::getenv("LLC_THD_DEAD")
                         : (NAME == "cpu0_STLB") ? std::getenv("STLB_THD_DEAD")
                         : nullptr;
  thd_doa  = (level_doa  && *level_doa)  ? std::stoull(level_doa)  : getenv_uint64("THD_DOA",  1);
  thd_dead = (level_dead && *level_dead) ? std::stoull(level_dead) : getenv_uint64("THD_DEAD", 0);
  repl_hist_pc.set_scoring_mode(static_cast<int>(getenv_uint64("SCORING_MODE", 2)));
  if (const char* v = std::getenv("DOA_SATURATE_MD"); v && std::stoull(v))
    repl_hist_pc.set_doa_saturate_md(true);

  // Bounded repl_hist_pc: 0 = unbounded (default, backward compatible).
  // REPL_HIST_REPL controls table management policy (same options as HIST_REPL).
  // REPL_HIST_BUF_CAP controls the promotion buffer size (default 0 = disabled).
  {
    const uint64_t rh_cap = (NAME == "LLC")
        ? getenv_uint64("REPL_HIST_LLC_CAP",  0)
        : getenv_uint64("REPL_HIST_STLB_CAP", 0);
    if (rh_cap > 0) {
      const uint64_t rh_buf    = getenv_uint64("REPL_HIST_BUF_CAP", 0);
      const char* rh_repl      = std::getenv("REPL_HIST_REPL");
      auto parse_rh_policy     = [](const char* v) -> HistTable::Policy {
        if (!v) return HistTable::Policy::LRU;
        if (std::string_view(v) == "lfu")     return HistTable::Policy::LFU;
        if (std::string_view(v) == "lfu_doa") return HistTable::Policy::LFU_DOA;
        if (std::string_view(v) == "srrip")   return HistTable::Policy::SRRIP;
        if (std::string_view(v) == "tiered")  return HistTable::Policy::TIERED;
        return HistTable::Policy::LRU;
      };
      repl_hist_pc = HistTable(rh_cap, parse_rh_policy(rh_repl), rh_buf);
      repl_hist_pc.set_scoring_mode(static_cast<int>(getenv_uint64("SCORING_MODE", 2)));
      if (const char* v = std::getenv("DOA_SATURATE_MD"); v && std::stoull(v))
        repl_hist_pc.set_doa_saturate_md(true);
      const uint64_t rh_ckpt = getenv_uint64("REPL_HIST_CHECKPOINT", 0);
      if (rh_ckpt > 0)
        repl_hist_pc.set_checkpoint(rh_ckpt, NAME);
    } else if ((NAME == "LLC"       && std::getenv("REPL_HIST_LLC_CAP")) ||
               (NAME == "cpu0_STLB" && std::getenv("REPL_HIST_STLB_CAP"))) {
      // This level's own cap var is explicitly set to 0: zero-capacity bounded
      // table — classify() always returns mostly_alive. Keyed on the level's OWN
      // var so that bounding one level (e.g. LLC) leaves the other unbounded
      // rather than forcing it empty.
      repl_hist_pc = HistTable(0, HistTable::Policy::LRU, 0, 0);
    }
    // else (this level's env var absent): keep default-constructed HistTable (unbounded mode)
  }
  if (const char* v = std::getenv("MID_PROMOTE"); v && std::stoull(v))
    mid_promote = true;

  // Replacement guidance: use bHIST signals to guide cache replacement decisions.
  if (const char* v = std::getenv("REPL_GUIDANCE"); v && std::stoull(v))
    repl_guidance_enable = true;
  repl_guidance_thd = getenv_uint64("REPL_GUIDANCE_THD", 0);

  // Per-PC liveness characterization (LIVENESS_CHAR=1).
  if (const char* v = std::getenv("LIVENESS_CHAR"); v && std::stoull(v))
    liveness_char_enable = true;


  // Unbounded characterization: track all (PC, address) pairs to measure actual demand.
  if (const char* v = std::getenv("CHARACTERIZATION"); v && std::stoull(v))
    characterization_enable = true;

  // PC subset tracking: record unique fill-PCs per level (LLC and STLB) and
  // report LLC⊆STLB at program exit. Activated by REPL_HIST_PC_SUBSET=1.
  if (const char* v = std::getenv("REPL_HIST_PC_SUBSET"); v && std::stoull(v))
    ::g_pc_subset.enabled = true;

  if (const char* v = std::getenv("REPL_HIST_MODE"); v && std::string_view(v) == "addr")
    repl_hist_use_addr = true;
  // Periodic bypass recheck (probe): shared by LLC and STLB. Default off.
  //   BYPASS_RECHECK_MODE     = off | fixed | backoff
  //   BYPASS_RECHECK_INTERVAL = base interval (bypasses between probes, default 32)
  //   BYPASS_RECHECK_CAP      = max interval for backoff (default 256)
  auto apply_recheck = [&](HistTable& tbl) {
    const char* m = std::getenv("BYPASS_RECHECK_MODE");
    if (!m) return;
    const std::string_view sv(m);
    HistTable::RecheckMode mode = HistTable::RecheckMode::Off;
    if      (sv == "fixed")   mode = HistTable::RecheckMode::Fixed;
    else if (sv == "backoff") mode = HistTable::RecheckMode::Backoff;
    else return;  // "off" or unrecognised → leave disabled
    const uint64_t base = getenv_uint64("BYPASS_RECHECK_INTERVAL", 32);
    const uint64_t cap  = getenv_uint64("BYPASS_RECHECK_CAP",     256);
    tbl.set_recheck(mode, base, cap);
  };
  if (NAME == "LLC") {
    if (const char* v = std::getenv("LIVENESS_BYPASS"); v && std::stoull(v))
      liveness_bypass = true;
    bypass_thd = getenv_uint64("BYPASS_THD", thd_doa);
    if (const uint64_t rp = getenv_uint64("BYPASS_RESET_PERIOD", 0); rp > 0)
      repl_hist_pc.set_reset_period(rp);
    bypass_fire_reset_period_ = getenv_uint64("BYPASS_FIRE_RESET_PERIOD", 0);
    if (const uint64_t rp = getenv_uint64("BYPASS_PC_RESET_PERIOD", 0); rp > 0)
      repl_hist_pc.set_bypass_pc_reset(rp);
    apply_recheck(repl_hist_pc);
    bypass_shadow_cap_ = getenv_uint64("LLC_BYPASS_SHADOW_SIZE", getenv_uint64("BYPASS_SHADOW_SIZE", 0));
    if (const char* v = std::getenv("STLB_LLC_PROP"); v && std::stoull(v))
      stlb_llc_prop_ = true;
    if (const char* v = std::getenv("STLB_LLC_PROP_HYBRID"); v && std::stoull(v))
      prop_hybrid_ = true;
    if (const char* v = std::getenv("STLB_LLC_PROP_OWNPC"); v && std::stoull(v))
      prop_ownpc_ = true;
    if (const char* v = std::getenv("PROP_GATE"); v && std::string_view(v) == "pc")
      prop_gate_pc_ = true;
  }
  if (NAME == "cpu0_STLB") {
    if (const char* v = std::getenv("STLB_LIVENESS_BYPASS"); v && std::stoull(v))
      stlb_liveness_bypass = true;
    stlb_bypass_thd = getenv_uint64("STLB_BYPASS_THD", getenv_uint64("BYPASS_THD", thd_doa));
    if (const uint64_t rp = getenv_uint64("BYPASS_PC_RESET_PERIOD", 0); rp > 0)
      repl_hist_pc.set_bypass_pc_reset(rp);
    apply_recheck(repl_hist_pc);
    if (const char* v = std::getenv("STLB_LLC_PROP"); v && std::stoull(v))
      stlb_llc_prop_ = true;
    if (const char* v = std::getenv("STLB_LLC_PROP_HYBRID"); v && std::stoull(v))
      prop_hybrid_ = true;
    if (const char* v = std::getenv("STLB_LLC_PROP_OWNPC"); v && std::stoull(v))
      prop_ownpc_ = true;
    if (const char* v = std::getenv("PROP_GATE"); v && std::string_view(v) == "pc")
      prop_gate_pc_ = true;
    // STLB bypass shadow (our predictor's own — distinct from Mazumdar's dpPred
    // shadow_table). On the STLB, long-range translation re-reference is normal
    // page re-use, so the shadow must be SMALL: only near-immediate re-references
    // are genuine "needed that page now" bypass mistakes. A bit larger than the
    // LLC's may be needed since translation working sets are coarser.
    bypass_shadow_cap_ = getenv_uint64("STLB_BYPASS_SHADOW_SIZE", getenv_uint64("BYPASS_SHADOW_SIZE", 0));
  }

  // Merged replacement history table: one shared HistTable for both LLC and
  // STLB. Capacity set by REPL_HIST_CAP (0 = unbounded). Activated by
  // REPL_HIST_MERGED=1. Initialised only once (first CACHE constructor wins).
  if (const char* v = std::getenv("REPL_HIST_MERGED"); v && std::stoull(v)) {
    ::g_use_merged_hist = true;
    if (!::g_merged_hist_ready) {
      const uint64_t cap = getenv_uint64("REPL_HIST_CAP",     0);
      const uint64_t buf = getenv_uint64("REPL_HIST_BUF_CAP", 0);
      ::g_merged_repl_hist = HistTable(cap, HistTable::Policy::LRU, buf, 0);
      ::g_merged_hist_ready = true;
    }
    // Per-instance repl_hist_pc is unused in merged mode; keep it default
    // (unbounded, empty) so classify calls that somehow reach it are safe.
  }
}

uint64_t CACHE::get_repl_guidance_score(uint64_t block_address, uint64_t dp_pc) const
{
  if (!repl_guidance_enable)
    return 0;

  uint64_t dead_count = 0;
  if (use_pc_bhist) {
    dead_count = bhist_pc.get(dp_pc, block_address);
  } else {
    dead_count = (uint64_t)std::max(int64_t{0}, bhist_flat.get_score(block_address));
  }

  return dead_count;
}

liveness_class CACHE::classify_block_liveness(uint64_t block_address, uint64_t pc) const
{
  const uint64_t key = repl_hist_use_addr
      ? ((NAME == "LLC") ? (block_address >> OFFSET_BITS) : block_address)
      : pc;
  if (::g_use_merged_hist)
    return ::g_merged_repl_hist.classify(key, thd_doa, thd_dead);
  return repl_hist_pc.classify(key, thd_doa, thd_dead);
}

void CACHE::record_characterization(uint64_t dp_pc, uint64_t block_address)
{
  if (!characterization_enable)
    return;
  pc_to_addrs[dp_pc].insert(block_address);
}

void CACHE::print_characterization_stats() const
{
  if (!characterization_enable || pc_to_addrs.empty())
    return;

  uint64_t total_pcs = pc_to_addrs.size();
  uint64_t total_pairs = 0;
  uint64_t min_addrs = UINT64_MAX;
  uint64_t max_addrs = 0;
  double sum_addrs = 0.0;

  for (const auto& [pc, addrs] : pc_to_addrs) {
    uint64_t addr_count = addrs.size();
    total_pairs += addr_count;
    min_addrs = std::min(min_addrs, addr_count);
    max_addrs = std::max(max_addrs, addr_count);
    sum_addrs += addr_count;
  }

  double avg_addrs = sum_addrs / total_pcs;
  std::cout << "\n[CHARACTERIZATION] Unbounded (PC, address) demand:\n"
            << "  Unique PCs: " << total_pcs << "\n"
            << "  Total (PC, address) pairs: " << total_pairs << "\n"
            << "  Avg addresses per PC: " << avg_addrs << "\n"
            << "  Min/Max addresses per PC: " << min_addrs << " / " << max_addrs << "\n"
            << "  Recommended fixed budget: " << total_pairs << " entries or ~" << (uint64_t)std::ceil(avg_addrs)
            << " per-PC with " << total_pcs << " PCs\n";
}

void CACHE::record_liveness_char(uint64_t pc, uint64_t install_cycle,
                                   uint64_t last_hit_cycle, uint64_t evict_cycle,
                                   bool accessed)
{
  auto& entry = pc_liveness_char[pc];
  entry.total++;
  if (!accessed) {
    entry.doa++;
    return;
  }
  // Halflife criterion: last hit in first half of residency → mostly-dead,
  // second half → mostly-alive.
  const uint64_t lifetime     = evict_cycle - install_cycle;
  const uint64_t time_til_end = evict_cycle - last_hit_cycle;
  if (lifetime == 0 || time_til_end <= lifetime / 2)
    entry.mostly_alive++;
  else
    entry.mostly_dead++;
}

void CACHE::print_liveness_char() const
{
  if (!liveness_char_enable || pc_liveness_char.empty())
    return;

  printf("%s LIVENESS_CHAR BEGIN\n", NAME.c_str());
  for (const auto& [pc, e] : pc_liveness_char) {
    printf("  PC=0x%016lx total=%lu doa=%lu mostly_dead=%lu mostly_alive=%lu\n",
           pc, e.total, e.doa, e.mostly_dead, e.mostly_alive);
  }
  printf("%s LIVENESS_CHAR END\n", NAME.c_str());
}

bool CACHE::handle_fill(const PACKET& fill_mshr)
{
  cpu = fill_mshr.cpu;

  // find victim
  auto [set_begin, set_end] = get_set_span(fill_mshr.address);
  auto way = std::find_if_not(set_begin, set_end, [](auto x) { return x.valid; });
  if (way == set_end) {
    way = std::next(set_begin, impl_find_victim(fill_mshr.cpu, fill_mshr.instr_id, get_set_index(fill_mshr.address), &*set_begin, fill_mshr.ip,
                                                fill_mshr.address, fill_mshr.type));

    // Replacement guidance: re-evaluate victim using bHIST dead_count signals.
    // Prefer evicting entries with high dead_count (entries that are often dead).
    if (repl_guidance_enable) {
      auto best_victim = way;
      uint64_t best_score = get_repl_guidance_score(best_victim->address, best_victim->dp_pc);

      for (auto it = set_begin; it != set_end; ++it) {
        if (!it->valid)
          continue;
        uint64_t score = get_repl_guidance_score(it->address, it->dp_pc);
        if (score > best_score) {
          best_victim = it;
          best_score = score;
        }
      }

      way = best_victim;
    }
  }

  // Predictor bypass: only fires when a valid entry would be displaced
  // (way->valid distinguishes eviction from filling a free slot).
  // On predictor bypass we do not redirect through the existing bypass code
  // path (way = set_end) because that path calls impl_update_replacement_state
  // with way_idx = NUM_WAY, which is out of bounds for LRU and semantically
  // wrong for any policy (no way was actually used). Instead we track the
  // bypass in a flag and handle it directly below.
  bool predictor_bypassed = false;
  if (way != set_end && way->valid) {
    uint64_t bypass_key = repl_hist_use_addr
        ? (fill_mshr.address >> OFFSET_BITS) : fill_mshr.ip;
    // STLB→LLC propagation (option a, cross-level): index the LLC bypass by the
    // STLB PC that bypassed this block's page. Require a PFQ hit — if the page was
    // never STLB-bypassed, the LLC predictor does not act on it.
    bool prop_ok = true;
    if (stlb_llc_prop_ && NAME == "LLC") {
      if (prop_gate_pc_) {
        // PC-gate: gate by the block's own PC being STLB-dead; index by own PC.
        if (!stlb_dead_pcs.count(fill_mshr.ip) && !prop_hybrid_)
          prop_ok = false;                           // not STLB-dead PC → don't predict (unless hybrid)
        // bypass_key stays own PC (fill_mshr.ip)
      } else {
        // PFN-gate (page-granular): index by the propagated STLB PC.
        const auto pfn = fill_mshr.address >> LOG2_PAGE_SIZE;
        const auto mit = prop_map.find(pfn);
        if (mit != prop_map.end()) {
          if (!prop_ownpc_) bypass_key = mit->second;  // A/B: STLB PC; D: keep own PC
        } else if (!prop_hybrid_) {
          prop_ok = false;                             // A/D: gate on miss; B: keep own PC
        }
      }
    }
    // DoA classification first; then, if a periodic recheck is due, suppress the
    // bypass so this fill is inserted as a probe and yields fresh eviction data.
    const bool lv_doa = liveness_bypass && NAME == "LLC"
        && fill_mshr.type != TRANSLATION && prop_ok
        && repl_hist_pc.classify(bypass_key, bypass_thd, 0) == liveness_class::doa;
    const bool lv_probe  = lv_doa && repl_hist_pc.should_probe(bypass_key);
    const bool lv_bypass = lv_doa && !lv_probe;
    if (lv_probe) sim_stats.back().liveness_probes++;
    if (lv_bypass) {
      sim_stats.back().liveness_bypasses++;
      if (bypass_fire_reset_period_ > 0 &&
          ++bypass_fire_count_ % bypass_fire_reset_period_ == 0)
        repl_hist_pc.reset_scores();
      repl_hist_pc.record_bypass(bypass_key);
      shadow_record_bypass(fill_mshr.address >> OFFSET_BITS, fill_mshr.ip, fill_mshr.data);
    }

    const bool stlb_lv_doa = stlb_liveness_bypass && NAME == "cpu0_STLB"
        && repl_hist_pc.classify(fill_mshr.ip, stlb_bypass_thd, 0) == liveness_class::doa;
    const bool stlb_lv_probe  = stlb_lv_doa && repl_hist_pc.should_probe(fill_mshr.ip);
    const bool stlb_lv_bypass = stlb_lv_doa && !stlb_lv_probe;
    if (stlb_lv_probe) sim_stats.back().liveness_probes++;
    if (stlb_lv_bypass) {
      sim_stats.back().liveness_bypasses++;
      repl_hist_pc.record_bypass(fill_mshr.ip);
      shadow_record_bypass(fill_mshr.address >> OFFSET_BITS, fill_mshr.ip, fill_mshr.data);
      if (stlb_llc_prop_) {  // propagate to the LLC: PFN→(STLB PC) for the PFN-gate,
        prop_map[fill_mshr.data >> LOG2_PAGE_SIZE] = fill_mshr.ip;  // and the PC itself
        stlb_dead_pcs.insert(fill_mshr.ip);                          // for the PC-gate
      }
    }

    const bool bypassed =
      (dppred && NAME == "cpu0_STLB" && dppred_bypass(fill_mshr)) ||
      (cbpred && NAME == "LLC" && fill_mshr.type != TRANSLATION && cbpred_bypass(fill_mshr)) ||
      lv_bypass || stlb_lv_bypass;

    if (bypassed) {
      predictor_bypassed = true;
      way = set_end;
    } else {
      // Compute liveness class using halflife criterion.
      liveness_class evict_lv;
      if (!way->accessed) {
        evict_lv = liveness_class::doa;
      } else {
        const uint64_t lifetime     = current_cycle - way->install_cycle;
        const uint64_t time_til_end = current_cycle - way->last_hit_cycle;
        evict_lv = (lifetime == 0 || time_til_end <= lifetime / 2)
                   ? liveness_class::mostly_alive : liveness_class::mostly_dead;
      }
      update_eviction_counters(*way, evict_lv);
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
      auto evicting_address = (ever_seen_data ? way->address : way->v_address) & ~champsim::bitmask(match_offset_bits ? 0 : OFFSET_BITS);

      if (way->prefetch)
        sim_stats.back().pf_useless++;

      if (fill_mshr.type == PREFETCH)
        sim_stats.back().pf_fill++;

      if (way->valid) {
        sim_stats.back().evictions++;
        if (liveness_char_enable)
          record_liveness_char(way->ip, way->install_cycle, way->last_hit_cycle,
                               current_cycle, way->accessed);
        if (!way->accessed) {
          sim_stats.back().doa++;
          // LLC only: reverse-STLB lookup — find the STLB entry for this block's
          // virtual page and check whether it is also unaccessed (DoA).
          if (NAME == "LLC" && stlb_block_ptr != nullptr) {
            const uint64_t vpn = way->v_address >> LOG2_PAGE_SIZE;
            for (const auto& sb : *stlb_block_ptr) {
              if (sb.valid && (sb.v_address >> LOG2_PAGE_SIZE) == vpn) {
                sim_stats.back().doa_stlb_found++;
                if (!sb.accessed)
                  sim_stats.back().doa_stlb_also_doa++;
                break;
              }
            }
          }
        } else {
          const uint64_t lifetime     = current_cycle - way->install_cycle;
          const uint64_t time_til_end = current_cycle - way->last_hit_cycle;
          if (lifetime == 0 || time_til_end <= lifetime / 2)
            sim_stats.back().mostly_alive++;
          else
            sim_stats.back().mostly_dead++;
        }
      }

      way->valid = true;
      way->prefetch = fill_mshr.prefetch_from_this;
      way->dirty = (fill_mshr.type == WRITE);
      way->accessed = false;
      {
        const auto pfn_fill = fill_mshr.address >> LOG2_PAGE_SIZE;
        const auto pit = std::find_if(pfq.begin(), pfq.end(),
                                      [pfn_fill](const auto& e){ return e.first == pfn_fill; });
        way->dp    = cbpred && NAME == "LLC" && fill_mshr.type != TRANSLATION && pit != pfq.end();
        way->dp_pc = way->dp ? pit->second : 0;
        if (way->dp)
          sim_stats.back().pfq_hits++;
        // STLB→LLC propagation: remember the propagated STLB PC so the eviction
        // update indexes repl_hist by the same key used for the fill-time decision.
        way->prop_pc = 0;
        if (stlb_llc_prop_ && NAME == "LLC" && fill_mshr.type != TRANSLATION) {
          if (prop_gate_pc_) {
            // PC-gate: gated-in (and indexed) by own PC if it is STLB-dead.
            if (stlb_dead_pcs.count(fill_mshr.ip)) way->prop_pc = fill_mshr.ip;
          } else {
            const auto mit = prop_map.find(pfn_fill);
            if (mit != prop_map.end()) way->prop_pc = mit->second;
          }
        }
      }
      way->address = fill_mshr.address;
      way->v_address = fill_mshr.v_address;
      way->data = fill_mshr.data;
      way->ip = fill_mshr.ip;
      way->install_cycle  = current_cycle;
      way->last_hit_cycle = current_cycle;
      way->ins_class = classify_block_liveness(fill_mshr.address, fill_mshr.ip);

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
    // COLLECT STATS
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
    // A writeback hit is dirty data landing from L2, not a read of the block,
    // so it is not evidence of read reuse. We therefore do not update the
    // liveness signals on writeback hits: neither the Accessed bit (which
    // distinguishes DoA from reused blocks) nor last_hit_cycle (which drives
    // the mostly-dead vs mostly-alive halflife split). This keeps the liveness
    // classification based on genuine reads only. Both fields are used solely
    // by the LLC/STLB liveness mechanism.
    if (handle_pkt.type != WRITE) {
      if (NAME == "cpu0_STLB" || NAME == "LLC")
        way->accessed = true;
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

    // Liveness-bypass shadow: a re-reference to a block our predictor bypassed
    // is a confirmed mistake. Delete the PC's history entry and reinsert the
    // block (STLB: serve the stored translation, skipping the PTW → returns true).
    if (liveness_bypass_shadow_hit(handle_pkt))
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
  impl_prefetcher_initialize();
  impl_initialize_replacement();
  if (NAME == "cpu0_STLB")
    stlb_block_ptr = &block;
}

void CACHE::begin_phase()
{
  roi_stats.emplace_back();
  sim_stats.emplace_back();

  roi_stats.back().name = NAME;
  sim_stats.back().name = NAME;

  // Reset history table stats so ROI counts are clean (exclude warmup).
  phist.reset_stats();
  bhist_flat.reset_stats();
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

  roi_stats.back().llt_bypasses            = sim_stats.back().llt_bypasses;
  roi_stats.back().llc_bypasses            = sim_stats.back().llc_bypasses;
  roi_stats.back().pfq_hits                = sim_stats.back().pfq_hits;
  roi_stats.back().cbpred_nogate_bypasses  = sim_stats.back().cbpred_nogate_bypasses;
  roi_stats.back().liveness_bypasses       = sim_stats.back().liveness_bypasses;
  roi_stats.back().liveness_probes         = sim_stats.back().liveness_probes;
  roi_stats.back().liveness_bypass_shadow_hits = sim_stats.back().liveness_bypass_shadow_hits;

  roi_stats.back().evictions    = sim_stats.back().evictions;
  roi_stats.back().doa          = sim_stats.back().doa;
  roi_stats.back().mostly_dead  = sim_stats.back().mostly_dead;
  roi_stats.back().mostly_alive = sim_stats.back().mostly_alive;
  roi_stats.back().doa_stlb_found    = sim_stats.back().doa_stlb_found;
  roi_stats.back().doa_stlb_also_doa = sim_stats.back().doa_stlb_also_doa;

  // History table utilisation stats (accumulated since begin_phase reset).
  {
    const auto& ps = phist.get_stats();
    roi_stats.back().phist_queries       = ps.queries;
    roi_stats.back().phist_table_hits    = ps.table_hits;
    roi_stats.back().phist_promotions    = ps.promotions;
    roi_stats.back().phist_promoted_hits = ps.promoted_hits;
    const auto& bs = bhist_flat.get_stats();
    roi_stats.back().bhist_queries       = bs.queries;
    roi_stats.back().bhist_table_hits    = bs.table_hits;
    roi_stats.back().bhist_promotions    = bs.promotions;
    roi_stats.back().bhist_promoted_hits = bs.promoted_hits;
  }

  print_characterization_stats();
  print_liveness_char();
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
