// Shared SRRIP victim-search mechanism used by both srrip.cc (the plain
// baseline) and srrip_live.cc (the liveness-guided variant). This is the
// aging-loop scan every SRRIP-family policy uses to find a victim: look for
// a way at maxRRPV; if none, age every way in the set (increment its RRPV)
// and retry.

#pragma once

#include <algorithm>
#include <iterator>

namespace srrip_common {

// Finds the way with rrpv == maxRRPV in [begin, end), aging every way in the
// range and retrying until one is found. `on_age_loop` is invoked once per
// aging pass (srrip_live.cc uses it to count aging loops for stats; pass a
// no-op for callers that don't track this).
template <typename Iter, typename OnAgeLoop>
Iter find_rrpv_victim(Iter begin, Iter end, int maxRRPV, OnAgeLoop on_age_loop)
{
  Iter victim = std::find(begin, end, maxRRPV);
  while (victim == end) {
    on_age_loop();
    for (auto it = begin; it != end; ++it)
      ++(*it);
    victim = std::find(begin, end, maxRRPV);
  }
  return victim;
}

} // namespace srrip_common
