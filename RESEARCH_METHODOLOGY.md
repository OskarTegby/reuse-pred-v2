# Research Methodology

## Before submitting any cluster job

**Debug offline first.**
Run the binary locally (or as a single-trace, short job on the cluster) before submitting a sweep.
Use 25M warmup / 50M sim for any verification run — half the standard time is enough to catch bugs.

Check three things before declaring a debug run valid:
1. The binary produces the expected output format (e.g. `LIVENESS_CHAR BEGIN`, `SRRIP-Live STATS`, non-zero activation rate).
2. The metric you are testing actually varies (e.g. IPC differs between thd=1 and thd=8).
3. The `run_info.txt` confirms the env vars you intended were actually set.

**Read the code before building.**
Before building and transferring a binary, read the changed functions in full — not just the diff.
Confirm that every env var the code reads is also exported in `run_cs.sh`, and that empty-string exports (`VAR=${}`) do not silently disable the feature.

**Commit before submitting full runs.**
Every full sweep must be attached to a commit hash. The workflow is:
1. Write and verify the code change (small test passes).
2. Commit with a short description of what changed and why.
3. Record the commit hash, config file, result directory label, and a one-line description in `results/paper/DATA_LOG.md`.
4. Submit the full jobs.

## Tracking results

Every result directory must have a corresponding entry in `DATA_LOG.md` with:
- Commit hash at time of submission
- Config file used (or the key parameters if no config file)
- Submission timestamp and job IDs
- What question the run is answering
- Any known caveats or follow-up needed

The result directory name encodes the date (`_YYYYMMDD_HHMM`), which ties it to the log entry.

## Branching and commit discipline

Use **dedicated AI branches** for exploratory or AI-assisted work.
Do not commit directly to `main` from an AI session.

Workflow:
1. Work on an `ai/<topic>` branch during the session. Commits here can be rough.
2. Before merging, create a clean branch (`feature/<topic>`) and cherry-pick or squash the commits you want to keep, rewriting messages to explain the *why* not the *what*.
3. Read every changed file before the clean commit. The clean commit is yours — you own it.
4. Merge the clean branch to `main` with `--no-ff`.

This means the `main` history stays readable and every commit reflects your understanding of the code, not the AI's.

## Summary checklist

Before any full cluster submission:
- [ ] Binary tested locally or with a 1–5 trace debug run
- [ ] Key metric varies as expected across the parameter being swept
- [ ] `run_info.txt` from debug run confirms all env vars
- [ ] Code read and understood (not just diffed)
- [ ] Committed with a descriptive message
- [ ] `DATA_LOG.md` updated with commit hash, config, job IDs, and purpose
