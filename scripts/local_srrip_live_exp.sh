#!/bin/bash
# Local experiment: SRRIP vs SRRIP-Live insertion/hit variants on 5 QMM traces.
# Three arms:
#   srrip          : plain SRRIP baseline
#   sl_ins2_nopromo: ins@2, hit@2 (no promotion on DoA hits)
#   sl_ins3_nopromo: ins@3, hit@2 (eviction-candidate insertion, no promotion)
#   sl_ins2_fullpr : ins@2, hit@0 (matches cluster binary default; full promotion)
#
# Run from repo root: bash scripts/local_srrip_live_exp.sh

set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

TRACE_DIR="/home/otegby/repos/code/ChampSim-dev/trace-files/QMM"
W=50000000
S=100000000
OUT="results/local_srrip_live_exp_full"

TRACES=(
  srv_128.champsimtrace.xz
  srv_12.champsimtrace.xz
  srv_21.champsimtrace.xz
  srv_255.champsimtrace.xz
  srv_276.champsimtrace.xz
)

COMMON_ENV="SCORING_MODE=5 THD_DOA=6 THD_DEAD=2 BHIST_MODE=pc SRRIP_LIVE_TARGET=llc"

declare -A ARMS=(
  [srrip]=""
  [sl_ins2_nopromo]="SRRIP_DOA_INS_RRPV=2 SRRIP_DOA_HIT_RRPV=2"
  [sl_ins3_nopromo]="SRRIP_DOA_INS_RRPV=3 SRRIP_DOA_HIT_RRPV=2"
  [sl_ins2_fullpr]="SRRIP_DOA_INS_RRPV=2 SRRIP_DOA_HIT_RRPV=0"
)

declare -A BINS=(
  [srrip]="bin/champsim_srrip"
  [sl_ins2_nopromo]="bin/champsim_srrip_live"
  [sl_ins3_nopromo]="bin/champsim_srrip_live"
  [sl_ins2_fullpr]="bin/champsim_srrip_live"
)

mkdir -p "$OUT"

echo "=== SRRIP-Live local experiment (QMM, 5 traces, W=${W} S=${S}) ==="
echo ""

pids=()
for arm in srrip sl_ins2_nopromo sl_ins3_nopromo sl_ins2_fullpr; do
  for trace in "${TRACES[@]}"; do
    tname="${trace%.champsimtrace.xz}"
    outdir="${OUT}/${arm}/${tname}"
    mkdir -p "$outdir"
    (
      env $COMMON_ENV ${ARMS[$arm]} \
        ./${BINS[$arm]} \
          --warmup_instructions "$W" \
          --simulation_instructions "$S" \
          "${TRACE_DIR}/${trace}" \
        > "${outdir}/champsim.out" 2>"${outdir}/champsim.err"
    ) &
    pids+=($!)
  done
done

echo "Launched ${#pids[@]} runs in parallel — waiting..."
for pid in "${pids[@]}"; do wait "$pid"; done
echo "All done."
echo ""

# Quick IPC comparison
python3 - << 'PYEOF'
from __future__ import print_function
import glob, os, re, math

OUT = "results/local_srrip_live_exp_full"
ARMS = ["srrip", "sl_ins2_nopromo", "sl_ins3_nopromo", "sl_ins2_fullpr"]

def ipc(f):
    try:
        with open(f) as h:
            for line in h:
                if line.startswith("CPU 0 cumulative IPC:"):
                    return float(line.split()[4])
    except:
        pass
    return None

def gm(vs):
    return math.exp(sum(math.log(v) for v in vs) / len(vs)) if vs else float('nan')

traces = sorted(set(
    os.path.basename(os.path.dirname(f))
    for f in glob.glob(OUT + "/srrip/*/champsim.out")
))

# Header
hdr = "%-30s" % "trace"
for arm in ARMS:
    hdr += " %14s" % arm
print(hdr)
print("-" * (30 + 15 * len(ARMS)))

all_ipcs = {arm: [] for arm in ARMS}
for t in traces:
    row = "%-30s" % t
    ipcs = {}
    for arm in ARMS:
        v = ipc(OUT + "/" + arm + "/" + t + "/champsim.out")
        ipcs[arm] = v
        if v:
            all_ipcs[arm].append(v)
    base = ipcs["srrip"]
    for arm in ARMS:
        v = ipcs[arm]
        if v is None:
            row += " %14s" % "n/a"
        elif arm == "srrip":
            row += " %14.4f" % v
        else:
            row += " %+13.2f%%" % ((v / base - 1) * 100) if base else " %14.4f" % v
    print(row)

print("-" * (30 + 15 * len(ARMS)))
row = "%-30s" % "geomean"
base_gm = gm(all_ipcs["srrip"])
row += " %14.4f" % base_gm
for arm in ARMS[1:]:
    g = gm(all_ipcs[arm])
    row += " %+13.2f%%" % ((g / base_gm - 1) * 100)
print(row)
PYEOF
