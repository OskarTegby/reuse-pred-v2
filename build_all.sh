#!/usr/bin/env bash
# build_all.sh — Build all per-policy ChampSim binaries.
#
# Each config in configs/ overrides executable_name, replacement policies for
# STLB and LLC, and optionally prefetchers for L1D/L2C (--pref variants).
#
# Usage:
#   ./build_all.sh               # Build all four no-prefetch policies
#   ./build_all.sh --pref        # Build all four prefetch variants (ip_stride+spp_dev)
#   ./build_all.sh --all         # Build all eight (no-pref + pref)
#   ./build_all.sh lru srrip     # Build specific no-prefetch policies only
#
# Outputs (in ./bin/):
#   No-prefetch (L1D=no, L2C=no):
#     champsim_lru      — vanilla LRU for STLB and LLC
#     champsim_lru_mid  — mid-insertion LRU for STLB and LLC
#     champsim_srrip    — SRRIP for STLB and LLC
#     champsim_drrip    — DRRIP for STLB and LLC
#   With-prefetch (L1D=ip_stride, L2C=spp_dev):
#     champsim_lru_pref      — LRU + ip_stride/spp_dev
#     champsim_lru_mid_pref  — lru_mid + ip_stride/spp_dev
#     champsim_srrip_pref    — SRRIP + ip_stride/spp_dev
#     champsim_drrip_pref    — DRRIP + ip_stride/spp_dev

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ALL_POLICIES=(lru lru_mid srrip drrip)

PREF=0
BUILD_ALL=0
EXPLICIT_POLICIES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pref) PREF=1; shift ;;
    --all)  BUILD_ALL=1; shift ;;
    *)      EXPLICIT_POLICIES+=("$1"); shift ;;
  esac
done

if [ "${BUILD_ALL}" -eq 1 ]; then
  PREF=1
  EXPLICIT_POLICIES=("${ALL_POLICIES[@]}")
fi

if [ ${#EXPLICIT_POLICIES[@]} -eq 0 ]; then
  EXPLICIT_POLICIES=("${ALL_POLICIES[@]}")
fi

build_one() {
  local policy="$1"
  local cfg="$2"
  if [ ! -f "$cfg" ]; then
    echo "ERROR: config not found: $cfg" >&2
    exit 2
  fi
  python3 config.sh champsim_config.json "$cfg"
  make static -j"$(nproc)"
}

# Build no-prefetch variants.
if [ "${PREF}" -eq 0 ] || [ "${BUILD_ALL}" -eq 1 ]; then
  for policy in "${EXPLICIT_POLICIES[@]}"; do
    echo "=== Building ${policy} (no prefetch) ==="
    build_one "${policy}" "configs/${policy}.json"
    echo "  → bin/champsim_${policy}"
    echo ""
  done
fi

# Build with-prefetch variants.
if [ "${PREF}" -eq 1 ]; then
  for policy in "${EXPLICIT_POLICIES[@]}"; do
    echo "=== Building ${policy}_pref (ip_stride + spp_dev) ==="
    build_one "${policy}_pref" "configs/${policy}_pref.json"
    echo "  → bin/champsim_${policy}_pref"
    echo ""
  done
fi

echo "Done. Binaries in ./bin/:"
ls -lh bin/champsim_* 2>/dev/null || echo "  (none found — check build output above)"
