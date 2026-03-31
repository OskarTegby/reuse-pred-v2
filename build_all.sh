#!/usr/bin/env bash
# build_all.sh — Build all per-policy ChampSim binaries.
#
# Each config in configs/ overrides only executable_name and the replacement
# policies for STLB and LLC; all other settings come from champsim_config.json.
#
# Usage:
#   ./build_all.sh             # Build all four policies
#   ./build_all.sh lru srrip   # Build specific policies only
#
# Outputs (in ./bin/):
#   champsim_lru      — vanilla LRU for STLB and LLC
#   champsim_lru_mid  — mid-insertion LRU for STLB and LLC
#   champsim_srrip    — SRRIP for STLB and LLC
#   champsim_drrip    — DRRIP for STLB and LLC

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ALL_POLICIES=(lru lru_mid srrip drrip)

if [ $# -gt 0 ]; then
  POLICIES=("$@")
else
  POLICIES=("${ALL_POLICIES[@]}")
fi

for policy in "${POLICIES[@]}"; do
  cfg="configs/${policy}.json"
  if [ ! -f "$cfg" ]; then
    echo "ERROR: config not found: $cfg" >&2
    exit 2
  fi
  echo "=== Building ${policy} ==="
  python3 config.sh champsim_config.json "$cfg"
  make -j"$(nproc)"
  echo "  → bin/champsim_${policy}"
  echo ""
done

echo "Done. Binaries in ./bin/:"
ls -lh bin/champsim_* 2>/dev/null || echo "  (none found — check build output above)"
