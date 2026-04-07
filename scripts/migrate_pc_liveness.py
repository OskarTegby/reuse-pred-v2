#!/usr/bin/env python3
"""migrate_pc_liveness.py — one-time migration for pre-CSV per-PC liveness data.

Walks all champsim.out files under one or more results directories, extracts
the old PER-PC LIVENESS text blocks, and writes a pc_liveness.csv next to each
champsim.out.  Files that already have a pc_liveness.csv are skipped unless
--force is given.

Usage
-----
    python3 scripts/migrate_pc_liveness.py results/<old-run>/
    python3 scripts/migrate_pc_liveness.py results/run1/ results/run2/ --force
"""

import argparse
import csv
import re
import sys
from pathlib import Path

CACHE_NAMES = ["cpu0_STLB", "LLC"]

ROW_PAT = re.compile(
    r"0x([0-9a-fA-F]+)\s+(\d+)\s+"
    r"(\d+)\s+\([\d.]+%\)\s+"
    r"(\d+)\s+\([\d.]+%\)\s+"
    r"(\d+)\s+\([\d.]+%\)"
)


def extract_entries(text: str, cache_name: str):
    header_pat = re.compile(
        r"^" + re.escape(cache_name) + r" PER-PC LIVENESS \(\d+ PCs",
        re.MULTILINE,
    )
    m = header_pat.search(text)
    if not m:
        return []
    return [
        (cache_name,
         f"0x{int(rm.group(1), 16):016x}",
         int(rm.group(2)),
         int(rm.group(3)),
         int(rm.group(4)),
         int(rm.group(5)))
        for rm in ROW_PAT.finditer(text[m.start():])
    ]


def migrate(out_file: Path, force: bool) -> str:
    csv_path = out_file.parent / "pc_liveness.csv"
    if csv_path.exists() and not force:
        return "skipped (already exists)"

    text = out_file.read_text(errors="replace")
    rows = []
    for name in CACHE_NAMES:
        rows.extend(extract_entries(text, name))

    if not rows:
        return "skipped (no PER-PC LIVENESS block found)"

    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cache", "pc", "evictions", "doa", "mostly_dead", "mostly_alive"])
        w.writerows(rows)

    return f"wrote {len(rows)} rows"


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dirs", nargs="+", type=Path,
                        help="Results directories to migrate")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing pc_liveness.csv files")
    args = parser.parse_args()

    out_files = []
    for d in args.dirs:
        if not d.is_dir():
            print(f"ERROR: not a directory: {d}", file=sys.stderr)
            sys.exit(1)
        found = sorted(d.glob("**/champsim.out"))
        if not found:
            print(f"WARNING: no champsim.out files found under {d}")
        out_files.extend(found)

    if not out_files:
        print("No champsim.out files found — nothing to do.")
        sys.exit(0)

    n_written = n_skipped = n_missing = 0
    for f in out_files:
        result = migrate(f, args.force)
        print(f"  {f.parent.name}: {result}")
        if result.startswith("wrote"):
            n_written += 1
        elif "no PER-PC" in result:
            n_missing += 1
        else:
            n_skipped += 1

    print(f"\nDone: {n_written} written, {n_skipped} skipped, {n_missing} had no data.")


if __name__ == "__main__":
    main()
