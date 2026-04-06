#include <iostream>
#include <deque>
#include <utility>

#include "cache.h"

// Pending prefetches buffered during prefetcher_cache_operate().
// Drained by prefetcher_cycle_operate() after all queue iteration is done.
static std::deque<std::pair<uint64_t, uint32_t>> nli_pending; // (pf_addr, metadata)
static CACHE* nli_owner = nullptr;

void CACHE::prefetcher_initialize() { std::cout << NAME << " next line prefetcher" << std::endl; }

void CACHE::prefetcher_branch_operate(uint64_t ip, uint8_t branch_type, uint64_t branch_target) {}

uint32_t CACHE::prefetcher_cache_operate(uint64_t addr, uint64_t ip, uint8_t cache_hit, uint8_t type, uint32_t metadata_in)
{
  // Do NOT call prefetch_line here — it inserts into queues.PQ while
  // operate_queue() holds iterators into it, causing std::deque iterator
  // invalidation. Buffer and drain safely in prefetcher_cycle_operate().
  if (nli_owner != this) {
    nli_pending.clear();
    nli_owner = this;
  }
  uint64_t pf_addr = addr + (1 << LOG2_BLOCK_SIZE);
  nli_pending.emplace_back(pf_addr, metadata_in);
  return metadata_in;
}

uint32_t CACHE::prefetcher_cache_fill(uint64_t addr, uint32_t set, uint32_t way, uint8_t prefetch, uint64_t evicted_addr, uint32_t metadata_in)
{
  return metadata_in;
}

void CACHE::prefetcher_cycle_operate()
{
  for (auto& [pf_addr, metadata] : nli_pending)
    prefetch_line(pf_addr, true, metadata);
  nli_pending.clear();
}

void CACHE::prefetcher_final_stats() {}
