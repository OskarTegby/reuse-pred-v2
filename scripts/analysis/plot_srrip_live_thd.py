#!/usr/bin/env python3
"""plot_srrip_live_thd.py — IPC speedup vs mid_thd for srrip_live vs SRRIP.

Three panels stacked vertically (one per suite).  Each panel shows two groups:
  srrip_live at thd=1,2,4,8,16  |  SRRIP (reference)

Within the srrip_live group, bars are shaded light→dark for increasing threshold.
Both groups report geomean IPC speedup over the LRU baseline.

Usage
-----
    python3 scripts/analysis/plot_srrip_live_thd.py             \\
        --thd-dirs dpc3_srrip_live_thd/ google_... qmm_...      \\
        --pol-dirs dpc3_pol/            google_... qmm_...       \\
        --labels   "SPEC (DPC3)"        Google     Qualcomm      \\
        [--out results/plots/srrip_live_thd.png]

STLB policy comparison mode (--stlb-dirs replaces --thd-dirs/--pol-dirs):
    python3 scripts/analysis/plot_srrip_live_thd.py             \\
        --stlb-dirs dpc3_stlb_policy/ google_... qmm_...        \\
        --labels    "SPEC (DPC3)"     Google     Qualcomm        \\
        [--out results/plots/stlb_policy_geomean.png]
"""

import argparse
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.colors as mc
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.transforms as mtrans
import numpy as np
from matplotlib.ticker import FixedFormatter, FixedLocator

sys.path.insert(0, str(Path(__file__).parent))
from champsim_utils import parse_ipc
from spec_weights import benchmark_weighted_geomean_pct

# ── Style constants (match colors.py) ─────────────────────────────────────────
SRRIP_LIVE_COLOR = "#2E8B6A"
SRRIP_COLOR      = "#E8A87C"
LRU_MID_COLOR    = "#A67CB9"
THD_VALUES       = [1, 2, 4, 8, 16]

STLB_POLICIES = ["stlb_srrip", "stlb_srrip_live", "stlb_lru_mid"]
STLB_COLORS   = {
    "stlb_srrip":      SRRIP_COLOR,
    "stlb_srrip_live": SRRIP_LIVE_COLOR,
    "stlb_lru_mid":    LRU_MID_COLOR,
}


def shade(hex_color, i, n_total):
    """Linearly interpolate from 55 % white-mix (i=0) to full colour (i=n-1)."""
    rgb = np.array(mc.to_rgb(hex_color))
    t   = i / max(n_total - 1, 1)
    return tuple(np.ones(3) * (1 - t) * 0.55 + rgb * (1 - (1 - t) * 0.55))


# ── Data loading ───────────────────────────────────────────────────────────────

def _load_ipc(directory: Path) -> dict:
    files = sorted(directory.glob("*/champsim.out"))
    return {f.parent.name: parse_ipc(f) for f in files}


def _geomean(values: dict, baselines: dict) -> "float | None":
    ratios = {}
    for wl, b in baselines.items():
        v = values.get(wl)
        if v is not None and b is not None and b > 0:
            ratios[wl] = v / b
    if not ratios:
        return None
    result = benchmark_weighted_geomean_pct(ratios)
    return None if math.isnan(result) else result


def load_suite(thd_dir: Path, pol_dir: Path) -> dict:
    lru_dir = pol_dir / "lru"
    if not lru_dir.is_dir():
        sys.exit(f"ERROR: no lru/ baseline in {pol_dir}")
    baselines = _load_ipc(lru_dir)
    if not baselines:
        sys.exit(f"ERROR: no workloads in {lru_dir}")

    srrip_dir  = pol_dir / "srrip"
    srrip_gm   = _geomean(_load_ipc(srrip_dir), baselines) if srrip_dir.is_dir() else None

    lru_mid_dir = pol_dir / "lru_mid"
    lru_mid_gm  = _geomean(_load_ipc(lru_mid_dir), baselines) if lru_mid_dir.is_dir() else None

    thd_gm = {}
    # thd=1 lives in the policy sweep dir (addr-keyed) or in the thd dir (PC-keyed)
    sl1_dir = pol_dir / "srrip_live"
    if not sl1_dir.is_dir():
        sl1_dir = thd_dir / "srrip_live_thd1"
    if sl1_dir.is_dir():
        thd_gm[1] = _geomean(_load_ipc(sl1_dir), baselines)
    # thd=2..16 live in the dedicated threshold sweep dir
    for thd in THD_VALUES[1:]:
        subdir = thd_dir / f"srrip_live_thd{thd}"
        thd_gm[thd] = _geomean(_load_ipc(subdir), baselines) if subdir.is_dir() else None

    return {"srrip_gm": srrip_gm, "lru_mid_gm": lru_mid_gm, "thd_gm": thd_gm}


def load_suite_stlb_thd(thd_dir: Path, pol_dir: Path) -> dict:
    """Load STLB threshold sweep data (stlb_srrip_live_thd{N} + references)."""
    lru_dir = pol_dir / "lru"
    if not lru_dir.is_dir():
        sys.exit(f"ERROR: no lru/ baseline in {pol_dir}")
    baselines = _load_ipc(lru_dir)
    if not baselines:
        sys.exit(f"ERROR: no workloads in {lru_dir}")

    stlb_srrip_dir = pol_dir / "stlb_srrip"
    stlb_srrip_gm  = _geomean(_load_ipc(stlb_srrip_dir), baselines) if stlb_srrip_dir.is_dir() else None

    stlb_lru_mid_dir = pol_dir / "stlb_lru_mid"
    stlb_lru_mid_gm  = _geomean(_load_ipc(stlb_lru_mid_dir), baselines) if stlb_lru_mid_dir.is_dir() else None

    thd_gm = {}
    for thd in THD_VALUES:
        subdir = thd_dir / f"stlb_srrip_live_thd{thd}"
        thd_gm[thd] = _geomean(_load_ipc(subdir), baselines) if subdir.is_dir() else None

    return {"stlb_srrip_gm": stlb_srrip_gm, "stlb_lru_mid_gm": stlb_lru_mid_gm, "thd_gm": thd_gm}


def load_suite_stlb(stlb_dir: Path) -> dict:
    lru_dir = stlb_dir / "lru"
    if not lru_dir.is_dir():
        sys.exit(f"ERROR: no lru/ baseline in {stlb_dir}")
    baselines = _load_ipc(lru_dir)
    if not baselines:
        sys.exit(f"ERROR: no workloads in {lru_dir}")
    pol_gm = {}
    for pol in STLB_POLICIES:
        pol_dir = stlb_dir / pol
        pol_gm[pol] = _geomean(_load_ipc(pol_dir), baselines) if pol_dir.is_dir() else None
    return pol_gm


# ── Plot ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--thd-dirs", nargs="+", default=None,
                    help="srrip_live_thd result dirs, one per suite")
    ap.add_argument("--pol-dirs", nargs="+", default=None,
                    help="Policy sweep result dirs, one per suite")
    ap.add_argument("--stlb-thd-dirs", nargs="+", default=None,
                    help="stlb_srrip_live threshold sweep dirs, one per suite")
    ap.add_argument("--stlb-pol-dirs", nargs="+", default=None,
                    help="STLB policy dirs providing lru+stlb_srrip+stlb_lru_mid, one per suite")
    ap.add_argument("--stlb-dirs", nargs="+", default=None,
                    help="STLB policy sweep result dirs, one per suite (single-threshold mode)")
    ap.add_argument("--labels", nargs="+", default=None,
                    help="Suite labels (default: inferred from dir names)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    stlb_thd_mode = args.stlb_thd_dirs is not None
    stlb_mode     = args.stlb_dirs is not None

    # ── STLB threshold sweep mode ──────────────────────────────────────────────
    if stlb_thd_mode:
        if not args.stlb_pol_dirs:
            sys.exit("ERROR: --stlb-thd-dirs requires --stlb-pol-dirs")
        if len(args.stlb_thd_dirs) != len(args.stlb_pol_dirs):
            sys.exit("ERROR: --stlb-thd-dirs and --stlb-pol-dirs must have the same length")
        n_suites = len(args.stlb_thd_dirs)
        labels   = args.labels or [Path(d).name.split("_")[0].upper()
                                    for d in args.stlb_thd_dirs]

        suites = []
        for thd_d, pol_d, label in zip(args.stlb_thd_dirs, args.stlb_pol_dirs, labels):
            print(f"Loading '{label}' ...")
            data = load_suite_stlb_thd(Path(thd_d), Path(pol_d))
            srrip_gm = data["stlb_srrip_gm"]
            print(f"  STLB-SRRIP: {srrip_gm:+.3f}%" if srrip_gm is not None else "  STLB-SRRIP: missing")
            for thd in THD_VALUES:
                v = data["thd_gm"].get(thd)
                print(f"  thd={thd:<3}: {v:+.3f}%" if v is not None else f"  thd={thd}: missing")
            suites.append({"label": label, **data})

        bar_w     = 0.20
        group_gap = 0.20

        fig, axes = plt.subplots(n_suites, 1,
                                 figsize=(9, 3.3 * n_suites), sharey=False)
        if n_suites == 1:
            axes = [axes]

        for ax, suite in zip(axes, suites):
            all_vals   = []
            minor_pos, minor_lbl = [], []
            major_pos, major_lbl = [], []

            g0 = 0.0
            for i, thd in enumerate(THD_VALUES):
                x  = g0 + i * bar_w
                gm = suite["thd_gm"].get(thd)
                minor_pos.append(x)
                minor_lbl.append(str(thd))
                if gm is not None:
                    ax.bar(x, gm, bar_w * 0.88,
                           color=shade(SRRIP_LIVE_COLOR, i, len(THD_VALUES)),
                           edgecolor="black", linewidth=0.4, zorder=3)
                    all_vals.append(gm)

            major_pos.append(g0 + (len(THD_VALUES) - 1) * bar_w / 2)
            major_lbl.append("stlb_srrip_live")

            g1 = len(THD_VALUES) * bar_w + group_gap
            minor_pos.append(g1)
            minor_lbl.append("")
            srrip_gm = suite["stlb_srrip_gm"]
            if srrip_gm is not None:
                ax.bar(g1, srrip_gm, bar_w * 0.88,
                       color=SRRIP_COLOR, edgecolor="black", linewidth=0.4, zorder=3)
                all_vals.append(srrip_gm)
            major_pos.append(g1)
            major_lbl.append("STLB-SRRIP")

            g2 = g1 + bar_w + group_gap / 2
            minor_pos.append(g2)
            minor_lbl.append("")
            lru_mid_gm = suite["stlb_lru_mid_gm"]
            if lru_mid_gm is not None:
                ax.bar(g2, lru_mid_gm, bar_w * 0.88,
                       color=LRU_MID_COLOR, edgecolor="black", linewidth=0.4, zorder=3)
                all_vals.append(lru_mid_gm)
            major_pos.append(g2)
            major_lbl.append("stlb_lru_mid")

            ax.axhline(0, color="black", linewidth=0.8, linestyle="--", zorder=1)
            ax.xaxis.set_minor_locator(FixedLocator(minor_pos))
            ax.xaxis.set_minor_formatter(FixedFormatter(minor_lbl))
            ax.tick_params(axis="x", which="minor", length=3, width=0.6,
                           labelsize=8.5, pad=2)
            ax.xaxis.set_major_locator(FixedLocator([]))
            ax.tick_params(axis="x", which="major", length=0)

            blend = mtrans.blended_transform_factory(ax.transData, ax.transAxes)
            for cx, lbl in zip(major_pos, major_lbl):
                ax.text(cx, -0.18, lbl, transform=blend,
                        ha="center", va="top", fontsize=10)

            ax.set_xlabel("mid-insertion threshold", fontsize=10, labelpad=36)
            ax.set_ylabel("IPC speedup vs LRU (geomean, %)", fontsize=9)
            ax.set_title(suite["label"], fontsize=12, fontweight="bold")
            ax.yaxis.grid(True, linestyle="--", color="gray", alpha=0.60,
                          linewidth=0.9, zorder=0)
            ax.set_axisbelow(True)

            if all_vals:
                positives = [v for v in all_vals if v >= 0]
                max_pos   = max(positives) if positives else 0.0
                lo_full   = min(all_vals)
                hi_full   = max(all_vals)
                if positives and lo_full < 0 and abs(lo_full) > 2 * max(max_pos, 0.5):
                    lo   = -max_pos * 0.6 - 0.1
                    hi   = hi_full
                    span = max(hi - lo, 0.3)
                    y_lo = lo - 0.18 * span
                    y_hi = hi + 0.22 * span
                    ax.set_ylim(y_lo, y_hi)
                    for patch in ax.patches:
                        b   = patch.get_y()
                        top = b + patch.get_height()
                        if b < y_lo:
                            x = patch.get_x() + patch.get_width() / 2
                            ax.text(x, y_lo - 0.02 * span, f"{b:.2f}%",
                                    ha="center", va="top", fontsize=7.5,
                                    fontweight="bold", color="black", clip_on=False)
                else:
                    span = max(hi_full - lo_full, 0.3)
                    ax.set_ylim(lo_full - 0.18 * span, hi_full + 0.22 * span)

            ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f%%"))

        thd_patches = [
            mpatches.Patch(facecolor=shade(SRRIP_LIVE_COLOR, i, len(THD_VALUES)),
                           edgecolor="black", linewidth=0.4, label=f"thd={thd}")
            for i, thd in enumerate(THD_VALUES)
        ]
        srrip_patch   = mpatches.Patch(facecolor=SRRIP_COLOR,   edgecolor="black",
                                       linewidth=0.4, label="STLB-SRRIP")
        lru_mid_patch = mpatches.Patch(facecolor=LRU_MID_COLOR, edgecolor="black",
                                       linewidth=0.4, label="stlb_lru_mid")
        fig.legend(handles=thd_patches + [srrip_patch, lru_mid_patch],
                   loc="lower center", ncol=len(THD_VALUES) + 2, fontsize=10,
                   framealpha=0.9, bbox_to_anchor=(0.5, 0.0))
        fig.suptitle(
            "IPC speedup vs. LRU as a function of stlb_srrip_live threshold",
            fontsize=11, fontweight="bold",
        )
        fig.tight_layout(rect=[0, 0.05, 1, 1])

        out = Path(args.out or "results/plots/stlb_thd.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=180, bbox_inches="tight")
        print(f"Saved: {out}")
        return

    # ── STLB policy comparison mode ────────────────────────────────────────────
    if stlb_mode:
        if args.thd_dirs or args.pol_dirs:
            sys.exit("ERROR: --stlb-dirs is exclusive with --thd-dirs/--pol-dirs")
        n_suites = len(args.stlb_dirs)
        labels   = args.labels or [Path(d).name.split("_")[0].upper()
                                    for d in args.stlb_dirs]

        suites = []
        for stlb_d, label in zip(args.stlb_dirs, labels):
            print(f"Loading '{label}' ...")
            pol_gm = load_suite_stlb(Path(stlb_d))
            for pol in STLB_POLICIES:
                v = pol_gm.get(pol)
                print(f"  {pol:<22}: {v:+.3f}%" if v is not None else f"  {pol}: missing")
            suites.append({"label": label, "pol_gm": pol_gm})

        bar_w = 0.20

        fig, axes = plt.subplots(n_suites, 1,
                                 figsize=(5, 3.3 * n_suites), sharey=False)
        if n_suites == 1:
            axes = [axes]

        for ax, suite in zip(axes, suites):
            all_vals    = []
            positions   = []
            tick_labels = []

            for i, pol in enumerate(STLB_POLICIES):
                x = i * 0.50
                positions.append(x)
                tick_labels.append(pol.replace("stlb_", ""))
                gm = suite["pol_gm"].get(pol)
                if gm is not None:
                    ax.bar(x, gm, bar_w * 0.88,
                           color=STLB_COLORS[pol], edgecolor="black",
                           linewidth=0.4, zorder=3)
                    all_vals.append(gm)

            ax.axhline(0, color="black", linewidth=0.8, linestyle="--", zorder=1)
            ax.xaxis.set_major_locator(FixedLocator(positions))
            ax.xaxis.set_major_formatter(FixedFormatter(tick_labels))
            ax.tick_params(axis="x", which="major", length=3, width=0.6,
                           labelsize=9, pad=3)
            ax.set_ylabel("IPC speedup vs LRU (geomean, %)", fontsize=9)
            ax.set_title(suite["label"], fontsize=12, fontweight="bold")
            ax.yaxis.grid(True, linestyle="--", color="gray", alpha=0.60,
                          linewidth=0.9, zorder=0)
            ax.set_axisbelow(True)

            if all_vals:
                span = max(max(all_vals) - min(all_vals), 0.3)
                ax.set_ylim(min(all_vals) - 0.18 * span, max(all_vals) + 0.22 * span)
            ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f%%"))

        patches = [
            mpatches.Patch(facecolor=STLB_COLORS[pol], edgecolor="black",
                           linewidth=0.4, label=pol.replace("stlb_", "STLB-"))
            for pol in STLB_POLICIES
        ]
        fig.legend(handles=patches, loc="lower center", ncol=len(STLB_POLICIES),
                   fontsize=10, framealpha=0.9, bbox_to_anchor=(0.5, 0.0))
        fig.suptitle("IPC speedup vs. LRU: STLB replacement policy comparison",
                     fontsize=11, fontweight="bold")
        fig.tight_layout(rect=[0, 0.05, 1, 1])

        out = Path(args.out or "results/plots/stlb_policy_geomean.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=180, bbox_inches="tight")
        print(f"Saved: {out}")
        return

    # ── Threshold sweep mode ───────────────────────────────────────────────────
    if not args.thd_dirs or not args.pol_dirs:
        sys.exit("ERROR: --thd-dirs and --pol-dirs are required (or use --stlb-dirs)")
    if len(args.thd_dirs) != len(args.pol_dirs):
        sys.exit("ERROR: --thd-dirs and --pol-dirs must have the same length")

    n_suites = len(args.thd_dirs)
    labels   = args.labels or [Path(d).name.split("_")[0].upper()
                                for d in args.thd_dirs]

    suites = []
    for thd_d, pol_d, label in zip(args.thd_dirs, args.pol_dirs, labels):
        print(f"Loading '{label}' ...")
        data = load_suite(Path(thd_d), Path(pol_d))
        srrip_gm = data["srrip_gm"]
        print(f"  SRRIP  : {srrip_gm:+.3f}%" if srrip_gm is not None else "  SRRIP: missing")
        for thd in THD_VALUES:
            v = data["thd_gm"].get(thd)
            print(f"  thd={thd:<3}: {v:+.3f}%" if v is not None else f"  thd={thd}: missing")
        suites.append({"label": label, **data})

    bar_w     = 0.20
    group_gap = 0.20

    fig, axes = plt.subplots(n_suites, 1,
                             figsize=(9, 3.3 * n_suites), sharey=False)
    if n_suites == 1:
        axes = [axes]

    for ax, suite in zip(axes, suites):
        all_vals   = []
        minor_pos, minor_lbl = [], []
        major_pos, major_lbl = [], []

        # ── Group 1: srrip_live thd sweep ─────────────────────────────────────
        g0 = 0.0
        for i, thd in enumerate(THD_VALUES):
            x  = g0 + i * bar_w
            gm = suite["thd_gm"].get(thd)
            minor_pos.append(x)
            minor_lbl.append(str(thd))
            if gm is not None:
                ax.bar(x, gm, bar_w * 0.88,
                       color=shade(SRRIP_LIVE_COLOR, i, len(THD_VALUES)),
                       edgecolor="black", linewidth=0.4, zorder=3)
                all_vals.append(gm)

        major_pos.append(g0 + (len(THD_VALUES) - 1) * bar_w / 2)
        major_lbl.append("srrip_live")

        # ── Group 2: SRRIP reference ───────────────────────────────────────────
        g1 = len(THD_VALUES) * bar_w + group_gap
        minor_pos.append(g1)
        minor_lbl.append("")
        srrip_gm = suite["srrip_gm"]
        if srrip_gm is not None:
            ax.bar(g1, srrip_gm, bar_w * 0.88,
                   color=SRRIP_COLOR, edgecolor="black", linewidth=0.4, zorder=3)
            all_vals.append(srrip_gm)

        major_pos.append(g1)
        major_lbl.append("SRRIP")

        # ── Group 3: lru_mid reference ─────────────────────────────────────────
        g2 = g1 + bar_w + group_gap / 2
        minor_pos.append(g2)
        minor_lbl.append("")
        lru_mid_gm = suite["lru_mid_gm"]
        if lru_mid_gm is not None:
            ax.bar(g2, lru_mid_gm, bar_w * 0.88,
                   color=LRU_MID_COLOR, edgecolor="black", linewidth=0.4, zorder=3)
            all_vals.append(lru_mid_gm)

        major_pos.append(g2)
        major_lbl.append("lru_mid")

        # ── Axis decoration ────────────────────────────────────────────────────
        ax.axhline(0, color="black", linewidth=0.8, linestyle="--", zorder=1)

        ax.xaxis.set_minor_locator(FixedLocator(minor_pos))
        ax.xaxis.set_minor_formatter(FixedFormatter(minor_lbl))
        ax.tick_params(axis="x", which="minor", length=3, width=0.6,
                       labelsize=8.5, pad=2)
        ax.xaxis.set_major_locator(FixedLocator([]))
        ax.tick_params(axis="x", which="major", length=0)

        blend = mtrans.blended_transform_factory(ax.transData, ax.transAxes)
        for cx, lbl in zip(major_pos, major_lbl):
            ax.text(cx, -0.18, lbl, transform=blend,
                    ha="center", va="top", fontsize=10)

        ax.set_xlabel("mid-insertion threshold", fontsize=10, labelpad=36)
        ax.set_ylabel("IPC speedup vs LRU (geomean, %)", fontsize=9)
        ax.set_title(suite["label"], fontsize=12, fontweight="bold")
        ax.yaxis.grid(True, linestyle="--", color="gray", alpha=0.60,
                      linewidth=0.9, zorder=0)
        ax.set_axisbelow(True)

        if all_vals:
            positives = [v for v in all_vals if v >= 0]
            max_pos   = max(positives) if positives else 0.0
            lo_full   = min(all_vals)
            hi_full   = max(all_vals)
            # Clip outlier: a negative bar that dwarfs all positives
            if positives and lo_full < 0 and abs(lo_full) > 2 * max(max_pos, 0.5):
                lo   = -max_pos * 0.6 - 0.1
                hi   = hi_full
                span = max(hi - lo, 0.3)
                y_lo = lo - 0.18 * span
                y_hi = hi + 0.22 * span
                ax.set_ylim(y_lo, y_hi)
                # Annotate each clipped bar below the axis
                for patch in ax.patches:
                    b   = patch.get_y()        # bottom of rectangle (negative for neg bars)
                    top = b + patch.get_height()
                    if b < y_lo:               # bar bottom below visible range → clipped
                        x = patch.get_x() + patch.get_width() / 2
                        ax.text(x, y_lo - 0.02 * span,
                                f"{b:.2f}%",
                                ha="center", va="top", fontsize=7.5,
                                fontweight="bold", color="black", clip_on=False)
            else:
                span = max(hi_full - lo_full, 0.3)
                ax.set_ylim(lo_full - 0.18 * span, hi_full + 0.22 * span)

        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f%%"))

    # ── Legend ─────────────────────────────────────────────────────────────────
    thd_patches = [
        mpatches.Patch(facecolor=shade(SRRIP_LIVE_COLOR, i, len(THD_VALUES)),
                       edgecolor="black", linewidth=0.4, label=f"thd={thd}")
        for i, thd in enumerate(THD_VALUES)
    ]
    srrip_patch   = mpatches.Patch(facecolor=SRRIP_COLOR,   edgecolor="black",
                                   linewidth=0.4, label="SRRIP")
    lru_mid_patch = mpatches.Patch(facecolor=LRU_MID_COLOR, edgecolor="black",
                                   linewidth=0.4, label="lru_mid")
    fig.legend(handles=thd_patches + [srrip_patch, lru_mid_patch],
               loc="lower center", ncol=len(THD_VALUES) + 2, fontsize=10,
               framealpha=0.9, bbox_to_anchor=(0.5, 0.0))

    fig.suptitle(
        "IPC speedup vs. LRU as a function of srrip_live threshold",
        fontsize=11, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0.05, 1, 1])

    out = Path(args.out or "results/plots/srrip_live_thd.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
