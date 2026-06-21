#!/usr/bin/env python3
"""QMM promotion-buffer study: lfu_doa vs tiered, with and without buffer.

Plots geomean speedup vs SRRIP (%) for QMM as a function of main table capacity,
with one curve per (policy, buf_cap) combination.

Usage:
  python3 plot_buf_study.py <run_label>
  e.g.  plot_buf_study.py qmm_buf_study_20260620_1234

Baseline: results/baselines/srrip/qmm/ (canonical champsim_srrip)
Unbounded reference: results/size_srrip_live_unbound_20260619_2009/qmm/unbound/
"""

import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"

CAPS    = [64, 128, 256, 512, 1024]
BUFS    = [0, 128, 256]
POLICIES = ["lfu_doa", "tiered"]

COLORS = {
    "lfu_doa": "#1f77b4",
    "tiered":  "#d62728",
}
STYLES = {
    0:   "-",
    128: "--",
    256: ":",
}
MARKERS = {
    0:   "o",
    128: "s",
    256: "^",
}


def get_ipc(p: Path):
    try:
        with open(p) as f:
            for line in f:
                if "CPU 0 cumulative IPC:" in line:
                    return float(line.split()[4])
    except Exception:
        pass
    return None


def geomean_pct(pairs):
    if not pairs:
        return None
    return (math.exp(sum(math.log(m / b) for m, b in pairs) / len(pairs)) - 1.0) * 100


def main():
    if len(sys.argv) < 2:
        print("Usage: plot_buf_study.py <run_label>")
        sys.exit(1)
    label = sys.argv[1]

    srrip_dir = RESULTS / "baselines" / "srrip" / "qmm"
    unbound_d = RESULTS / "size_srrip_live_unbound_20260619_2009" / "qmm" / "unbound"

    srrip_ipc = {}
    for td in srrip_dir.iterdir():
        b = get_ipc(td / "champsim.out")
        if b:
            srrip_ipc[td.name] = b

    if not srrip_ipc:
        print("No SRRIP baseline data found"); sys.exit(1)

    # Unbounded reference
    unb_pairs = []
    for name, b in srrip_ipc.items():
        u = get_ipc(unbound_d / name / "champsim.out")
        if u:
            unb_pairs.append((u, b))
    unb_pct = geomean_pct(unb_pairs) if unb_pairs else None
    if unb_pct:
        print(f"Unbounded reference: {unb_pct:+.2f}%  (n={len(unb_pairs)})")

    fig, ax = plt.subplots(figsize=(8, 4.5))

    x = list(range(len(CAPS)))

    for policy in POLICIES:
        for buf in BUFS:
            ys, ns = [], []
            for cap in CAPS:
                run_dir = RESULTS / label / f"{policy}_c{cap}_b{buf}"
                if not run_dir.is_dir():
                    ys.append(None); ns.append(0)
                    continue
                pairs = []
                for name, b in srrip_ipc.items():
                    m = get_ipc(run_dir / name / "champsim.out")
                    if m:
                        pairs.append((m, b))
                pct = geomean_pct(pairs) if len(pairs) >= 3 else None
                ys.append(pct); ns.append(len(pairs))
                if pct is not None:
                    print(f"  {policy} cap={cap:4d} buf={buf:3d}: {pct:+.2f}%  (n={len(pairs)})")

            xs_v = [x[i] for i, y in enumerate(ys) if y is not None]
            ys_v = [y for y in ys if y is not None]
            if not xs_v:
                continue

            lbl = f"{policy} buf={buf}"
            ax.plot(xs_v, ys_v,
                    color=COLORS[policy],
                    linestyle=STYLES[buf],
                    marker=MARKERS[buf],
                    markersize=5, linewidth=1.5,
                    label=lbl)

    if unb_pct is not None:
        ax.axhline(y=unb_pct, color="black", linestyle="--", linewidth=1.0, alpha=0.6,
                   label=f"Unbounded ({unb_pct:+.1f}%)")

    ax.axhline(y=0, color="black", linewidth=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels([str(c) for c in CAPS], fontsize=9)
    ax.set_xlabel("Main table capacity (entries)", fontsize=10)
    ax.set_ylabel("Geomean speedup vs SRRIP (%)", fontsize=10)
    ax.tick_params(axis="y", labelsize=9)
    ax.legend(frameon=False, fontsize=8, ncol=2)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()

    out = ROOT / "results" / "plots" / f"buf_study_{label.split('_', 3)[-1]}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
