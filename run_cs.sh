#!/bin/bash

REPO="$HOME/ChampSim-dev"
BIN="$REPO/bin/champsim"
TRACE_DIR="$REPO/trace-files/MAZUMDAR"
RESULTS_BASE="$REPO/results"
JOBS_DIR="$RESULTS_BASE/jobs"

# Default predictor parameter values (match cache.h defaults)
PFQ_CAP=8
ST_SIZE=2

# Parse command line args
DEBUG=0
while getopts "d" opt; do
  case $opt in
  d) DEBUG=1 ;;
  esac
done

mkdir -p "$JOBS_DIR"

# Build sorted list of traces at submit time so all array tasks see the same order
mapfile -t TRACES < <(ls -1 "${TRACE_DIR}"/*.champsimtrace.xz 2>/dev/null | sort)
N=${#TRACES[@]}
if [ "$N" -eq 0 ]; then
  echo "ERROR: No traces found in ${TRACE_DIR}" >&2
  exit 1
fi

submit_job() {
  local exp_name=$1
  local dppred=$2
  local cbpred=$3
  local pconf_thd=$4
  local bconf_thd=$5

  local warmup sim walltime task_range
  if [ "$DEBUG" -eq 1 ]; then
    warmup=100000
    sim=500000
    walltime="02:00:00"
    task_range="1-2" # only run first two traces in debug mode
    exp_name="debug_${exp_name}"
  else
    warmup=500000
    sim=1000000
    walltime="24:00:00"
    task_range="1-${N}"
  fi

  local job_script="$JOBS_DIR/${exp_name}.sh"

  cat >"$job_script" <<EOF
#!/bin/bash
#$ -N ${exp_name}
#$ -t ${task_range}
#$ -o $JOBS_DIR/${exp_name}_\$TASK_ID.stdout
#$ -e $JOBS_DIR/${exp_name}_\$TASK_ID.stderr
#$ -l h_rt=${walltime}
#$ -l mem_free=4G

# Predictor settings — read by load_predictor_settings() in CACHE constructor
export DPPRED=${dppred}
export CBPRED=${cbpred}
export PCONF_THD=${pconf_thd}
export BCONF_THD=${bconf_thd}
export ST_SIZE=${ST_SIZE}
export PFQ_CAP=${PFQ_CAP}

# Resolve this task's trace (list built identically to submit time)
mapfile -t TRACES < <(ls -1 "${TRACE_DIR}"/*.champsimtrace.xz 2>/dev/null | sort)
IDX=\$((SGE_TASK_ID - 1))
TRACE_FILE="\${TRACES[\$IDX]}"
TRACE_NAME=\$(basename "\$TRACE_FILE" .champsimtrace.xz)

if [ ! -f "\$TRACE_FILE" ]; then
  echo "ERROR: trace not found: \$TRACE_FILE" >&2
  exit 1
fi

RUN_DIR="${RESULTS_BASE}/${exp_name}/\${TRACE_NAME}"
mkdir -p "\$RUN_DIR"

cat > "\$RUN_DIR/run_info.txt" << INFO
exp_name=${exp_name}
trace=\$TRACE_NAME
dppred=${dppred}
cbpred=${cbpred}
pconf_thd=${pconf_thd}
bconf_thd=${bconf_thd}
pfq_cap=${PFQ_CAP}
st_size=${ST_SIZE}
warmup=${warmup}
sim=${sim}
INFO

echo "Running experiment: ${exp_name}, trace: \$TRACE_NAME"
"${BIN}" --warmup_instructions ${warmup} --simulation_instructions ${sim} "\$TRACE_FILE" \
  > "\$RUN_DIR/stdout.log" 2> "\$RUN_DIR/stderr.log"
rc=\$?

date
echo "Exit code: \$rc"
exit \$rc
EOF

  chmod +x "$job_script"
  qsub "$job_script"
  echo "Submitted: ${exp_name} (tasks ${task_range})"
}

if [ "$DEBUG" -eq 1 ]; then
  submit_job "pthd6" 1 0 6 0
  submit_job "pthd6_bthd6" 1 1 6 6
else
  # Baseline: both predictors off
  submit_job "baseline" 0 0 0 0

  # dpPred only: sweep pconf_thd from 0 to 6
  for thd in $(seq 0 6); do
    submit_job "pthd${thd}" 1 0 "$thd" 0
  done

  # dpPred + cbPred: sweep both thresholds
  for pthd in $(seq 0 6); do
    for bthd in $(seq 0 6); do
      submit_job "pthd${pthd}_bthd${bthd}" 1 1 "$pthd" "$bthd"
    done
  done
fi
