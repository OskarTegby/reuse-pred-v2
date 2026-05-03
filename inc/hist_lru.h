#ifndef HIST_LRU_H
#define HIST_LRU_H

#include <algorithm>
#include <cassert>

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

#endif
