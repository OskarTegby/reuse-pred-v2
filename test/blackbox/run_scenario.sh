#!/usr/bin/env bash
#
# Black-box scenario runner for the liveness replacement policies.
#
#   Usage: run_scenario.sh <scenario>          # run + diff against golden
#          GENERATE=1 run_scenario.sh <scenario>  # (re)write the golden file
#
# Each scenario names a binary + a fixed environment.  The runner executes
# ChampSim on a single deterministic trace, strips the only nondeterministic
# line (the wall-clock "Simulation time" suffix), and byte-compares the whole
# report against test/blackbox/expected/<scenario>.out.
#
# The guard is the full report, not a hand-picked metric: every cache counter
# and every liveness statistic (LLC UNIQUE INSTRUCTION DOA, the repl_hist PC
# dump, ...) is pinned.  A code change that compounds over the simulation moves
# *some* number, and the diff catches it without anyone naming which one.
#
# Determinism is what makes a zero-tolerance golden diff valid: same binary +
# same trace = bit-identical output (verified; only the timing line varies).
#
set -euo pipefail

SCEN="${1:?usage: run_scenario.sh <scenario>}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${SRC_ROOT:-$(cd "$HERE/../.." && pwd)}"
BIN_DIR="${BIN_DIR:-$ROOT/bin}"
TRACE="${TRACE:-$ROOT/trace-files/pagerank.champsimtrace.xz}"
EXPECTED_DIR="$HERE/expected"
OUT_DIR="${OUTPUT_DIR:-$HERE/test_outputs}"
WARMUP="${WARMUP:-1000000}"
SIM="${SIM:-2000000}"

mkdir -p "$OUT_DIR" "$EXPECTED_DIR"

# --- scenario definitions -------------------------------------------------
# Set BIN (binary basename) and export the scenario's env.  Anything not set
# here falls back to the binary's compiled-in default, which is the point of
# the bare "*_default" scenarios: they guard the default code path.
#
# THD_DOA/THD_DEAD/SCORING_MODE form the canonical liveness baseline; the
# pagerank trace is 100% DoA with four load PCs.

unset_policy_env() {
  unset SCORING_MODE LRU_LIVE_DOA_INS LRU_LIVE_ALLOW_BYPASS \
        DUEL_N_SAMPLERS DUEL_N_CONFIGS DUEL_METRIC DUEL_HYST \
        BHIST_MODE SRRIP_LIVE_TARGET SRRIP_DOA_INS_RRPV SRRIP_DOA_INS_RRPV_B \
        IPV_DOA IPV_DOA_0 IPV_DOA_1 IPV_DOA_2 \
        REPL_HIST_LLC_CAP REPL_HIST_REPL REPL_HIST_DUMP_PCS \
        THD_DOA THD_DEAD 2>/dev/null || true
}
unset_policy_env

base() { export THD_DOA=6 THD_DEAD=10 SCORING_MODE=5; }

case "$SCEN" in
  # ---------------- LRU-Live ----------------
  lru_default)        BIN=champsim_lru_live ;;
  lru_2n3)            BIN=champsim_lru_live; base; export LRU_LIVE_DOA_INS=2n3 ;;
  lru_lru)            BIN=champsim_lru_live; base; export LRU_LIVE_DOA_INS=lru ;;
  lru_bypass)         BIN=champsim_lru_live; base; export LRU_LIVE_DOA_INS=bypass ;;
  lru_bypass_off)     BIN=champsim_lru_live; base; export LRU_LIVE_DOA_INS=bypass LRU_LIVE_ALLOW_BYPASS=0 ;;
  lru_duel_hits)      BIN=champsim_lru_live; base; export DUEL_N_SAMPLERS=32 ;;
  lru_duel_lat_hyst)  BIN=champsim_lru_live; base; export DUEL_N_SAMPLERS=32 DUEL_METRIC=latency DUEL_HYST=250000 ;;
  lru_cap256)         BIN=champsim_lru_live; base; export REPL_HIST_LLC_CAP=256 REPL_HIST_REPL=tiered REPL_HIST_DUMP_PCS=1 ;;

  # ---------------- SRRIP-Live ----------------
  srrip_default)      BIN=champsim_srrip_live ;;
  srrip_mode3)        BIN=champsim_srrip_live; base; export SCORING_MODE=3 BHIST_MODE=pc SRRIP_LIVE_TARGET=llc ;;
  srrip_mode4)        BIN=champsim_srrip_live; base; export SCORING_MODE=4 BHIST_MODE=pc SRRIP_LIVE_TARGET=llc ;;
  srrip_mode5)        BIN=champsim_srrip_live; base; export SCORING_MODE=5 BHIST_MODE=pc SRRIP_LIVE_TARGET=llc ;;
  srrip_mode7)        BIN=champsim_srrip_live; base; export SCORING_MODE=7 BHIST_MODE=pc SRRIP_LIVE_TARGET=llc ;;
  srrip_mode8)        BIN=champsim_srrip_live; base; export SCORING_MODE=8 BHIST_MODE=pc SRRIP_LIVE_TARGET=llc ;;
  srrip_cap256)       BIN=champsim_srrip_live; base; export BHIST_MODE=pc SRRIP_LIVE_TARGET=llc REPL_HIST_LLC_CAP=256 REPL_HIST_REPL=tiered REPL_HIST_DUMP_PCS=1 ;;
  srrip_duel_cfg0)    BIN=champsim_srrip_live; base; export BHIST_MODE=pc SRRIP_LIVE_TARGET=llc DUEL_N_SAMPLERS=256 SRRIP_DOA_INS_RRPV=2 SRRIP_DOA_INS_RRPV_B=3 ;;

  # ---------------- IPV-Live ----------------
  ipv_default)        BIN=champsim_ipv_live ;;
  ipv_canonical)      BIN=champsim_ipv_live; base; export SRRIP_LIVE_TARGET=llc ;;
  ipv_ins3_comma)     BIN=champsim_ipv_live; base; export SRRIP_LIVE_TARGET=llc IPV_DOA=0,1,2,2,3 ;;
  ipv_ins3_colon)     BIN=champsim_ipv_live; base; export SRRIP_LIVE_TARGET=llc IPV_DOA=0:1:2:2:3 ;;
  ipv_cap256)         BIN=champsim_ipv_live; base; export SRRIP_LIVE_TARGET=llc REPL_HIST_LLC_CAP=256 REPL_HIST_REPL=tiered REPL_HIST_DUMP_PCS=1 ;;

  # ---------------- set dueling ----------------
  duel_ipv_cfg0_ins2) BIN=champsim_ipv_live; base; export SRRIP_LIVE_TARGET=llc DUEL_N_SAMPLERS=256 IPV_DOA_0=0,1,2,2,2 IPV_DOA_1=0,1,2,2,3 ;;
  duel_ipv_cfg0_ins3) BIN=champsim_ipv_live; base; export SRRIP_LIVE_TARGET=llc DUEL_N_SAMPLERS=256 IPV_DOA_0=0,1,2,2,3 IPV_DOA_1=0,1,2,2,2 ;;
  duel_ipv_3way)      BIN=champsim_ipv_live; base; export SRRIP_LIVE_TARGET=llc DUEL_N_SAMPLERS=256 DUEL_N_CONFIGS=3 IPV_DOA_0=0,1,2,2,2 IPV_DOA_1=0,1,2,2,3 IPV_DOA_2=0,1,1,2,3 ;;

  *) echo "run_scenario.sh: unknown scenario '$SCEN'" >&2; exit 2 ;;
esac

BIN_PATH="$BIN_DIR/$BIN"
if [ ! -x "$BIN_PATH" ]; then echo "SKIP $SCEN: binary not built: $BIN_PATH" >&2; exit 77; fi
if [ ! -f "$TRACE" ];   then echo "SKIP $SCEN: trace not found: $TRACE"    >&2; exit 77; fi

ACTUAL="$OUT_DIR/$SCEN.out"
GOLDEN="$EXPECTED_DIR/$SCEN.out"

# Run, then strip the nondeterministic wall-clock suffix.
"$BIN_PATH" --warmup_instructions "$WARMUP" --simulation_instructions "$SIM" "$TRACE" 2>&1 \
  | sed -E 's/ \(Simulation time: [0-9]+ hr [0-9]+ min [0-9]+ sec\)//' \
  > "$ACTUAL"

if [ "${GENERATE:-0}" = "1" ]; then
  cp "$ACTUAL" "$GOLDEN"
  echo "GENERATED $GOLDEN"
  exit 0
fi

if [ ! -f "$GOLDEN" ]; then
  echo "FAIL $SCEN: no golden file ($GOLDEN). Run with GENERATE=1 to create it." >&2
  exit 1
fi

if diff -u "$GOLDEN" "$ACTUAL"; then
  echo "PASS $SCEN"
else
  echo "FAIL $SCEN: output diverged from golden" >&2
  exit 1
fi
