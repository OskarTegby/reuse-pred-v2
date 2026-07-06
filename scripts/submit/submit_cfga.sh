#!/bin/bash
# Config A ("LRU-Live-style protective" DoA): insert@10, V[p]=max(p-1,5), ceiling 5.
# Same setup as overnight arms (GIPPR base, M_LADDER MD, THD 8/2) so it is directly
# comparable to the slowstart arm (= Config B).
set -euo pipefail
BASE=/home/users/otegby/ChampSim-dev
cd "$BASE"

W=50000000
S=50000000
DATE=$(date +%Y%m%d_%H%M)

SUITES=(
  "dpc3:/home/users/shared/traces/dpc3_traces:champsimtrace.xz"
  "gap:trace-files/gap:trace.gz"
  "ligra:trace-files/ligra:champsimtrace.xz"
  "gms:trace-files/gms:champsimtrace.gz"
  "google:/home/users/shared/traces/Google_Traces_v2:champsim.gz"
  "qmm:trace-files/QMM:champsimtrace.xz"
  "ml:trace-files/ml:champsimtrace.gz"
)

D_CFGA="5:5:5:5:5:5:5:6:7:8:9:10:11:12:13:14:10"
M_LADDER="4:4:4:4:4:4:4:4:5:6:7:8:9:10:11:12:12"

LABEL_BASE="ipv_cfgA_protect_${DATE}"

for entry in "${SUITES[@]}"; do
  IFS=: read -r suite tdir ext <<< "$entry"
  n=$(find "$tdir" -name "*.${ext}" 2>/dev/null | wc -l)
  [ "$n" -eq 0 ] && { echo "WARNING: no traces for $suite"; continue; }
  label="${LABEL_BASE}/${suite}/cfgA"
  mkdir -p "$BASE/results/$label" "$BASE/logs/$label"
  qsub -t 1-${n} -N "${suite:0:2}_cfgA" \
       -o "$BASE/logs/$label/" -e "$BASE/logs/$label/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "$BASE" \
       -v WARMUP=$W,SIM=$S,TRACE_DIR="$tdir",TRACE_EXT="$ext",RUN_LABEL="$label",BINARY="champsim_ipv_live",THD_DOA=8,THD_DEAD=2,IPV_DOA="$D_CFGA",IPV_MOSTLY_DEAD="$M_LADDER" \
       "$BASE/scripts/submit/run_cs.sh" | grep -oP 'job-array \K[0-9]+'
  echo "  $label ($n traces)"
done
echo "LABEL=${LABEL_BASE}"
