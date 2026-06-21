#!/usr/bin/env bash
# trace_pressure_filter.sh — Task-ID lists for traces with LLC pressure
# (>= 10,000 LLC misses in SRRIP baseline). Excludes LLC-inert traces
# (e.g. perlbench slices with working sets that fit in L2C).
#
# Usage: source this file, then use $PRESSURE_IDS[suite] in qsub -t
#   source scripts/submit/trace_pressure_filter.sh
#   qsub -t "${PRESSURE_IDS[dpc3]}" ...
#
# Generated from: {suite}_thd_rebaseline_20260605_2316/srrip (dpc3/gap/gms/ligra/ml)
#                 qmm_thd_rebaseline_20260604_2307/srrip (qmm)
# Threshold: >= 10,000 LLC MISS during 100M simulation instructions.

declare -A PRESSURE_IDS PRESSURE_N

PRESSURE_IDS[dpc3]="3,4,5,6,7,9,10,11,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,54,55,61,63,64,65,66,67,78,79,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95"
PRESSURE_IDS[gap]="1,2,3,4,5,6,7,8,9"
PRESSURE_IDS[gms]="1,2,3,4,5,6,7,8,9,10,11"
PRESSURE_IDS[ligra]="1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17"
PRESSURE_IDS[ml]="1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31"
PRESSURE_IDS[qmm]="1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45"

PRESSURE_N[dpc3]=71
PRESSURE_N[gap]=9
PRESSURE_N[gms]=11
PRESSURE_N[ligra]=17
PRESSURE_N[ml]=31
PRESSURE_N[qmm]=45
