#!/usr/bin/env bash
# build_cache_size_study.sh — generate configs and build cache/TLB size-study binaries.
#
# Each component is varied independently: half size (÷2) and double size (×2),
# with all other components held at their baseline values.  All binaries use
# plain LRU so measured liveness reflects the unmodified eviction distribution.
#
# Baselines (from champsim_config.json):
#   LLC   : 2048 sets × 16 ways = 2 MB
#   L2C   : 512  sets × 8  ways = 256 KB
#   STLB  : 128  sets × 8  ways = 1024 entries
#   DTLB  : 16   sets × 4  ways = 64   entries
#   ITLB  : 32   sets × 4  ways = 128  entries
#
# Generated binaries (in ./bin/):
#   champsim_lru                 — baseline (already built by build_all.sh)
#   champsim_lru_llc_half        — LLC ÷ 2  (1024 sets)
#   champsim_lru_llc_double      — LLC × 2  (4096 sets)
#   champsim_lru_l2c_half        — L2C ÷ 2  (256 sets)
#   champsim_lru_l2c_double      — L2C × 2  (1024 sets)
#   champsim_lru_stlb_half       — STLB ÷ 2 (64 sets)
#   champsim_lru_stlb_double     — STLB × 2 (256 sets)
#   champsim_lru_dtlb_half       — DTLB ÷ 2 (8 sets)
#   champsim_lru_dtlb_double     — DTLB × 2 (32 sets)
#   champsim_lru_itlb_half       — ITLB ÷ 2 (16 sets)
#   champsim_lru_itlb_double     — ITLB × 2 (64 sets)
#
# Usage:
#   ./scripts/build_cache_size_study.sh            # build everything
#   ./scripts/build_cache_size_study.sh --dry-run  # print configs, no build
#   ./scripts/build_cache_size_study.sh llc stlb   # build specific components only

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

TMPDIR_CONFIGS="${PROJECT_ROOT}/.cache_size_configs"
mkdir -p "$TMPDIR_CONFIGS"

DRY_RUN=0
SELECTED=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    llc|l2c|stlb|dtlb|itlb) SELECTED+=("$1"); shift ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 [--dry-run] [llc] [l2c] [stlb] [dtlb] [itlb]" >&2
       exit 2 ;;
  esac
done

declare -A BASELINE=( [llc]=2048 [l2c]=512 [stlb]=128 [dtlb]=16 [itlb]=32 )
declare -A COMP_KEY=( [llc]=LLC [l2c]=L2C [stlb]=STLB [dtlb]=DTLB [itlb]=ITLB )

# Each component gets exactly two variants: half and double.
declare -A SWEEP=(
  [llc]="half:1024 double:4096"
  [l2c]="half:256  double:1024"
  [stlb]="half:64   double:256"
  [dtlb]="half:8    double:32"
  [itlb]="half:16   double:64"
)

if [ ${#SELECTED[@]} -eq 0 ]; then
  SELECTED=(llc l2c stlb dtlb itlb)
fi

build_one() {
  local cfg_file="$1" bin_name="$2"
  echo "  → Building bin/${bin_name} ..."
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "    [dry-run] python3 config.sh champsim_config.json ${cfg_file} && make static"
    return 0
  fi
  python3 config.sh champsim_config.json "$cfg_file"
  make static -j"$(nproc)" 2>&1 | tail -3
}

total=0
for comp in "${SELECTED[@]}"; do
  echo "=== ${comp^^} (baseline: ${BASELINE[$comp]} sets) ==="
  for variant in ${SWEEP[$comp]}; do
    label="${variant%%:*}"   # "half" or "double"
    sets="${variant##*:}"    # number of sets
    ((total++)) || true
    bin_name="champsim_lru_${comp}_${label}"
    cfg_file="${TMPDIR_CONFIGS}/${bin_name}.json"

    # Override only the swept component; force LRU everywhere (base config
    # uses lru_mid for LLC and STLB, which would confound liveness stats).
    python3 - <<PYEOF > "$cfg_file"
import json
cfg = {
  "executable_name": "${bin_name}",
  "${COMP_KEY[$comp]}": {"sets": ${sets}},
  "LLC":  {"replacement": "lru"},
  "STLB": {"replacement": "lru"},
}
print(json.dumps(cfg, indent=2))
PYEOF

    echo "  [${label}]  ${sets} sets  → bin/${bin_name}"
    build_one "$cfg_file" "$bin_name"
  done
  echo ""
done

echo "Done. Built ${total} size-study binaries (+ champsim_lru as baseline)."
echo "Run ./scripts/submit/sweep_cache_size.sh <suite> to submit jobs."
