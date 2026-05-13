#!/usr/bin/env bash
# build_all.sh — Build all per-policy ChampSim binaries.
#
# Each config in configs/ overrides executable_name, replacement policies for
# STLB and LLC, and optionally prefetchers for L1I/L1D/L2C (--pref variants).
#
# Usage:
#   ./build_all.sh                        # Build all binaries (default: nopref + pref)
#   ./build_all.sh --nopref               # Build only the no-prefetch variants
#   ./build_all.sh --pref                 # Build only the prefetch variants (L1I=next_line_instr, L1D=ip_stride, L2C=spp_dev)
#   ./build_all.sh --paper-pref           # Build only the paper-prefetch variants (L1I=epi_instr, L1D=berti, L2C=next_line)
#   ./build_all.sh lru lru_mid            # Build specific policies (both pref and no-pref variants)
#   ./build_all.sh --nopref stlb_lru_mid   # Build STLB-only mid-insertion binary (lru_mid STLB, LRU LLC)
#   ./build_all.sh --nopref lru_mid_both   # Build LLC+STLB mid-insertion binary (lru_mid in both caches)
#
# Outputs (in ./bin/):
#   No-prefetch:
#     champsim_lru           — LRU for STLB and LLC
#     champsim_lru_mid       — LRU for STLB, mid-insertion LRU for LLC
#     champsim_srrip         — LRU for STLB, SRRIP for LLC
#     champsim_srrip_live    — LRU for STLB, liveness-informed SRRIP for LLC
#     champsim_drrip         — LRU for STLB, DRRIP for LLC
#   STLB-only (built with --nopref stlb_lru_mid / stlb_srrip / stlb_srrip_live):
#     champsim_stlb_lru_mid   — mid-insertion LRU for STLB, LRU for LLC
#     champsim_stlb_srrip     — SRRIP for STLB, LRU for LLC
#     champsim_stlb_srrip_live — srrip_live for STLB, LRU for LLC
#   LLC+STLB (built with --nopref lru_mid_both):
#     champsim_lru_mid_both  — mid-insertion LRU for both STLB and LLC
#   With-prefetch (L1I=next_line_instr, L1D=ip_stride, L2C=spp_dev):
#     champsim_lru_pref      — LRU (STLB+LLC) + next_line_instr/ip_stride/spp_dev
#     champsim_lru_mid_pref  — LRU STLB, lru_mid LLC + next_line_instr/ip_stride/spp_dev
#     champsim_srrip_pref    — LRU STLB, SRRIP LLC + next_line_instr/ip_stride/spp_dev
#     champsim_srrip_live_pref — LRU STLB, srrip_live LLC + next_line_instr/ip_stride/spp_dev
#     champsim_drrip_pref    — LRU STLB, DRRIP LLC + next_line_instr/ip_stride/spp_dev
#   With-paper-prefetch (L1I=epi_instr, L1D=berti, L2C=next_line — matches PACIPV ISCA'25):
#     champsim_lru_paper_pref      — LRU + epi_instr/berti/next_line
#     champsim_lru_mid_paper_pref  — lru_mid + epi_instr/berti/next_line
#     champsim_srrip_paper_pref    — SRRIP + epi_instr/berti/next_line
#     champsim_srrip_live_paper_pref — srrip_live + epi_instr/berti/next_line
#     champsim_drrip_paper_pref    — DRRIP + epi_instr/berti/next_line

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ALL_POLICIES=(lru lru_mid srrip srrip_live drrip)

BUILD_NOPREF=1
BUILD_PREF=1
BUILD_PAPER_PREF=0
EXPLICIT_POLICIES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pref)        BUILD_NOPREF=0; BUILD_PAPER_PREF=0; shift ;;
    --nopref)      BUILD_PREF=0; BUILD_PAPER_PREF=0; shift ;;
    --paper-pref)  BUILD_NOPREF=0; BUILD_PREF=0; BUILD_PAPER_PREF=1; shift ;;
    *)             EXPLICIT_POLICIES+=("$1"); shift ;;
  esac
done

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
if [ "${BUILD_NOPREF}" -eq 1 ]; then
  for policy in "${EXPLICIT_POLICIES[@]}"; do
    echo "=== Building ${policy} (no prefetch) ==="
    build_one "${policy}" "configs/${policy}.json"
    echo "  → bin/champsim_${policy}"
    echo ""
  done
fi

# Build with-prefetch variants.
if [ "${BUILD_PREF}" -eq 1 ]; then
  for policy in "${EXPLICIT_POLICIES[@]}"; do
    echo "=== Building ${policy}_pref (next_line_instr + ip_stride + spp_dev) ==="
    build_one "${policy}_pref" "configs/${policy}_pref.json"
    echo "  → bin/champsim_${policy}_pref"
    echo ""
  done
fi

# Build with-paper-prefetch variants (EPI + Berti + next_line, matching PACIPV ISCA'25).
if [ "${BUILD_PAPER_PREF}" -eq 1 ]; then
  for policy in "${EXPLICIT_POLICIES[@]}"; do
    echo "=== Building ${policy}_paper_pref (epi_instr + berti + next_line) ==="
    build_one "${policy}_paper_pref" "configs/${policy}_paper_pref.json"
    echo "  → bin/champsim_${policy}_paper_pref"
    echo ""
  done
fi

echo "Done. Binaries in ./bin/:"
ls -lh bin/champsim_* 2>/dev/null || echo "  (none found — check build output above)"
