#!/bin/bash
# IPV-Live vector-design study. Usage: submit_ipv_designs.sh <wave1|wave2>
set -euo pipefail
BASE=/home/users/otegby/ChampSim-dev
cd "$BASE"

W=50000000
S=50000000
DATE=$(date +%Y%m%d_%H%M)
WAVE="${1:?usage: submit_ipv_designs.sh wave1|wave2}"

# suite:dir:ext
WAVE1_SUITES=(
  "dpc3:/home/users/shared/traces/dpc3_traces:champsimtrace.xz"
  "gap:trace-files/gap:trace.gz"
  "ligra:trace-files/ligra:champsimtrace.xz"
)
WAVE2_SUITES=(
  "gms:trace-files/gms:champsimtrace.gz"
  "google:/home/users/shared/traces/Google_Traces_v2:champsim.gz"
  "qmm:trace-files/QMM:champsimtrace.xz"
  "ml:trace-files/ml:champsimtrace.gz"
)

D_FLAT="10:10:10:10:10:10:10:10:10:10:10:10:10:10:10:10:10"
M_FLAT="8:8:8:8:8:8:8:8:8:8:8:8:8:8:8:8:8"
D_LADDER="8:8:8:8:8:8:8:8:8:8:8:8:9:10:11:12:14"
M_LADDER="4:4:4:4:4:4:4:4:5:6:7:8:9:10:11:12:12"
D_CAP="8:8:8:8:8:8:8:8:8:9:10:11:8:9:8:8:12"
M_CAP="4:4:4:4:4:5:6:7:4:5:6:7:4:5:4:4:12"
D_SLOW="1:1:1:1:1:1:1:6:6:6:6:10:10:10:13:13:15"
M_FRONT="7:7:7:7:7:7:7:12:7:7:8:8:10:10:10:10:12"
D_RESCUE="8:8:8:8:8:8:8:8:8:8:8:8:9:10:11:12:15"
MDPP="0:1:2:3:4:5:6:7:0:1:2:3:0:1:0:0:12"

# arm:extra_env  (all IPV arms get THD_DOA=8,THD_DEAD=2)
ARMS=(
  "ctrl_flat:IPV_DOA=${D_FLAT},IPV_MOSTLY_DEAD=${M_FLAT}"
  "ladder:IPV_DOA=${D_LADDER},IPV_MOSTLY_DEAD=${M_LADDER}"
  "capped:IPV_DOA=${D_CAP},IPV_MOSTLY_DEAD=${M_CAP}"
  "slowstart:IPV_DOA=${D_SLOW},IPV_MOSTLY_DEAD=${M_LADDER}"
  "frontload:IPV_DOA=${D_LADDER},IPV_MOSTLY_DEAD=${M_FRONT}"
  "rescue:IPV_DOA=${D_RESCUE},IPV_MOSTLY_DEAD=${M_FLAT}"
  "mdpp_ctrl:IPV_VECTOR=${MDPP},IPV_DOA=${D_FLAT},IPV_MOSTLY_DEAD=${M_FLAT}"
)

LABEL_BASE="ipv_designs_${WAVE}_${DATE}"

if [ "$WAVE" = "wave1" ]; then SUITES=("${WAVE1_SUITES[@]}"); else SUITES=("${WAVE2_SUITES[@]}"); fi

for entry in "${SUITES[@]}"; do
  IFS=: read -r suite tdir ext <<< "$entry"
  n=$(find "$tdir" -name "*.${ext}" 2>/dev/null | wc -l)
  if [ "$n" -eq 0 ]; then echo "WARNING: no traces for $suite ($tdir/*.$ext), skipping"; continue; fi

  for arm_entry in "${ARMS[@]}"; do
    arm="${arm_entry%%:*}"
    extra="${arm_entry#*:}"
    label="${LABEL_BASE}/${suite}/${arm}"
    mkdir -p "$BASE/results/$label" "$BASE/logs/$label"
    qsub -t 1-${n} -N "${suite:0:2}_${arm:0:6}" \
         -o "$BASE/logs/$label/" -e "$BASE/logs/$label/" \
         -l h_rt=24:00:00 -l mem_free=1G -wd "$BASE" \
         -v WARMUP=$W,SIM=$S,TRACE_DIR="$tdir",TRACE_EXT="$ext",RUN_LABEL="$label",BINARY="champsim_ipv_live",THD_DOA=8,THD_DEAD=2,$extra \
         "$BASE/scripts/submit/run_cs.sh" | grep -oP 'job-array \K[0-9]+'
    echo "  $label ($n traces)"
  done

  label="${LABEL_BASE}/${suite}/lru"
  mkdir -p "$BASE/results/$label" "$BASE/logs/$label"
  qsub -t 1-${n} -N "${suite:0:2}_lru" \
       -o "$BASE/logs/$label/" -e "$BASE/logs/$label/" \
       -l h_rt=24:00:00 -l mem_free=1G -wd "$BASE" \
       -v WARMUP=$W,SIM=$S,TRACE_DIR="$tdir",TRACE_EXT="$ext",RUN_LABEL="$label",BINARY="champsim_lru" \
       "$BASE/scripts/submit/run_cs.sh" | grep -oP 'job-array \K[0-9]+'
  echo "  $label ($n traces)"
done

echo "LABEL=${LABEL_BASE}"
