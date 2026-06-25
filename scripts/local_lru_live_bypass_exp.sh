#!/bin/bash
# Local experiment: LRU-Live DoA insertion modes on ligra + QMM traces.
# Four arms:
#   lru_base   : plain LRU baseline
#   ll_2n3     : LRU-Live, DoA at 2N/3 from MRU (current default)
#   ll_lrupos  : LRU-Live, DoA at LRU position (rank 0)
#   ll_bypass  : LRU-Live, DoA bypass-priority (rank 0, always evicted first)
#   ll_duel    : PSEL duel — cfgA=2n3 vs cfgB=bypass
#
# Run from repo root: bash scripts/local_lru_live_bypass_exp.sh

set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

W=50000000; S=100000000
OUT="results/local_lru_live_bypass_v2"
COMMON="SCORING_MODE=5 THD_DOA=6 THD_DEAD=16 BHIST_MODE=pc SRRIP_LIVE_TARGET=llc"

declare -A ARM_ENV=(
  [lru_base]=""
  [ll_2n3]="LRU_LIVE_DOA_INS=2n3"
  [ll_lrupos]="LRU_LIVE_DOA_INS=lru"
  [ll_bypass]="LRU_LIVE_DOA_INS=bypass"
  [ll_duel]="LRU_LIVE_DOA_INS=2n3 LRU_LIVE_DOA_INS_B=bypass DUEL_N_SAMPLERS=32"
  [ll_duel_lat]="LRU_LIVE_DOA_INS=2n3 LRU_LIVE_DOA_INS_B=bypass DUEL_N_SAMPLERS=32 DUEL_METRIC=latency"
)
declare -A ARM_BIN=(
  [lru_base]="bin/champsim_lru"
  [ll_2n3]="bin/champsim_lru_live"
  [ll_lrupos]="bin/champsim_lru_live"
  [ll_bypass]="bin/champsim_lru_live"
  [ll_duel]="bin/champsim_lru_live"
  [ll_duel_lat]="bin/champsim_lru_live"
)

LIGRA_DIR="/home/otegby/repos/code/ChampSim-dev/trace-files/ligra"
QMM_DIR="/home/otegby/repos/code/ChampSim-dev/trace-files/QMM"

TRACES=(
  "${LIGRA_DIR}/ligra_CF.com-lj.ungraph.gcc_6.3.0_O3.drop_154750M.length_250M.champsimtrace.xz"
  "${LIGRA_DIR}/ligra_BFSCC.com-lj.ungraph.gcc_6.3.0_O3.drop_15500M.length_250M.champsimtrace.xz"
  "${LIGRA_DIR}/ligra_PageRankDelta.com-lj.ungraph.gcc_6.3.0_O3.drop_24000M.length_250M.champsimtrace.xz"
  "${QMM_DIR}/srv_128.champsimtrace.xz"
  "${QMM_DIR}/srv_12.champsimtrace.xz"
)

mkdir -p "$OUT"
echo "=== LRU-Live bypass experiment (3 ligra + 2 QMM, W=${W} S=${S}) ==="
echo ""

MAX_JOBS=10
for arm in lru_base ll_2n3 ll_lrupos ll_bypass ll_duel ll_duel_lat; do
  for trace in "${TRACES[@]}"; do
    tname=$(basename "$trace" | sed 's/\.champsimtrace\.xz$//')
    outdir="${OUT}/${arm}/${tname}"
    mkdir -p "$outdir"
    while [ "$(jobs -rp | wc -l)" -ge "$MAX_JOBS" ]; do sleep 2; done
    (
      env $COMMON ${ARM_ENV[$arm]} \
        ./${ARM_BIN[$arm]} \
          --warmup_instructions "$W" \
          --simulation_instructions "$S" \
          "$trace" \
        > "${outdir}/champsim.out" 2>"${outdir}/champsim.err"
    ) &
    echo "  launched: ${arm} / ${tname##*ligra_}${tname##*srv_}"
  done
done

echo ""
echo "Waiting (max $MAX_JOBS parallel)..."
wait
echo "All done."
echo ""

python3 - << 'PYEOF'
from __future__ import print_function
import glob, os, re, math

OUT = "results/local_lru_live_bypass"
ARMS = ["lru_base", "ll_2n3", "ll_lrupos", "ll_bypass", "ll_duel", "ll_duel_lat"]

def ipc(f):
    try:
        with open(f) as h:
            for line in h:
                if line.startswith("CPU 0 cumulative IPC:"):
                    return float(line.split()[4])
    except: pass
    return None

def winner(f):
    try:
        with open(f) as h:
            for line in h:
                if "winner=" in line:
                    m = re.search(r"winner=(\S+)", line)
                    if m: return m.group(1)
    except: pass
    return None

def gm(vs): return math.exp(sum(math.log(v) for v in vs)/len(vs)) if vs else float('nan')

def short(t):
    for k in ["PageRankDelta","BFSCC","CF","srv_128","srv_12"]:
        if k in t: return k
    return t[:14]

traces = sorted(set(
    os.path.basename(os.path.dirname(f))
    for f in glob.glob(OUT + "/lru_base/*/champsim.out")
))

print("%-16s | %8s | %8s | %8s | %8s | %8s | duel" % (
    "trace","lru_base","ll_2n3/LR","ll_lru/LR","ll_byp/LR","ll_duel/LR"))
print("-" * 82)

all_ipc = {a: [] for a in ARMS}
for t in traces:
    ipcs = {a: ipc(OUT+"/"+a+"/"+t+"/champsim.out") for a in ARMS}
    for a in ARMS:
        if ipcs[a]: all_ipc[a].append(ipcs[a])
    base = ipcs["lru_base"]
    w = winner(OUT+"/ll_duel/"+t+"/champsim.out") or "?"
    row = "%-16s | %8.4f" % (short(t), base or 0)
    for a in ARMS[1:]:
        v = ipcs[a]
        row += " | %+7.2f%%" % ((v/base-1)*100) if (v and base) else " |     n/a"
    row += " | %s" % w
    print(row)

print("-" * 82)
base_gm = gm(all_ipc["lru_base"])
row = "%-16s | %8.4f" % ("geomean", base_gm)
for a in ARMS[1:]:
    g = gm(all_ipc[a])
    row += " | %+7.2f%%" % ((g/base_gm-1)*100)
row += " |"
print(row)
PYEOF
