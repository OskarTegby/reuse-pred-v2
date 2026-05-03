#include <catch.hpp>
#include "hist_lru.h"

#include <map>
#include <cstdint>

namespace {
  struct entry_t {
    uint64_t last_access = 0;
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

// Set-associative tests.
// The pattern under test mirrors get_bhist_entry:
//   lru_access(outer[key % sets], key, ways, clock)

TEST_CASE("set-associative: keys in different sets do not evict each other") {
  std::map<uint64_t, std::map<uint64_t, entry_t>> m;
  uint64_t clock = 0;
  const uint64_t sets = 2;
  const std::size_t ways = 1;

  lru_access(m[0 % sets], uint64_t{0}, ways, clock);  // set 0
  lru_access(m[1 % sets], uint64_t{1}, ways, clock);  // set 1

  REQUIRE(m[0].size() == 1);
  REQUIRE(m[1].size() == 1);
}

TEST_CASE("set-associative: keys in the same set cause a conflict eviction") {
  std::map<uint64_t, std::map<uint64_t, entry_t>> m;
  uint64_t clock = 0;
  const uint64_t sets = 2;
  const std::size_t ways = 1;

  lru_access(m[0 % sets], uint64_t{0}, ways, clock);  // set 0
  lru_access(m[2 % sets], uint64_t{2}, ways, clock);  // set 0 again (2%2==0), evicts key 0

  REQUIRE(m[0].size() == 1);
  REQUIRE(m[0].count(0) == 0);
  REQUIRE(m[0].count(2) == 1);
}

TEST_CASE("set-associative: sets=1 eliminates conflict misses") {
  std::map<uint64_t, std::map<uint64_t, entry_t>> m;
  uint64_t clock = 0;
  const uint64_t sets = 1;
  const std::size_t ways = 2;

  // Keys 0 and 2 would conflict under sets=2,ways=1 but coexist here
  lru_access(m[0 % sets], uint64_t{0}, ways, clock);
  lru_access(m[2 % sets], uint64_t{2}, ways, clock);

  REQUIRE(m[0].size() == 2);
  REQUIRE(m[0].count(0) == 1);
  REQUIRE(m[0].count(2) == 1);
}

TEST_CASE("set-associative: total capacity is sets x ways") {
  std::map<uint64_t, std::map<uint64_t, entry_t>> m;
  uint64_t clock = 0;
  const uint64_t sets = 2;
  const std::size_t ways = 3;

  // Fill exactly sets*ways entries with no evictions
  for (uint64_t k = 0; k < sets * ways; ++k)
    lru_access(m[k % sets], k, ways, clock);

  std::size_t total = 0;
  for (auto& [s, inner] : m) total += inner.size();
  REQUIRE(total == sets * ways);

  // One more entry triggers exactly one eviction
  lru_access(m[(sets * ways) % sets], uint64_t{sets * ways}, ways, clock);
  total = 0;
  for (auto& [s, inner] : m) total += inner.size();
  REQUIRE(total == sets * ways);
}
