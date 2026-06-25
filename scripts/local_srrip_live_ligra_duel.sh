#!/bin/bash
# Local experiment: SRRIP-Live set dueling on 3 ligra traces.
# Tests whether the PSEL duel (Config A vs Config B) recovers from the ins@3
# regression that Config B alone causes on ligra.
#
# Arms:
#   srrip        : plain SRRIP baseline
#   cfgA         : ins@2 hit@2 — no reward, near-SRRIP (safe)
#   cfgB         : ins@3 hit@0 — aggressive insertion, full promotion
#   duel         : PSEL duel between cfgA and cfgB (DUEL_N_SAMPLERS=32)
#
# Run from repo root: bash scripts/local_srrip_live_ligra_duel.sh

set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

TRACE_DIR="/home/otegby/repos/code/ChampSim-dev/trace-files/ligra"
W=50000000
S=100000000
OUT="results/local_ligra_duel"

TRACES=(
  "ligra_CF.com-lj.ungraph.gcc_6.3.0_O3.drop_154750M.length_250M.champsimtrace.xz"
  "ligra_BFSCC.com-lj.ungraph.gcc_6.3.0_O3.drop_15500M.length_250M.champsimtrace.xz"
  "ligra_PageRankDelta.com-lj.ungraph.gcc_6.3.0_O3.drop_24000M.length_250M.champsimtrace.xz"
)

COMMON="SCORING_MODE=5 THD_DOA=6 THD_DEAD=16 BHIST_MODE=pc SRRIP_LIVE_TARGET=llc"

declare -A ARM_BIN=(
  [srrip]="bin/champsim_srrip"
  [cfgA]="bin/champsim_srrip_live"
  [cfgB]="bin/champsim_srrip_live"
  [duel]="bin/champsim_srrip_live"
)
declare -A ARM_ENV=(
  [srrip]=""
  [cfgA]="SRRIP_DOA_INS_RRPV=2 SRRIP_DOA_HIT_RRPV=2"
  [cfgB]="SRRIP_DOA_INS_RRPV=3 SRRIP_DOA_HIT_RRPV=0"
  [duel]="SRRIP_DOA_INS_RRPV=2 SRRIP_DOA_HIT_RRPV=2 SRRIP_DOA_INS_RRPV_B=3 SRRIP_DOA_HIT_RRPV_B=0 DUEL_N_SAMPLERS=32"
)

mkdir -p "$OUT"

echo "=== SRRIP-Live duel experiment (ligra, 3 traces, W=${W} S=${S}) ==="
echo ""

MAX_JOBS=10
pids=()
arm_trace=()

for arm in srrip cfgA cfgB duel; do
  for trace in "${TRACES[@]}"; do
    tname="${trace%.champsimtrace.xz}"
    outdir="${OUT}/${arm}/${tname}"
    mkdir -p "$outdir"

    # Semaphore: wait if at MAX_JOBS running
    while [ "$(jobs -rp | wc -l)" -ge "$MAX_JOBS" ]; do sleep 2; done

    (
      env $COMMON ${ARM_ENV[$arm]} \
        ./${ARM_BIN[$arm]} \
          --warmup_instructions "$W" \
          --simulation_instructions "$S" \
          "${TRACE_DIR}/${trace}" \
        > "${outdir}/champsim.out" 2>"${outdir}/champsim.err"
    ) &
    pids+=($!)
    arm_trace+=("${arm}/${tname}")
    echo "  launched: ${arm} / ${tname##*ligra_}"
  done
done

echo ""
echo "Waiting for ${#pids[@]} runs (max $MAX_JOBS parallel)..."
for pid in "${pids[@]}"; do wait "$pid"; done
echo "All done."
echo ""

python3 - << 'PYEOF'
from __future__ import print_function
import glob, os, re, math

OUT = "results/local_ligra_duel"
ARMS = ["srrip", "cfgA", "cfgB", "duel"]

def ipc(f):
    try:
        with open(f) as h:
            for line in h:
                if line.startswith("CPU 0 cumulative IPC:"):
                    return float(line.split()[4])
    except:
        pass
    return None

def winner(f):
    try:
        with open(f) as h:
            for line in h:
                if "winner=config_" in line:
                    m = re.search(r"winner=config_(\w+)", line)
                    if m: return m.group(1)
                if "PSEL=" in line:
                    m = re.search(r"winner=(\w+)", line)
                    if m: return m.group(1)
    except:
        pass
    return None

def gm(vs):
    return math.exp(sum(math.log(v) for v in vs) / len(vs)) if vs else float('nan')

traces = sorted(set(
    os.path.basename(os.path.dirname(f))
    for f in glob.glob(OUT + "/srrip/*/champsim.out")
))

# Short names for display
def short(t):
    for k in ["PageRankDelta", "BFSCC", "CF"]:
        if k in t: return k
    return t[:20]

print("%-16s | %8s | %8s | %8s | %8s | duel winner" % (
    "trace", "srrip", "cfgA/SR", "cfgB/SR", "duel/SR"))
print("-" * 72)

all_ipc = {a: [] for a in ARMS}
for t in traces:
    ipcs = {a: ipc(OUT + "/" + a + "/" + t + "/champsim.out") for a in ARMS}
    for a in ARMS:
        if ipcs[a]: all_ipc[a].append(ipcs[a])
    base = ipcs["srrip"]
    w = winner(OUT + "/duel/" + t + "/champsim.out")
    row = "%-16s | %8.4f" % (short(t), base or 0)
    for a in ["cfgA", "cfgB", "duel"]:
        v = ipcs[a]
        row += " | %+7.2f%%" % ((v / base - 1) * 100) if (v and base) else " |     n/a"
    row += " | %s" % (w or "?")
    print(row)

print("-" * 72)
base_gm = gm(all_ipc["srrip"])
row = "%-16s | %8.4f" % ("geomean", base_gm)
for a in ["cfgA", "cfgB", "duel"]:
    g = gm(all_ipc[a])
    row += " | %+7.2f%%" % ((g / base_gm - 1) * 100)
row += " |"
print(row)
PYEOF
