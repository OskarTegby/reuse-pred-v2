#!/usr/bin/env python3
"""plot_debug_bypass.py — validate weighted-bypass behavior on a single trace.

Parses champsim.out files from the three debug configs (baseline,
cbpred_unweighted, cbpred_weighted) and produces a 2×2 figure:

  [0,0] IPC relative to baseline
  [0,1] LLC bypass events (bypasses, correct, incorrect) per kilo-instr
  [1,0] Bypass accuracy: correct vs incorrect %
  [1,1] Weighted-bhist DoA insert breakdown (normal vs pessimistic per KI)

Usage:
    python3 scripts/analysis/plot_debug_bypass.py <results/debug_bypass/srv_128>
    python3 scripts/analysis/plot_debug_bypass.py <dir> [--out fig.png]
"""

import argparse
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

CONFIGS = ["baseline", "cbpred_unweighted", "cbpred_weighted"]
LABELS  = ["Baseline\n(no bypass)", "CBPRED\n(unweighted)", "CBPRED\n(weighted)"]
COLORS  = ["#888888", "#4C9BE8", "#2E8B6A"]


# ── Parser ────────────────────────────────────────────────────────────────────

def _int(m, group=1):
    return int(m.group(group)) if m else None


def parse_out(path: Path) -> dict:
    d = dict(
        ipc=None, instrs=None,
        llc_bypasses=None,
        bypass_correct=None, bypass_incorrect=None,
        cbpred_doa_normal=None, cbpred_doa_pessimistic=None,
        llc_miss=None,
        pfq_probes=None, pfq_hits=None,
        bhist_lookups=None, bhist_hits=None,
    )
    in_roi = False
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return d
    for line in text.splitlines():
        if "Region of Interest Statistics" in line:
            in_roi = True
        if not in_roi:
            continue
        if d["ipc"] is None:
            m = re.search(r"cumulative IPC:\s+([\d.]+)", line)
            if m:
                d["ipc"] = float(m.group(1))
        if d["instrs"] is None:
            m = re.search(r"instructions:\s+(\d+)", line)
            if m:
                d["instrs"] = int(m.group(1))
        # LLC bypasses
        m = re.fullmatch(r"LLC BYPASSES:\s+(\d+)", line.strip())
        if m:
            d["llc_bypasses"] = int(m.group(1))
        # Bypass accuracy
        m = re.search(r"LLC BYPASS ACCURACY:.*incorrect=(\d+).*correct=(\d+)", line)
        if m:
            d["bypass_incorrect"] = int(m.group(1))
            d["bypass_correct"]   = int(m.group(2))
        # Weighted DoA insert breakdown
        m = re.search(r"LLC CBPRED DOA INSERTS:.*normal=(\d+).*pessimistic=(\d+)", line)
        if m:
            d["cbpred_doa_normal"]      = int(m.group(1))
            d["cbpred_doa_pessimistic"] = int(m.group(2))
        # LLC total miss
        if d["llc_miss"] is None and re.match(r"LLC TOTAL\s+ACCESS:", line):
            m = re.search(r"MISS:\s+(\d+)", line)
            if m:
                d["llc_miss"] = int(m.group(1))
        # PFQ
        m = re.search(r"LLC PFQ PROBES:\s+(\d+)\s+HITS:\s+(\d+)", line)
        if m:
            d["pfq_probes"] = int(m.group(1))
            d["pfq_hits"]   = int(m.group(2))
        # BHIST
        m = re.search(r"LLC BHIST LOOKUPS:\s+(\d+)\s+HITS:\s+(\d+)", line)
        if m:
            d["bhist_lookups"] = int(m.group(1))
            d["bhist_hits"]    = int(m.group(2))
    return d


# ── Plot ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir", type=Path,
                    help="Directory containing baseline/, cbpred_unweighted/, cbpred_weighted/ sub-dirs")
    ap.add_argument("--out", type=Path, default=None,
                    help="Output PNG path (default: <results_dir>/debug_bypass.png)")
    args = ap.parse_args()

    root = args.results_dir
    out  = args.out or root / "debug_bypass.png"

    data = {}
    for cfg in CONFIGS:
        p = root / cfg / "champsim.out"
        if not p.exists():
            print(f"WARNING: {p} not found", file=sys.stderr)
        data[cfg] = parse_out(p)

    base_ipc = data["baseline"]["ipc"] or 1.0
    ki = {cfg: (data[cfg]["instrs"] or 1) / 1000 for cfg in CONFIGS}

    fig, axes = plt.subplots(2, 2, figsize=(10, 7))
    fig.suptitle(f"CBPRED Weighted-Bypass Debug: {root.name}", fontsize=12, fontweight="bold")

    x = np.arange(len(CONFIGS))
    bar_w = 0.5

    # ── [0,0] Relative IPC ───────────────────────────────────────────────────
    ax = axes[0, 0]
    rel = [(data[cfg]["ipc"] or 0) / base_ipc for cfg in CONFIGS]
    bars = ax.bar(x, rel, bar_w, color=COLORS, edgecolor="white", linewidth=0.8)
    ax.axhline(1.0, color="black", linewidth=0.8, linestyle="--")
    ax.set_title("IPC relative to Baseline")
    ax.set_xticks(x); ax.set_xticklabels(LABELS, fontsize=8)
    ax.set_ylabel("Speedup")
    for bar, v in zip(bars, rel):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.001,
                f"{v:.3f}", ha="center", va="bottom", fontsize=7)

    # ── [0,1] LLC bypass events per KI ──────────────────────────────────────
    ax = axes[0, 1]
    bypasses = [(data[cfg]["llc_bypasses"] or 0) / ki[cfg] for cfg in CONFIGS]
    corrects  = [(data[cfg]["bypass_correct"]   or 0) / ki[cfg] for cfg in CONFIGS]
    incorrects= [(data[cfg]["bypass_incorrect"] or 0) / ki[cfg] for cfg in CONFIGS]
    ax.bar(x - bar_w*0.33, bypasses,  bar_w*0.33, label="bypasses",  color=COLORS, edgecolor="white", alpha=0.9)
    ax.bar(x,              corrects,  bar_w*0.33, label="correct",   color="#5DBB63", edgecolor="white", alpha=0.9)
    ax.bar(x + bar_w*0.33, incorrects,bar_w*0.33, label="incorrect", color="#D9534F", edgecolor="white", alpha=0.9)
    ax.set_title("LLC Bypass Events per KI")
    ax.set_xticks(x); ax.set_xticklabels(LABELS, fontsize=8)
    ax.set_ylabel("Events / KI")
    ax.legend(fontsize=7)

    # ── [1,0] Bypass accuracy % ──────────────────────────────────────────────
    ax = axes[1, 0]
    correct_pct   = []
    incorrect_pct = []
    for cfg in CONFIGS:
        c = data[cfg]["bypass_correct"]   or 0
        i = data[cfg]["bypass_incorrect"] or 0
        total = c + i or 1
        correct_pct.append(100 * c / total)
        incorrect_pct.append(100 * i / total)
    ax.bar(x - bar_w*0.25, correct_pct,   bar_w*0.5, label="correct %",   color="#5DBB63", edgecolor="white")
    ax.bar(x + bar_w*0.25, incorrect_pct, bar_w*0.5, label="incorrect %", color="#D9534F", edgecolor="white")
    ax.axhline(50, color="gray", linewidth=0.8, linestyle=":")
    ax.set_ylim(0, 110)
    ax.set_title("Bypass Accuracy (%)")
    ax.set_xticks(x); ax.set_xticklabels(LABELS, fontsize=8)
    ax.set_ylabel("% of resolved bypasses")
    ax.legend(fontsize=7)
    for xi, (cp, ip) in enumerate(zip(correct_pct, incorrect_pct)):
        if cp + ip > 0:
            ax.text(xi - bar_w*0.25, cp + 1, f"{cp:.1f}", ha="center", va="bottom", fontsize=7)
            ax.text(xi + bar_w*0.25, ip + 1, f"{ip:.1f}", ha="center", va="bottom", fontsize=7)

    # ── [1,1] Weighted DoA insert breakdown per KI ──────────────────────────
    ax = axes[1, 1]
    normals  = [(data[cfg]["cbpred_doa_normal"]      or 0) / ki[cfg] for cfg in CONFIGS]
    pessims  = [(data[cfg]["cbpred_doa_pessimistic"] or 0) / ki[cfg] for cfg in CONFIGS]
    ax.bar(x - bar_w*0.25, normals, bar_w*0.5, label="normal inserts\n(→ bhist += W_NORMAL)",
           color="#4C9BE8", edgecolor="white")
    ax.bar(x + bar_w*0.25, pessims, bar_w*0.5, label="pessimistic inserts\n(→ bhist += W_LOW)",
           color="#F0A030", edgecolor="white")
    ax.set_title("Weighted-bhist DoA Insert Breakdown per KI")
    ax.set_xticks(x); ax.set_xticklabels(LABELS, fontsize=8)
    ax.set_ylabel("Events / KI")
    ax.legend(fontsize=7)
    # Annotate ratio for weighted config
    if normals[2] + pessims[2] > 0:
        ratio = normals[2] / (normals[2] + pessims[2])
        ax.text(2, max(normals[2], pessims[2]) * 1.02,
                f"normal {ratio*100:.1f}%", ha="center", fontsize=7, color="#4C9BE8")

    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved: {out}")

    # ── Console summary ──────────────────────────────────────────────────────
    print("\n=== Summary ===")
    for cfg, lbl in zip(CONFIGS, LABELS):
        d = data[cfg]
        ipc = d["ipc"]
        rel_ipc = (ipc or 0) / base_ipc
        bypasses = d["llc_bypasses"] or 0
        c = d["bypass_correct"]   or 0
        i = d["bypass_incorrect"] or 0
        total = c + i or 1
        acc = 100 * c / total
        n = d["cbpred_doa_normal"] or 0
        p = d["cbpred_doa_pessimistic"] or 0
        print(f"\n{lbl.replace(chr(10),' ')}")
        print(f"  IPC={ipc:.4f}  ({rel_ipc:+.3f}x baseline)")
        print(f"  LLC bypasses={bypasses}  correct={c} ({acc:.1f}%)  incorrect={i} ({100-acc:.1f}%)")
        if n + p > 0:
            print(f"  DoA inserts: normal={n}  pessimistic={p}  (normal fraction={100*n/(n+p):.1f}%)")
        else:
            print(f"  DoA inserts: (none tracked — CBPRED_WEIGHTED=0 or no bypasses)")


if __name__ == "__main__":
    main()
