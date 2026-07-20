// Shared IPV (Insertion/Promotion Vector) mechanism used by both ipv.cc (the
// plain baseline) and ipv_live.cc (the liveness-guided variant): the default
// vectors, env-var vector parsing, and the permutation-shift move used for
// both hit-promotion and fill-insertion. Included separately by each .cc
// file (inside its own anonymous namespace scope via the include), so each
// still gets its own private copy -- this only removes the duplicated
// source text, not the per-translation-unit instantiation.

#pragma once

#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

const std::vector<int> kDefaultIpv16 = {
    0, 0, 2, 8, 4, 1, 4, 1, 8, 0, 14, 8, 12, 13, 14, 9, 5
};

// WI-GIPPR-16 resampled to k=12: position p_old = round(p * 15/11) for each
// new position p in 0..11, value rescaled by 12/16 and clamped to [0, 11].
const std::vector<int> kDefaultIpv12 = {
    0, 0, 6, 3, 1, 1, 6, 10, 6, 9, 10, 7, 4
};

std::vector<int> trivial_ipv(std::size_t k)
{
  std::vector<int> v(k + 1, 0);
  v[k] = static_cast<int>(k) - 1;
  return v;
}

std::vector<int> default_ipv(std::size_t k)
{
  if (k == 16) return kDefaultIpv16;
  if (k == 12) return kDefaultIpv12;
  return trivial_ipv(k);
}

// Parses `var` for a k-way cache; falls back to `dflt` if unset, malformed,
// wrong length, or containing an out-of-range position.
std::vector<int> parse_ipv_env(const char* var, std::size_t k, const std::vector<int>& dflt)
{
  const char* s = std::getenv(var);
  if (!s || !*s) return dflt;
  std::string buf(s);
  std::vector<int> v;
  v.reserve(k + 1);
  char* tok = std::strtok(buf.data(), ",: ");
  while (tok) {
    v.push_back(std::atoi(tok));
    tok = std::strtok(nullptr, ",: ");
  }
  if (v.size() != k + 1) return dflt;
  for (int p : v) if (p < 0 || p >= static_cast<int>(k)) return dflt;
  return v;
}

// Moves the block at position `from` to position `to`, shifting the blocks
// in between by one to close the gap. `order[p]` = way at position p;
// `rank[w]` = position of way w. Both are kept in sync.
void move_to(uint16_t* order, uint16_t* rank, int from, int to)
{
  if (from == to) return;
  const uint16_t way = order[from];
  if (to < from) {
    for (int p = from; p > to; --p) { order[p] = order[p - 1]; rank[order[p]] = static_cast<uint16_t>(p); }
  } else {
    for (int p = from; p < to; ++p) { order[p] = order[p + 1]; rank[order[p]] = static_cast<uint16_t>(p); }
  }
  order[to] = way;
  rank[way] = static_cast<uint16_t>(to);
}
