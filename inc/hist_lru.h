#ifndef HIST_LRU_H
#define HIST_LRU_H

#include <algorithm>
#include <cassert>
#include <cstdint>

// Address decomposition for set-associative history tables.
// Sets must be a power of 2.  Low bits of addr are the set index;
// remaining high bits are the tag.  set | tag → full addr (no overlap).

inline void assert_power_of_two(uint64_t sets)
{
  assert(sets > 0 && (sets & (sets - 1)) == 0);
}

inline uint64_t addr_set(uint64_t addr, uint64_t sets)
{
  assert_power_of_two(sets);
  return addr & (sets - 1);
}

inline uint64_t addr_tag(uint64_t addr, uint64_t sets)
{
  assert_power_of_two(sets);
  return addr >> __builtin_ctzll(sets);
}

// Reconstruct the original address from its set index and tag.
inline uint64_t addr_reconstruct(uint64_t set, uint64_t tag, uint64_t sets)
{
  assert_power_of_two(sets);
  return (tag << __builtin_ctzll(sets)) | set;
}

// Evicts the entry with the smallest last_access timestamp from map.
// Map must be a std::map<Key, Value> where Value has a uint64_t last_access field.
// Assumes map is non-empty.
template <typename Map>
void evict_lru(Map& map)
{
  assert(!map.empty());
  auto lru = std::min_element(map.begin(), map.end(),
    [](const auto& a, const auto& b) { return a.second.last_access < b.second.last_access; });
  map.erase(lru);
}

// Accesses or inserts key in map, evicting the LRU entry first if the map is
// at capacity.  Stamps the accessed entry with ++clock and returns a reference.
template <typename Map, typename Key>
typename Map::mapped_type& lru_access(Map& map, const Key& key, std::size_t capacity, uint64_t& clock)
{
  if (!map.count(key) && map.size() >= capacity)
    evict_lru(map);
  auto& e = map[key];
  e.last_access = ++clock;
  return e;
}

// Evicts the entry with the smallest freq counter from map.
// Map must be a std::map<Key, Value> where Value has a uint64_t freq field.
// Assumes map is non-empty.
template <typename Map>
void evict_lfu(Map& map)
{
  assert(!map.empty());
  auto lfu = std::min_element(map.begin(), map.end(),
    [](const auto& a, const auto& b) { return a.second.freq < b.second.freq; });
  map.erase(lfu);
}

// Accesses or inserts key in map, evicting the LFU entry first if the map is
// at capacity.  Increments the accessed entry's freq and returns a reference.
template <typename Map, typename Key>
typename Map::mapped_type& lfu_access(Map& map, const Key& key, std::size_t capacity)
{
  if (!map.count(key) && map.size() >= capacity)
    evict_lfu(map);
  auto& e = map[key];
  ++e.freq;
  return e;
}

#endif
