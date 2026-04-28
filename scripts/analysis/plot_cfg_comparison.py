#!/usr/bin/env python3
"""plot_cfg_comparison.py — bypass-predictor speedup across cache configurations.

Produces a strip chart with six clusters arranged as three suite groups of two:

    [ SPEC old | SPEC new ]   [ Google old | Google new ]   [ QMM old | QMM new ]

Each cluster shows jittered per-trace IPC speedup dots and a geomean diamond.
A table in the figure summarises the two hardware configurations in full.

Usage
-----
    python3 scripts/analysis/plot_cfg_comparison.py \\
        --old-qmm    results/qmm_20260322 \\
        --old-dpc3   results/dpc3_oldcfg_20260428_1717 \\
        --old-google results/google_oldcfg_20260428_1717 \\
        --new-qmm    results/dp_study/qmm_dp_study_20260428_1143 \\
        --new-dpc3   results/dp_study/dpc3_dp_study_20260428_1143 \\
        --new-google results/dp_study/google_dp_study_20260428_1143 \\
        --out        results/plots/cfg_comparison/cfg_comparison.png

Any suite argument may be omitted; that suite is simply skipped.
"""

import argparse
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import matplotlib.pyplot as plt
import numpy as np

Y_LO, Y_HI = -2.0, 5.0   # clip range; outliers are annotated

# ── Suite identity ────────────────────────────────────────────────────────────
SUITE_ORDER  = ["dpc3",        "google",  "qmm"]
SUITE_LABELS = ["SPEC (DPC3)", "Google",  "Qualcomm"]
SUITE_COLORS = ["#2C7BB6",     "#D7191C", "#1A9641"]

# ── Configuration identity ────────────────────────────────────────────────────
CONFIGS = [
    dict(
        key    = "old",
        label  = "Old",
        legend = "Old  (L2C 512 KB, LLC 20 cy)",
        color  = "#E07B4A",
    ),
    dict(
        key    = "new",
        label  = "New",
        legend = "New  (L2C 256 KB, LLC 40 cy)",
        color  = "#4393C3",
    ),
]

# ── Simpoint weights ──────────────────────────────────────────────────────────
_DEFAULT_WEIGHTS_DIR = (
    Path(__file__).parents[2] / ".." / "ChampSim-dev" / "trace-files" / "SPEC2006_weights"
).resolve()


def _load_spec_weights(d: Path) -> dict:
    result: dict = {}
    if not d.is_dir():
        return result
    for bm in sorted(d.iterdir()):
        wf = bm / "weights.out"; sf = bm / "simpoints.out"
        if not (wf.exists() and sf.exists()):
            continue
        for sp_id, w in zip([int(x) for x in sf.read_text().split()],
                            [float(x) for x in wf.read_text().split()]):
            result[f"{bm.name}-{sp_id}B"] = w
    return result


_SPEC_WEIGHTS = _load_spec_weights(_DEFAULT_WEIGHTS_DIR)


def _bm_name(wl: str) -> str:
    m = re.match(r'^(.+)-\d+[A-Z]+$', wl)
    return m.group(1) if m else wl


def _geomean_pct(sp: dict) -> float:
    groups: dict = {}
    for wl, v in sp.items():
        groups.setdefault(_bm_name(wl), []).append(wl)
    per_bench = []
    for wls in groups.values():
        ratios = {wl: sp[wl] / 100 + 1 for wl in wls}
        if _SPEC_WEIGHTS:
            pairs = [(ratios[wl], _SPEC_WEIGHTS.get(wl)) for wl in wls]
            if any(w is not None for _, w in pairs):
                pairs = [(r, w) for r, w in pairs if w is not None and r > 0]
                tw = sum(w for _, w in pairs)
                if tw > 0:
                    per_bench.append(float(np.exp(sum(w / tw * np.log(r) for r, w in pairs))))
                    continue
        vals = [ratios[wl] for wl in wls if ratios[wl] > 0]
        if vals:
            per_bench.append(float(np.exp(np.mean(np.log(vals)))))
    if not per_bench:
        return float("nan")
    return (float(np.exp(np.mean(np.log([r for r in per_bench if r > 0])))) - 1) * 100


# ── Parsing ───────────────────────────────────────────────────────────────────

def _parse_ipc(path: Path):
    in_roi = False
    try:
        for line in path.read_text(errors="replace").splitlines():
            if "Region of Interest Statistics" in line:
                in_roi = True
            if in_roi and "cumulative IPC:" in line:
                m = re.search(r"cumulative IPC:\s+([0-9.]+)", line)
                if m:
                    return float(m.group(1))
    except OSError:
        pass
    return None


def _load_speedups(suite_dir: Path, baseline_name: str, pred_name: str) -> dict:
    base_d = suite_dir / baseline_name
    pred_d = suite_dir / pred_name
    if not base_d.is_dir() or not pred_d.is_dir():
        return {}
    bases = {}
    for f in sorted(base_d.glob("*/champsim.out")):
        v = _parse_ipc(f)
        if v is not None:
            bases[f.parent.name] = v
    sp = {}
    for wl, b in bases.items():
        if b <= 0:
            continue
        p = _parse_ipc(pred_d / wl / "champsim.out")
        if p is not None:
            sp[wl] = (p / b - 1) * 100
    return sp


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    for s in SUITE_ORDER:
        ap.add_argument(f"--old-{s}", metavar="DIR", default=None)
        ap.add_argument(f"--new-{s}", metavar="DIR", default=None)
    ap.add_argument("--out", default="results/plots/cfg_comparison/cfg_comparison.png")
    args = ap.parse_args()

    # ── Load data ─────────────────────────────────────────────────────────────
    # data[suite_key][cfg_key] = {wl: speedup_%}
    data: dict = {}
    for skey in SUITE_ORDER:
        entry: dict = {}
        for cfg in CONFIGS:
            ckey = cfg["key"]
            dir_s = getattr(args, f"{ckey}_{skey}")
            if not dir_s:
                entry[ckey] = {}
                continue
            d = Path(dir_s)
            sp = _load_speedups(d, "baseline", "pred_6_6")
            if not sp:
                sp = _load_speedups(d, "baseline", "pthd6_bthd6")  # March naming
            if not sp:
                sp = _load_speedups(d, "lru", "lru_pred")           # dp_study naming
            if sp:
                print(f"  {ckey} {skey}: {len(sp)} traces from {d.name}")
            else:
                print(f"  {ckey} {skey}: no data in {d}", file=sys.stderr)
            entry[ckey] = sp
        if any(entry.values()):
            data[skey] = entry

    if not data:
        sys.exit("ERROR: no data loaded — check directory arguments")

    present_suites = [s for s in SUITE_ORDER if s in data]
    n_suites = len(present_suites)

    # ── Layout: two clusters per suite, gap between suites ───────────────────
    cluster_w = 0.55   # width allocated to each cluster
    gap       = 0.50   # extra gap between suite groups

    positions: dict = {}   # (suite, cfg_key) → x centre
    x = 0.0
    suite_centres: dict = {}
    for si, skey in enumerate(present_suites):
        xs_pair = []
        for cfg in CONFIGS:
            positions[(skey, cfg["key"])] = x + cluster_w / 2
            xs_pair.append(x + cluster_w / 2)
            x += cluster_w
        suite_centres[skey] = (xs_pair[0] + xs_pair[-1]) / 2
        x += gap    # gap between suites

    x_max = x - gap

    rng = np.random.default_rng(0)

    fig, ax = plt.subplots(figsize=(max(7, 3.5 * n_suites), 5.5))

    # Alternating suite background bands
    for si, skey in enumerate(present_suites):
        xs_pair = [positions[(skey, c["key"])] for c in CONFIGS
                   if (skey, c["key"]) in positions]
        if not xs_pair:
            continue
        lo = min(xs_pair) - cluster_w * 0.55
        hi = max(xs_pair) + cluster_w * 0.55
        if si % 2 == 0:
            ax.axvspan(lo, hi, color="gray", alpha=0.07, zorder=0)

    # Draw clusters
    for skey, slabel, suite_color in zip(SUITE_ORDER, SUITE_LABELS, SUITE_COLORS):
        if skey not in data:
            continue
        for cfg in CONFIGS:
            ckey  = cfg["key"]
            color = cfg["color"]
            sp    = data[skey][ckey]
            if not sp:
                continue
            xc   = positions[(skey, ckey)]
            vals = np.array(list(sp.values()))
            j    = rng.uniform(-cluster_w * 0.28, cluster_w * 0.28, size=len(vals))
            clipped = np.clip(vals, Y_LO, Y_HI)
            ax.scatter(xc + j, clipped, s=20, color=color,
                       edgecolors="none", alpha=0.55, zorder=2)
            n_above = int((vals > Y_HI).sum())
            n_below = int((vals < Y_LO).sum())
            if n_above:
                ax.annotate(
                    f"↑{n_above} (max {vals.max():.1f}%)",
                    xy=(xc, Y_HI), xytext=(0, 4), textcoords="offset points",
                    ha="center", va="bottom", fontsize=6.5, color=color,
                )
            if n_below:
                ax.annotate(
                    f"↓{n_below} (min {vals.min():.1f}%)",
                    xy=(xc, Y_LO), xytext=(0, -4), textcoords="offset points",
                    ha="center", va="top", fontsize=6.5, color=color,
                )
            gm = _geomean_pct(sp)
            ax.plot(xc, gm, marker="D", markersize=9, color=color,
                    markeredgecolor="black", markeredgewidth=0.8, zorder=4)
            ax.annotate(f"{gm:+.2f}%",
                        xy=(xc, gm), xytext=(0, 8), textcoords="offset points",
                        ha="center", fontsize=7.5, color=color, fontweight="bold")

    # x-ticks: one tick per cluster, labelled with config short name
    tick_xs    = [positions[(s, c["key"])] for s in present_suites
                  for c in CONFIGS if (s, c["key"]) in positions]
    tick_labels = [cfg["label"] for _ in present_suites for cfg in CONFIGS]
    ax.set_xticks(tick_xs)
    ax.set_xticklabels(tick_labels, fontsize=10)

    # Suite names above the x-axis, centred over each pair
    ax_ylim = ax.get_ylim()
    for skey, slabel in zip(present_suites, SUITE_LABELS):
        ax.text(suite_centres[skey], -0.085, slabel,
                transform=ax.get_xaxis_transform(),
                ha="center", va="top", fontsize=11, fontweight="bold")

    ax.axhline(0, color="black", linewidth=0.8, linestyle="--", zorder=1)
    ax.set_ylim(Y_LO - 0.3, Y_HI + 0.5)
    ax.set_xlim(-cluster_w * 0.7, x_max + cluster_w * 0.7)
    ax.set_ylabel("IPC speedup vs LRU baseline  (%)", fontsize=11)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
    ax.yaxis.grid(True, linestyle="--", color="gray", alpha=0.3, linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)

    # ── Config legend ─────────────────────────────────────────────────────────
    legend_patches = [
        mpatches.Patch(color=cfg["color"], label=cfg["legend"])
        for cfg in CONFIGS
    ]
    ax.legend(handles=legend_patches, fontsize=9.5, framealpha=0.9,
              loc="upper right")

    ax.set_title(
        "Bypass-predictor IPC speedup vs. LRU baseline: old vs. current cache hierarchy\n"
        r"(pconf$=6$, bconf$=6$;  dots = individual traces,  $\diamond$ = geomean)",
        fontsize=11, fontweight="bold", pad=8,
    )

    fig.tight_layout()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=200, bbox_inches="tight")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
