#!/bin/bash
# LRU-Live bypass latency duel — all local traces, max 10 concurrent jobs.
# Two arms: LRU baseline + LRU-Live latency duel (cfgA=2n3 vs cfgB=bypass).

set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

W=50000000; S=100000000
OUT="results/local_lru_live_bypass_v3"
MAX_JOBS=10

TRACES=()
for dir_ext in \
  "/home/otegby/repos/code/ChampSim-dev/trace-files/QMM:champsimtrace.xz" \
  "/home/otegby/repos/code/ChampSim-dev/trace-files/ligra:champsimtrace.xz" \
  "/home/otegby/repos/code/ChampSim-dev/trace-files/SPEC2006:champsimtrace.xz"; do
  dir="${dir_ext%%:*}"; ext="${dir_ext##*:}"
  while IFS= read -r f; do TRACES+=("$f"); done < <(find "$dir" -name "*.${ext}" | sort)
done

echo "=== LRU-Live bypass latency duel (${#TRACES[@]} traces, max ${MAX_JOBS} concurrent) ==="

sem() { while [ "$(jobs -rp | wc -l)" -ge "$MAX_JOBS" ]; do sleep 1; done; }

for trace in "${TRACES[@]}"; do
  tname=$(basename "$trace" | sed 's/\.\(champsimtrace\.xz\|champsim\.gz\|trace\.gz\)$//')

  sem; mkdir -p "${OUT}/lru_base/${tname}"
  ( ./bin/champsim_lru \
      --warmup_instructions "$W" --simulation_instructions "$S" "$trace" \
      > "${OUT}/lru_base/${tname}/champsim.out" \
      2>"${OUT}/lru_base/${tname}/champsim.err" ) &

  sem; mkdir -p "${OUT}/ll_duel_bypass_lat/${tname}"
  ( SCORING_MODE=5 THD_DOA=6 THD_DEAD=16 BHIST_MODE=pc SRRIP_LIVE_TARGET=llc \
    LRU_LIVE_DOA_INS=2n3 LRU_LIVE_DOA_INS_B=bypass \
    DUEL_N_SAMPLERS=32 DUEL_METRIC=latency \
    ./bin/champsim_lru_live \
      --warmup_instructions "$W" --simulation_instructions "$S" "$trace" \
      > "${OUT}/ll_duel_bypass_lat/${tname}/champsim.out" \
      2>"${OUT}/ll_duel_bypass_lat/${tname}/champsim.err" ) &
done

echo "Waiting for all jobs..."
wait
echo "Done — $(date)"
echo ""

python3 - << 'PYEOF'
from __future__ import print_function
import glob, os, re, math

OUT = "results/local_lru_live_bypass_v3"

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

def suite(t):
    if "srv_" in t:   return "qmm"
    if "ligra_" in t: return "ligra"
    return "spec"

def gm(vs): return math.exp(sum(math.log(v) for v in vs)/len(vs)) if vs else None
def pct(a, b): return "%+6.2f%%" % ((a/b-1)*100) if a and b else "  n/a"

traces = sorted(set(
    os.path.basename(os.path.dirname(f))
    for f in glob.glob(OUT + "/lru_base/*/champsim.out")
))

by_suite = {"qmm": [], "ligra": [], "spec": []}
for t in traces:
    by_suite[suite(t)].append(t)

print("%-8s | %8s | %12s | winner A/B | n" % ("suite", "lru_gm", "duel_lat/LR"))
print("-" * 55)

total_sr = []; total_dl = []
for sname in ["qmm", "ligra", "spec"]:
    sr = []; dl = []; nA = nB = 0
    for t in by_suite[sname]:
        s = ipc(OUT+"/lru_base/"+t+"/champsim.out")
        d = ipc(OUT+"/ll_duel_bypass_lat/"+t+"/champsim.out")
        w = winner(OUT+"/ll_duel_bypass_lat/"+t+"/champsim.out")
        if s: sr.append(s)
        if d: dl.append(d)
        if w:
            if "A" in w: nA += 1
            elif "B" in w: nB += 1
    if not sr: continue
    total_sr += sr; total_dl += dl
    sg = gm(sr); dg = gm(dl)
    print("%-8s | %8.4f | %12s | A=%d B=%d | %d/%d" % (
        sname, sg, pct(dg, sg), nA, nB, len(dl), len(sr)))

print("-" * 55)
if total_sr:
    print("%-8s | %8.4f | %12s" % ("pooled", gm(total_sr), pct(gm(total_dl), gm(total_sr))))
PYEOF
