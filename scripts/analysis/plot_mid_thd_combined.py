#!/usr/bin/env python3
"""plot_mid_thd_combined.py — IPC speedup vs mid_thd for all 4 configs × 3 suites.

Three panels (one per suite), each showing 4 lines:
  addr, no-promote  — lru_mid_new runs
  addr, promote     — mid_lru_study runs (pre-fix implicit promotion)
  PC,   no-promote  — lru_mid_new runs
  PC,   promote     — mid_lru_study runs (or explicit --mid-promote run)

Output: results/plots/mid_lru/mid_thd_combined.png
"""

import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# ── Simpoint weights ──────────────────────────────────────────────────────────

_DEFAULT_WEIGHTS_DIR = (
    Path(__file__).parents[2] / ".." / "ChampSim-dev" / "trace-files" / "SPEC2006_weights"
).resolve()


def _load_spec_weights(weights_dir: Path) -> "dict[str, float]":
    """Return {trace_name: weight} from weights_dir/{bm}/{weights.out,simpoints.out}."""
    result: dict = {}
    if not weights_dir.is_dir():
        return result
    for bm_dir in sorted(weights_dir.iterdir()):
        if not bm_dir.is_dir():
            continue
        w_file = bm_dir / "weights.out"
        s_file = bm_dir / "simpoints.out"
        if not (w_file.exists() and s_file.exists()):
            continue
        w_vals = [float(x) for x in w_file.read_text().split()]
        s_ids  = [int(x)   for x in s_file.read_text().split()]
        for sp_id, w in zip(s_ids, w_vals):
            result[f"{bm_dir.name}-{sp_id}B"] = w
    return result


def _benchmark_name(wl: str) -> str:
    """Strip SPEC simpoint suffix: 602.gcc_s-734B -> 602.gcc_s."""
    m = re.match(r'^(.+)-\d+[A-Z]+$', wl)
    return m.group(1) if m else wl


_SPEC_WEIGHTS: "dict[str, float]" = _load_spec_weights(_DEFAULT_WEIGHTS_DIR)

BASE = Path("results")

CONFIGS = [
    ("addr, no-promote", "#5B7FA6", "o", "-"),    # steel blue, solid
    ("addr, promote",    "#1A4A7A", "s", "--"),   # dark blue, dashed
    ("PC, no-promote",   "#E09B6A", "^", "-"),    # light orange, solid
    ("PC, promote",      "#B03000", "D", "--"),   # dark red, dashed
]

SUITES = [
    {
        "label": "SPEC (DPC3)",
        "dirs": [
            BASE / "lru_mid_new/dpc3_mid_addr_20260406_1251",
            BASE / "mid_lru_study/dpc3_mid_addr_20260401_2359",
            BASE / "lru_mid_new/dpc3_mid_pc_20260406_1251",
            BASE / "mid_lru_study/dpc3_mid_pc_20260401_2359",
        ],
    },
    {
        "label": "Google",
        "dirs": [
            BASE / "lru_mid_new/google_mid_addr_20260406_1251",
            BASE / "mid_lru_study/google_mid_addr_20260402_0000",
            BASE / "lru_mid_new/google_mid_pc_20260406_1251",
            BASE / "mid_lru_study/google_mid_pc_promote_20260407_1031",
        ],
    },
    {
        "label": "Qualcomm",
        "dirs": [
            BASE / "lru_mid_new/qmm_mid_addr_20260406_1251",
            BASE / "mid_lru_study/qmm_mid_addr_20260401_1625",
            BASE / "lru_mid_new/qmm_mid_pc_20260406_1251",
            BASE / "mid_lru_study/qmm_mid_pc_20260401_1625",
        ],
    },
]

MAX_N = 5


def parse_ipc(path: Path):
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


def geomean_speedup(sweep_dir: Path, n: int):
    """Return benchmark-weighted geomean IPC speedup (%) at mid_thd=n.

    For SPEC traces (matched by simpoint weights): weighted geometric mean
    within each benchmark (re-normalised for missing simpoints), then
    equal-weight geomean across benchmarks.
    For all other traces: flat equal-weight geomean.
    """
    lru_dir = sweep_dir / "lru"
    baselines: dict = {}
    for f in sorted(lru_dir.glob("*/champsim.out")):
        v = parse_ipc(f)
        if v is not None:
            baselines[f.parent.name] = v
    if not baselines:
        return None

    thd_dir = sweep_dir / f"mid_thd{n}"
    if not thd_dir.is_dir():
        return None

    # Collect per-trace speedup ratios (not %)
    ratios: dict = {}
    for wl, b in baselines.items():
        v = parse_ipc(thd_dir / wl / "champsim.out")
        if v is not None and b > 0:
            ratios[wl] = v / b

    if not ratios:
        return None

    # Group by benchmark name (SPEC only; others each become their own group)
    groups: dict = {}
    for wl, r in ratios.items():
        groups.setdefault(_benchmark_name(wl), []).append(wl)

    per_bench = []
    for wl_list in groups.values():
        if _SPEC_WEIGHTS:
            pairs = [(ratios[wl], _SPEC_WEIGHTS.get(wl)) for wl in wl_list]
            if any(w is not None for _, w in pairs):
                pairs = [(r, w) for r, w in pairs if w is not None and r > 0]
                total_w = sum(w for _, w in pairs)
                if total_w > 0:
                    per_bench.append(
                        float(np.exp(sum((w / total_w) * np.log(r) for r, w in pairs))))
                    continue
        # Fallback: equal-weight geomean within group
        vals = [r for r in [ratios[wl] for wl in wl_list] if r > 0]
        if vals:
            per_bench.append(float(np.exp(np.mean(np.log(vals)))))

    if not per_bench:
        return None
    # Geomean across benchmarks → convert to %
    return (float(np.exp(np.mean(np.log([r for r in per_bench if r > 0])))) - 1) * 100


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/plots/mid_lru/mid_thd_combined.png")
    args = ap.parse_args()

    ns = list(range(1, MAX_N + 1))
    n_cfgs = len(CONFIGS)
    bar_w  = 0.18
    group_w = n_cfgs * bar_w   # no extra gap — N values are the visual separator

    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=False)

    # Build a colour ramp from light to dark for N=1..5 within each config's hue
    def shade(hex_color, n, n_max):
        """Lighten for small n, keep full colour at n_max."""
        import matplotlib.colors as mc
        rgb = np.array(mc.to_rgb(hex_color))
        t = (n - 1) / max(n_max - 1, 1)   # 0 (lightest) → 1 (darkest)
        white = np.ones(3)
        return tuple(white * (1 - t) * 0.55 + rgb * (1 - (1 - t) * 0.55))

    group_gap = 0.35   # extra space between config groups

    from matplotlib.ticker import FixedLocator, FixedFormatter

    for ax, suite in zip(axes, SUITES):
        all_vals = []
        major_pos, major_lbl = [], []   # group centres → config names
        minor_pos, minor_lbl = [], []   # bar centres   → N values

        for ci, ((lbl, color, _marker, _ls), sweep_dir) in enumerate(
                zip(CONFIGS, suite["dirs"])):
            g_start = ci * (MAX_N * bar_w + group_gap)

            for ni, n in enumerate(ns):
                x = g_start + ni * bar_w
                minor_pos.append(x)
                minor_lbl.append(str(n))
                gm = geomean_speedup(sweep_dir, n)
                if gm is None:
                    print(f"  WARNING: no data — {suite['label']} / {lbl} / mid_thd{n}",
                          file=sys.stderr)
                    continue
                c = shade(color, n, MAX_N)
                ax.bar(x, gm, bar_w * 0.88, color=c, edgecolor="black",
                       linewidth=0.4, zorder=3)
                all_vals.append(gm)

            # Group centre label
            major_pos.append(g_start + (MAX_N - 1) * bar_w / 2)
            major_lbl.append(lbl)

        ax.axhline(0, color="black", linewidth=0.8, linestyle="--", zorder=1)

        # Minor ticks: N=1..5 under each bar — no major ticks (they would
        # suppress the middle minor label at the coinciding position)
        ax.xaxis.set_minor_locator(FixedLocator(minor_pos))
        ax.xaxis.set_minor_formatter(FixedFormatter(minor_lbl))
        ax.tick_params(axis="x", which="minor", length=3, width=0.6,
                       labelsize=6.5, pad=2)
        ax.xaxis.set_major_locator(FixedLocator([]))
        ax.tick_params(axis="x", which="major", length=0)

        # Config group labels as text below the N labels, in axes-x / data-y
        import matplotlib.transforms as mtrans
        blend = mtrans.blended_transform_factory(ax.transData, ax.transAxes)
        for cx, lbl in zip(major_pos, major_lbl):
            ax.text(cx, -0.30, lbl, transform=blend,
                    ha="center", va="top", fontsize=8.5)

        ax.set_xlabel("N  (mid-insertion threshold)", fontsize=9, labelpad=10)
        ax.set_ylabel("IPC speedup vs LRU (geomean, %)", fontsize=9)
        ax.set_title(suite["label"], fontsize=12, fontweight="bold")
        ax.yaxis.grid(True, linestyle="--", color="gray", alpha=0.60,
                      linewidth=0.9, zorder=0)
        ax.set_axisbelow(True)

        if all_vals:
            lo, hi = min(all_vals), max(all_vals)
            span = max(hi - lo, 0.3)
            ax.set_ylim(lo - 0.18 * span, hi + 0.22 * span)

        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f%%"))

    # Legend: N=1..5 shading using the first config's colour as reference
    import matplotlib.patches as mpatches
    ref_color = CONFIGS[0][1]
    n_patches = [mpatches.Patch(facecolor=shade(ref_color, n, MAX_N),
                                edgecolor="black", linewidth=0.4,
                                label=f"N={n}") for n in ns]
    fig.legend(handles=n_patches,
               loc="lower center", ncol=MAX_N, fontsize=10,
               framealpha=0.9, bbox_to_anchor=(0.5, -0.04))

    fig.suptitle(
        "IPC speedup vs LRU as a function of mid_thd",
        fontsize=12, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0.12, 1, 1])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
