#!/usr/bin/env python3

# Run the black-box tests on the cluster with automatic queue management.
#
#   Usage: blackbox_run_cluster.py           # compare against expected/
#          blackbox_run_cluster.py generate  # write new expected/ outputs

import base64
import glob
import os
import re
import shutil
import subprocess
import sys
import time

ABDET = "otegby@abdet.inf.um.es"
ROOT = "/home/users/otegby/ChampSim-dev"
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
EXPECTED_DIR = os.path.join(REPO, "test/blackbox/expected")
LOCAL_OUT_DIR = os.path.join(REPO, "test/blackbox/test_outputs_cluster")
CHECK = os.path.join(REPO, "test/blackbox/check_progress.py")
RUNNER = os.path.join(REPO, "test/blackbox/run_scenario.py")
POLL_INTERVAL = 30
STUCK_TIMEOUT = 900


def now():
    return time.strftime("%H:%M:%S")


def log(msg):
    print("[%s] %s" % (now(), msg))


class ClusterState:
    def __init__(self):
        self.released = False
        self.qw_jobs = ""
        self.bb_ids = ""


# The command is base64-encoded so it survives two layers of SSH quoting
# intact -- single quotes inside awk/grep programs would otherwise terminate
# a naive single-quote wrapper and silently break the command.
def ca(cmd, capture=True, check=False):
    b64 = base64.b64encode(cmd.encode()).decode()
    inner = 'ssh otegby@castillo.inf.um.es "echo %s | base64 -d | bash"' % b64
    argv = ["ssh", "-o", "BatchMode=yes", ABDET, inner]
    if capture:
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    else:
        result = subprocess.run(argv)
    if check and result.returncode != 0:
        raise RuntimeError("ca() failed (exit %d): %r" % (result.returncode, cmd))
    return result.stdout.rstrip("\n") if capture else None


def cancel_job(scen):
    b64 = base64.b64encode(("qdel bb_%s" % scen).encode()).decode()
    inner = 'ssh otegby@castillo.inf.um.es "echo %s | base64 -d | bash"' % b64
    argv = ["ssh", "-o", "BatchMode=yes", ABDET, inner]
    subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def download_partials():
    cmd = (
        'ssh %s "ssh otegby@castillo.inf.um.es \'tar czf - -C %s/test/blackbox/test_outputs .\'" '
        '2>/dev/null | tar xzf - -C %s 2>/dev/null'
    ) % (ABDET, ROOT, LOCAL_OUT_DIR)
    subprocess.run(cmd, shell=True)


def _count_matching_lines(raw, bb_ids):
    if not bb_ids:
        return 0
    ids = set(bb_ids.split("|"))
    return sum(1 for line in raw.splitlines() if line in ids)


# Echoes -1 if qstat/SSH returned nothing at all (a transient failure), so the
# caller does not mistake an SSH blip for "queue drained" -- held qw jobs
# always keep a real qstat non-empty.
def jobs_in_queue(state):
    raw = ca("qstat -u otegby 2>/dev/null | awk 'NR>1{print $1}'")
    if not raw:
        return -1
    return _count_matching_lines(raw, state.bb_ids)


# Echoes -1 on an SSH/qstat blip so a transient failure is not misread as
# "all launched".
def bb_waiting(state):
    raw = ca("qstat -u otegby 2>/dev/null | awk 'NR>1 && $5 ~ /qw/{print $1}'")
    if not raw:
        return -1
    return _count_matching_lines(raw, state.bb_ids)


def qrls_held(state):
    if state.released:
        return
    state.released = True
    if not state.qw_jobs:
        return
    print("")
    log("Releasing held jobs...")
    ca("qrls %s 2>&1 | grep -c 'modified hold'" % state.qw_jobs, capture=False)
    log("Done.")


def release_when_launched(state):
    if state.released:
        return
    if not state.qw_jobs:
        state.released = True
        return
    if bb_waiting(state) == 0:
        log("All bb jobs launched; releasing held jobs.")
        qrls_held(state)


def hold_queued_jobs(state):
    log("Identifying queued jobs to hold...")
    raw = ca(
        'qstat -u otegby 2>/dev/null | awk \'NR>1 && $5=="qw"{print $1}\' | sort -u | tr "\\n" " "',
        check=True,
    )
    state.qw_jobs = raw.rstrip(" ")
    if state.qw_jobs:
        held_count = ca("qhold %s 2>&1 | grep -c 'modified hold'" % state.qw_jobs)
        if not held_count:
            held_count = "0"
        log("Held %s tasks from: %s" % (held_count, state.qw_jobs))
    else:
        log("No queued jobs to hold.")


# Outputs from a previous run must be removed first: otherwise the first poll
# would download already-complete files and report FULL_PASS instantly,
# before this run's jobs have even started.
def clear_stale_outputs():
    log("Clearing previous outputs...")
    ca("rm -f %s/test/blackbox/test_outputs/*.out" % ROOT, capture=False)
    for f in glob.glob(os.path.join(LOCAL_OUT_DIR, "*.out")):
        os.remove(f)


def submit_bb_jobs(state):
    log("Submitting black-box jobs...")
    submit_out = ca("python3 %s/scripts/submit/blackbox_validation.py 2>&1" % ROOT, check=True)
    ids = re.findall(r"(?<=job )\d+", submit_out)
    state.bb_ids = "|".join(ids)
    n_bb = sum(1 for line in submit_out.splitlines() if "has been submitted" in line)
    log("Submitted %d jobs (IDs: %s)" % (n_bb, " ".join(ids)))
    return n_bb


# SGE has a small delay between qsub returning and jobs appearing in qstat.
def wait_for_jobs_to_register(state):
    log("Waiting for jobs to register...")
    for _ in range(24):
        if jobs_in_queue(state) > 0:
            break
        time.sleep(5)


def classify_scenario(actual_path, expected_path):
    result = subprocess.run(
        ["python3", CHECK, actual_path, expected_path],
        stdout=subprocess.PIPE, universal_newlines=True,
    )
    return result.stdout.strip()


def count_newlines(path):
    try:
        with open(path, "rb") as f:
            return f.read().count(b"\n")
    except FileNotFoundError:
        return 0


def print_diff_excerpt(expected_path, actual_path):
    result = subprocess.run(
        ["diff", expected_path, actual_path],
        stdout=subprocess.PIPE, universal_newlines=True,
    )
    changed = [l for l in result.stdout.splitlines() if l.startswith("<") or l.startswith(">")]
    for line in changed[:6]:
        print("      " + line)


def run_generate_mode(state, scenarios, n_bb):
    log("Waiting for jobs to finish (poll %ds)..." % POLL_INTERVAL)
    while True:
        running = jobs_in_queue(state)
        if running >= 0:
            log("%d/%d jobs still in queue" % (running, n_bb))
        release_when_launched(state)
        if running == 0:
            break
        time.sleep(POLL_INTERVAL)
    download_partials()
    log("Writing reference outputs to expected/...")
    os.makedirs(EXPECTED_DIR, exist_ok=True)  # may not exist if all references were removed
    for scen in scenarios:
        shutil.copyfile(
            os.path.join(LOCAL_OUT_DIR, scen + ".out"),
            os.path.join(EXPECTED_DIR, scen + ".out"),
        )
    subprocess.run(["git", "-C", REPO, "add", "test/blackbox/expected/"], check=True)
    subprocess.run(
        ["git", "-C", REPO, "commit", "-m", "test: update expected outputs from cluster full runs"],
        check=True,
    )
    log("Done — expected/ updated and committed.")
    qrls_held(state)
    sys.exit(0)


def run_verify_mode(state, scenarios):
    log("Incremental verification (poll %ds)." % POLL_INTERVAL)
    print("  states: PENDING < RUNNING < SOFT_PASS (>=20M sim, on track) < FULL_PASS;  FAIL = diverged")
    prev = {}
    lines = {}
    stall_since = {}
    while True:
        download_partials()
        counts = {
            "PENDING": 0, "RUNNING": 0, "SOFT_PASS": 0,
            "FULL_PASS": 0, "FAIL": 0, "NO-REFERENCE": 0,
        }
        for scen in scenarios:
            actual = os.path.join(LOCAL_OUT_DIR, scen + ".out")
            expected = os.path.join(EXPECTED_DIR, scen + ".out")
            st = classify_scenario(actual, expected)

            if st in ("RUNNING", "SOFT_PASS"):
                cur = count_newlines(actual)
                if cur > lines.get(scen, 0):
                    lines[scen] = cur
                    stall_since[scen] = time.time()
                elif time.time() - stall_since.get(scen, time.time()) >= STUCK_TIMEOUT:
                    print("  [%s] STUCK      %s — no output for %ds; cancelling bb_%s"
                          % (now(), scen, STUCK_TIMEOUT, scen))
                    cancel_job(scen)
                    st = "FAIL"
                    prev[scen] = "FAIL"

            counts[st] += 1

            if prev.get(scen) != st:
                if st == "SOFT_PASS":
                    print("  [%s] SOFT PASS  %s — >=20M sim verified, on track" % (now(), scen))
                elif st == "FULL_PASS":
                    print("  [%s] FULL PASS  %s — fully verified" % (now(), scen))
                elif st == "FAIL":
                    print("  [%s] FAIL       %s — diverged from expected:" % (now(), scen))
                    print_diff_excerpt(expected, actual)
                    print("      cancelling doomed job bb_%s" % scen)
                    cancel_job(scen)
                prev[scen] = st

        print("[%s] pending:%d running:%d soft:%d full:%d FAIL:%d"
              % (now(), counts["PENDING"], counts["RUNNING"], counts["SOFT_PASS"],
                 counts["FULL_PASS"], counts["FAIL"]))
        release_when_launched(state)

        if counts["FULL_PASS"] + counts["FAIL"] + counts["NO-REFERENCE"] == len(scenarios):
            break
        # Safety net: if the queue drained but some scenario never completed
        # (a job crashed), stop instead of polling forever; the final report
        # flags it.
        if jobs_in_queue(state) == 0:
            log("queue drained; finalizing.")
            time.sleep(3)
            download_partials()
            break
        time.sleep(POLL_INTERVAL)


def print_final_report(scenarios):
    print("")
    print("═" * 40)
    print("  BLACK-BOX RESULTS (cluster / full)  ")
    print("═" * 40)
    passed = 0
    failed = 0
    for scen in scenarios:
        actual = os.path.join(LOCAL_OUT_DIR, scen + ".out")
        expected = os.path.join(EXPECTED_DIR, scen + ".out")
        st = classify_scenario(actual, expected)
        if st == "FULL_PASS":
            print("  %-32s PASS" % scen)
            passed += 1
        elif st == "FAIL":
            print("  %-32s FAIL" % scen)
            failed += 1
        else:
            print("  %-32s INCOMPLETE (%s)" % (scen, st))
            failed += 1
    print("")
    if failed == 0:
        print("  ALL PASSED (%d/%d)" % (passed, passed + failed))
    else:
        print("  %d FAILED/INCOMPLETE, %d passed (%d/%d)" % (failed, passed, passed, passed + failed))
    print("═" * 40)


def main(argv):
    sys.stdout.reconfigure(line_buffering=True)
    mode = argv[1] if len(argv) > 1 else "verify"
    state = ClusterState()

    os.makedirs(LOCAL_OUT_DIR, exist_ok=True)

    scenarios = subprocess.run(
        ["python3", RUNNER, "--list"],
        stdout=subprocess.PIPE, universal_newlines=True, check=True,
    ).stdout.splitlines()

    hold_queued_jobs(state)
    clear_stale_outputs()
    n_bb = submit_bb_jobs(state)
    wait_for_jobs_to_register(state)

    if mode == "generate":
        run_generate_mode(state, scenarios, n_bb)
        return 0

    run_verify_mode(state, scenarios)
    print_final_report(scenarios)
    qrls_held(state)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
