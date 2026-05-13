#!/usr/bin/env bash
# _manifest.sh — sourced by sweep scripts to write a run_manifest.txt.
#
# Requires the calling script to have set:
#   PROJECT_ROOT, BASE_LABEL
# and optionally: token (suite name), BINARY, WARMUP, SIM.
#
# Usage in a sweep script:
#   source "${SCRIPT_DIR}/_manifest.sh"
#   ...
#   write_manifest       # call after BASE_LABEL is defined

write_manifest() {
    local dir="${PROJECT_ROOT}/results/${BASE_LABEL}"
    mkdir -p "$dir"
    {
        echo "date=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "host=$(hostname -f 2>/dev/null || hostname)"
        echo "git_commit=$(git -C "${PROJECT_ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)"
        echo "git_branch=$(git -C "${PROJECT_ROOT}" symbolic-ref --short HEAD 2>/dev/null || echo detached)"
        echo "git_dirty=$(git -C "${PROJECT_ROOT}" diff --quiet HEAD 2>/dev/null && echo clean || echo dirty)"
        echo "suite=${token:-unknown}"
        echo "binary=${BINARY:-unknown}"
        echo "warmup=${WARMUP:-unknown}"
        echo "sim=${SIM:-unknown}"
    } > "${dir}/run_manifest.txt"
}
