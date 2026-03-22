#!/usr/bin/env bash
# sweep_cs.sh - submit threshold sweep experiments across all configurations
# Usage: ./sweep_cs.sh {maz|qmm} [--debug]
#
# --debug    Run only srv_128 instead of all traces (quick sanity check)
#
# Configurations submitted:
#   baseline             : dppred=0, cbpred=0
#   pthd{0..6}           : dppred=1, cbpred=0, pconf_thd=0..6
#   pthd{0..6}_bthd{0..6}: dppred=1, cbpred=1, pconf_thd=0..6, bconf_thd=0..6
# Total: 1 + 7 + 49 = 57 configs

set -euo pipefail

# ── Argument parsing ──────────────────────────────────────────────────────────
token=""
DEBUG=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    maz|mazumdar|qmm) token="${1,,}"; shift ;;
    --debug)          DEBUG=1; shift ;;
    *) echo "Unknown argument: $1" >&2
       echo "Usage: $0 {maz|qmm} [--debug]" >&2
       exit 2 ;;
  esac
done

if [ -z "$token" ]; then
  echo "Usage: $0 {maz|qmm} [--debug]" >&2
  exit 2
fi

# ── Trace-set settings ────────────────────────────────────────────────────────
case "$token" in
  maz|mazumdar)
    WARMUP=100000000
    SIM=1000000000
    TRACE_DIR=trace-files/MAZUMDAR
    ;;
  qmm)
    WARMUP=50000000
    SIM=100000000
    TRACE_DIR=trace-files/QMM
    ;;
esac

# ── Resolve trace list ────────────────────────────────────────────────────────
mapfile -t TRACES < <(ls -1 "${TRACE_DIR}"/*.champsimtrace.xz 2>/dev/null | sort)
N=${#TRACES[@]}
if [ "$N" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2
  exit 2
fi

if [ "$DEBUG" -eq 1 ]; then
  TASK_RANGE=""
  for i in "${!TRACES[@]}"; do
    if [[ "${TRACES[$i]}" == *srv_128* ]]; then
      TASK_RANGE="$((i+1))-$((i+1))"
      break
    fi
  done
  if [ -z "$TASK_RANGE" ]; then
    echo "WARNING: srv_128 not found in ${TRACE_DIR} — using task 1 instead" >&2
    TASK_RANGE="1-1"
  fi
  MODE_TAG="_debug"
else
  TASK_RANGE="1-${N}"
  MODE_TAG=""
fi

DATE=$(date +%Y%m%d)
BASE_LABEL="${token}_${DATE}${MODE_TAG}"

mkdir -p logs

# ── Build config list: (exp_name dppred cbpred pconf_thd bconf_thd) ──────────
configs=()
configs+=("baseline 0 0 0 0")
for thd in $(seq 0 6); do
  configs+=("pthd${thd} 1 0 ${thd} 0")
done
for pthd in $(seq 0 6); do
  for bthd in $(seq 0 6); do
    configs+=("pthd${pthd}_bthd${bthd} 1 1 ${pthd} ${bthd}")
  done
done

echo "Submitting ${#configs[@]} configurations × ${N} traces (tasks ${TASK_RANGE})"
echo "Results base: results/${BASE_LABEL}/"
echo ""

# ── Submit all configs ────────────────────────────────────────────────────────
for config in "${configs[@]}"; do
  read -r exp_name dppred cbpred pconf_thd bconf_thd <<< "$config"

  RUN_LABEL="${BASE_LABEL}/${exp_name}"
  mkdir -p "results/${RUN_LABEL}"

  raw=$(qsub -t "$TASK_RANGE" \
             -N "cs_${exp_name}" \
             -v WARMUP="$WARMUP",SIM="$SIM",TRACE_DIR="$TRACE_DIR",RUN_LABEL="$RUN_LABEL",DPPRED="$dppred",CBPRED="$cbpred",PCONF_THD="$pconf_thd",BCONF_THD="$bconf_thd" \
             run_cs.sh)
  jid=$(echo "$raw" | awk '/Your job/ {print $3}' | cut -d. -f1)
  echo "  [jid=${jid}] ${exp_name}"
done

echo ""
echo "All configs submitted. Monitor with: qstat -u \$USER"
echo "Results will appear under: results/${BASE_LABEL}/"
