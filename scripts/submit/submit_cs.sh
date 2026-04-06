#!/usr/bin/env bash
# submit_cs.sh - helper to submit the SGE job with preset WARMUP/SIM/TRACE_DIR per token
# Usage: ./submit_cs.sh test|maz|qmm|dpc3|google [additional qsub args...]
#
# Trace sets and their output separation:
#   test   – 1 trace per workload, 1M warmup / 5M sim (smoke test across all sets)
#   maz    – SPEC traces (local):          results/maz_<date_HHMM>/
#   qmm    – Qualcomm traces (local):      results/qmm_<date_HHMM>/
#   dpc3   – SPEC/DPC-3 traces (shared):   results/dpc3_<date_HHMM>/
#   google – Google traces (shared):       results/google_<date_HHMM>/

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SHARED_TRACES=/home/users/shared/traces

if [ $# -lt 1 ]; then
  echo "Usage: $0 {test|maz|qmm|dpc3|google} [qsub args...]" >&2
  exit 2
fi

token="$1"; shift
EXTRA_QSUB_ARGS=("$@")

# submit_one LABEL WARMUP SIM TRACE_DIR TRACE_EXT MAX_TRACES
# MAX_TRACES=0 means submit all traces.
submit_one() {
  local label="$1" warmup="$2" sim="$3" trace_dir="$4" trace_ext="$5" max_n="$6"

  mapfile -t traces < <(find "${trace_dir}" -name "*.${trace_ext}" | sort)
  local n=${#traces[@]}
  if [ "$n" -eq 0 ]; then
    echo "WARNING: No traces found in ${trace_dir} — skipping ${label}" >&2
    return 1
  fi
  [ "$max_n" -gt 0 ] && [ "$n" -gt "$max_n" ] && n=$max_n

  local run_label="${label}_$(date +%Y%m%d_%H%M)"
  local log_dir="${PROJECT_ROOT}/logs/${run_label}"
  mkdir -p "$log_dir" "${PROJECT_ROOT}/results/${run_label}"

  echo "Submitting : ${run_label} (${n} trace(s), warmup=${warmup}, sim=${sim})"
  echo "  traces   : ${trace_dir}"
  echo "  logs     : logs/${run_label}/"

  qsub -t "1-${n}" \
       -o "${log_dir}/" \
       -e "${log_dir}/" \
       -wd "$PROJECT_ROOT" \
       -v WARMUP="$warmup",SIM="$sim",TRACE_DIR="$trace_dir",TRACE_EXT="$trace_ext",RUN_LABEL="$run_label" \
       "${EXTRA_QSUB_ARGS[@]}" "${PROJECT_ROOT}/scripts/submit/run_cs.sh"
}

case "${token,,}" in
  test)
    submit_one test_maz    1000000 5000000 "${PROJECT_ROOT}/trace-files/MAZUMDAR"  champsimtrace.xz 1
    submit_one test_qmm    1000000 5000000 "${PROJECT_ROOT}/trace-files/QMM"       champsimtrace.xz 1
    submit_one test_dpc3   1000000 5000000 "${SHARED_TRACES}/dpc3_traces"         champsimtrace.xz 1
    submit_one test_google 1000000 5000000 "${SHARED_TRACES}/Google_Traces_v2"   champsim.gz      1
    ;;
  maz|mazumdar)
    submit_one maz 100000000 1000000000 "${PROJECT_ROOT}/trace-files/MAZUMDAR" champsimtrace.xz 0
    ;;
  qmm)
    submit_one qmm 50000000 100000000 "${PROJECT_ROOT}/trace-files/QMM" champsimtrace.xz 0
    ;;
  dpc3)
    submit_one dpc3 100000000 1000000000 "${SHARED_TRACES}/dpc3_traces" champsimtrace.xz 0
    ;;
  google)
    submit_one google 100000000 1000000000 "${SHARED_TRACES}/Google_Traces_v2" champsim.gz 0
    ;;
  *)
    echo "Unknown token: $token — use test, maz, qmm, dpc3, or google" >&2
    exit 2
    ;;
esac
