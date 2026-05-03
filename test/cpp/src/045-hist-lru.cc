#include <catch.hpp>
#include "hist_lru.h"

#include <map>
#include <cstdint>

namespace {
  struct entry_t {
    uint64_t last_access = 0;
    uint64_t freq        = 0;
    uint64_t full_addr   = 0;
  };
}

TEST_CASE("evict_lru removes the entry with the smallest last_access") {
  std::map<uint64_t, entry_t> m;
  m[1] = {10};
  m[2] = {30};
  m[3] = {20};

  evict_lru(m);

  REQUIRE(m.size() == 2);
  REQUIRE(m.count(1) == 0);  // last_access=10 was LRU
  REQUIRE(m.count(2) == 1);
  REQUIRE(m.count(3) == 1);
}

TEST_CASE("evict_lru on a single-entry map leaves it empty") {
  std::map<uint64_t, entry_t> m;
  m[42] = {99};

  evict_lru(m);

  REQUIRE(m.empty());
}

TEST_CASE("evict_lru evicts the oldest of several equal-timestamp entries consistently") {
  std::map<uint64_t, entry_t> m;
  m[10] = {5};
  m[20] = {5};
  m[30] = {5};

  evict_lru(m);

  // std::min_element picks the first minimum — map iteration order is by key,
  // so key 10 (first in iteration) is evicted.
  REQUIRE(m.size() == 2);
  REQUIRE(m.count(10) == 0);
}

TEST_CASE("evict_lru respects insertion order when last_access is monotonically increasing") {
  std::map<uint64_t, entry_t> m;
  m[1] = {1};
  m[2] = {2};
  m[3] = {3};
  m[4] = {4};

  evict_lru(m);
  REQUIRE(m.count(1) == 0);

  evict_lru(m);
  REQUIRE(m.count(2) == 0);

  REQUIRE(m.size() == 2);
}

TEST_CASE("evict_lru does not remove a recently accessed entry") {
  std::map<uint64_t, entry_t> m;
  m[1] = {1};
  m[2] = {2};
  m[3] = {100};  // recently accessed

  evict_lru(m);

  REQUIRE(m.count(3) == 1);  // recently accessed entry survives
}

TEST_CASE("lru_access inserts a new entry and stamps it") {
  std::map<uint64_t, entry_t> m;
  uint64_t clock = 0;

  auto& e = lru_access(m, uint64_t{1}, std::size_t{4}, clock);

  REQUIRE(m.size() == 1);
  REQUIRE(clock == 1);
  REQUIRE(e.last_access == 1);
}

TEST_CASE("lru_access updates the clock on each call") {
  std::map<uint64_t, entry_t> m;
  uint64_t clock = 0;

  lru_access(m, uint64_t{1}, std::size_t{4}, clock);
  lru_access(m, uint64_t{2}, std::size_t{4}, clock);
  auto& e = lru_access(m, uint64_t{3}, std::size_t{4}, clock);

  REQUIRE(clock == 3);
  REQUIRE(e.last_access == 3);
}

TEST_CASE("lru_access does not evict when below capacity") {
  std::map<uint64_t, entry_t> m;
  uint64_t clock = 0;

  lru_access(m, uint64_t{1}, std::size_t{2}, clock);
  lru_access(m, uint64_t{2}, std::size_t{2}, clock);

  REQUIRE(m.size() == 2);
}

TEST_CASE("lru_access evicts the LRU entry when at capacity") {
  std::map<uint64_t, entry_t> m;
  uint64_t clock = 0;

  lru_access(m, uint64_t{1}, std::size_t{2}, clock);
  lru_access(m, uint64_t{2}, std::size_t{2}, clock);
  lru_access(m, uint64_t{3}, std::size_t{2}, clock);  // key 1 evicted

  REQUIRE(m.size() == 2);
  REQUIRE(m.count(1) == 0);
  REQUIRE(m.count(2) == 1);
  REQUIRE(m.count(3) == 1);
}

TEST_CASE("lru_access on an existing entry does not evict and updates its timestamp") {
  std::map<uint64_t, entry_t> m;
  uint64_t clock = 0;

  lru_access(m, uint64_t{1}, std::size_t{2}, clock);
  lru_access(m, uint64_t{2}, std::size_t{2}, clock);
  lru_access(m, uint64_t{1}, std::size_t{2}, clock);  // re-access key 1
  lru_access(m, uint64_t{3}, std::size_t{2}, clock);  // key 2 is now LRU, evicted

  REQUIRE(m.size() == 2);
  REQUIRE(m.count(1) == 1);
  REQUIRE(m.count(2) == 0);
  REQUIRE(m.count(3) == 1);
}

// addr_set / addr_tag / addr_reconstruct

TEST_CASE("addr_set returns low bits of address") {
  REQUIRE(addr_set(0b0000, 1) == 0);
  REQUIRE(addr_set(0b1111, 1) == 0);   // sets=1: everything goes to set 0

  REQUIRE(addr_set(0b1100, 4) == 0);   // low 2 bits = 00
  REQUIRE(addr_set(0b1101, 4) == 1);   // low 2 bits = 01
  REQUIRE(addr_set(0b1110, 4) == 2);   // low 2 bits = 10
  REQUIRE(addr_set(0b1111, 4) == 3);   // low 2 bits = 11
}

TEST_CASE("addr_tag returns high bits of address") {
  REQUIRE(addr_tag(42, 1) == 42);      // sets=1: tag is the full address

  REQUIRE(addr_tag(0b1101, 4) == 0b11);  // high bits after stripping 2 set bits
  REQUIRE(addr_tag(0b0100, 4) == 0b01);
}

TEST_CASE("addr_reconstruct is the inverse of addr_set/addr_tag") {
  for (uint64_t sets : {uint64_t{1}, uint64_t{2}, uint64_t{4}, uint64_t{8}, uint64_t{16}}) {
    for (uint64_t addr : {uint64_t{0}, uint64_t{1}, uint64_t{7}, uint64_t{13}, uint64_t{255}, uint64_t{1024}}) {
      REQUIRE(addr_reconstruct(addr_set(addr, sets), addr_tag(addr, sets), sets) == addr);
    }
  }
}

// Set-associative tests using addr_set / addr_tag as inner key.
// The pattern under test mirrors get_bhist_entry:
//   lru_access(outer[addr_set(key, sets)], addr_tag(key, sets), ways, clock)

TEST_CASE("set-associative: keys in different sets do not evict each other") {
  std::map<uint64_t, std::map<uint64_t, entry_t>> m;
  uint64_t clock = 0;
  const uint64_t    sets = 2;
  const std::size_t ways = 1;

  lru_access(m[addr_set(0, sets)], addr_tag(0, sets), ways, clock);  // set 0
  lru_access(m[addr_set(1, sets)], addr_tag(1, sets), ways, clock);  // set 1

  REQUIRE(m[0].size() == 1);
  REQUIRE(m[1].size() == 1);
}

TEST_CASE("set-associative: keys in the same set cause a conflict eviction") {
  std::map<uint64_t, std::map<uint64_t, entry_t>> m;
  uint64_t clock = 0;
  const uint64_t    sets = 2;
  const std::size_t ways = 1;

  // addr=0 → set=0, tag=0; addr=2 → set=0, tag=1; both map to set 0
  lru_access(m[addr_set(0, sets)], addr_tag(0, sets), ways, clock);
  lru_access(m[addr_set(2, sets)], addr_tag(2, sets), ways, clock);  // evicts tag 0

  REQUIRE(m[0].size() == 1);
  REQUIRE(m[0].count(addr_tag(0, sets)) == 0);
  REQUIRE(m[0].count(addr_tag(2, sets)) == 1);
}

TEST_CASE("set-associative: sets=1 eliminates conflict misses") {
  std::map<uint64_t, std::map<uint64_t, entry_t>> m;
  uint64_t clock = 0;
  const uint64_t    sets = 1;
  const std::size_t ways = 2;

  // Addresses 0 and 2 would conflict under sets=2,ways=1 but coexist here
  lru_access(m[addr_set(0, sets)], addr_tag(0, sets), ways, clock);
  lru_access(m[addr_set(2, sets)], addr_tag(2, sets), ways, clock);

  REQUIRE(m[0].size() == 2);
  REQUIRE(m[0].count(addr_tag(0, sets)) == 1);
  REQUIRE(m[0].count(addr_tag(2, sets)) == 1);
}

TEST_CASE("set-associative: total capacity is sets x ways") {
  std::map<uint64_t, std::map<uint64_t, entry_t>> m;
  uint64_t clock = 0;
  const uint64_t    sets = 2;
  const std::size_t ways = 3;

  // Fill exactly sets*ways entries with no evictions
  for (uint64_t k = 0; k < sets * ways; ++k)
    lru_access(m[addr_set(k, sets)], addr_tag(k, sets), ways, clock);

  std::size_t total = 0;
  for (auto& [s, inner] : m) total += inner.size();
  REQUIRE(total == sets * ways);

  // One more entry triggers exactly one eviction
  const uint64_t extra = sets * ways;
  lru_access(m[addr_set(extra, sets)], addr_tag(extra, sets), ways, clock);
  total = 0;
  for (auto& [s, inner] : m) total += inner.size();
  REQUIRE(total == sets * ways);
}

TEST_CASE("set-associative: full_addr round-trips through set and tag") {
  std::map<uint64_t, std::map<uint64_t, entry_t>> m;
  uint64_t clock = 0;
  const uint64_t    sets = 4;
  const std::size_t ways = 8;

  for (uint64_t addr : {uint64_t{0}, uint64_t{1}, uint64_t{13}, uint64_t{255}}) {
    auto& e = lru_access(m[addr_set(addr, sets)], addr_tag(addr, sets), ways, clock);
    e.full_addr = addr;
    REQUIRE(addr_reconstruct(addr_set(addr, sets), addr_tag(addr, sets), sets) == e.full_addr);
  }
}

// lfu_access counter mechanics

TEST_CASE("lfu_access inserts a new entry with freq=1") {
  std::map<uint64_t, entry_t> m;

  auto& e = lfu_access(m, uint64_t{1});

  REQUIRE(m.size() == 1);
  REQUIRE(e.freq == 1);
}

TEST_CASE("lfu_access increments freq on each re-access") {
  std::map<uint64_t, entry_t> m;

  lfu_access(m, uint64_t{1});
  lfu_access(m, uint64_t{1});
  auto& e = lfu_access(m, uint64_t{1});

  REQUIRE(e.freq == 3);
}

TEST_CASE("lfu_access resets freq to 1 when a key is re-inserted after erasure") {
  std::map<uint64_t, entry_t> m;

  lfu_access(m, uint64_t{1});
  lfu_access(m, uint64_t{1});  // freq=2
  m.erase(1);

  auto& e = lfu_access(m, uint64_t{1});  // fresh insertion
  REQUIRE(e.freq == 1);
}
