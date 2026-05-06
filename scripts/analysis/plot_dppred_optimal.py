#!/usr/bin/env python3
"""
plot_dppred_optimal.py — per-benchmark optimal threshold analysis for the bypass predictor.

Supports two modes:
  --mode dppred  : sweep dpPred-only threshold (pthd 0–6, cbPred off)
  --mode cbpred  : sweep full 7×7 dpPred×cbPred threshold grid (pthd×bthd)

For each benchmark/group the script finds the optimal threshold and produces:
  Top panel   – paired bars (optimal vs default threshold) per benchmark,
                sorted by optimal speedup.  The optimal bar is annotated
                with the chosen threshold and coloured by its pthd value.
  Bottom panel – distribution of optimal threshold choices:
                  dppred → 1-D bar chart of optimal pthd values
                  cbpred → 7×7 count heatmap of (pthd, bthd) pairs

Grouping rules
--------------
  dpc3   : simpoints grouped by benchmark with SPEC2006 simpoint weights.
  google : traces grouped by workload-family prefix (arizona_0001 → arizona).
  qmm    : each trace is its own workload.

Usage
-----
  python3 scripts/analysis/plot_dppred_optimal.py \\
      results/dpc3_oldcfg_thd_20260428_2229 \\
      --suite dpc3 --mode cbpred \\
      --out results/plots/dp_cbpred_study/dpc3_cbpred_optimal.png
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from spec_weights import benchmark_weighted_geomean_pct, SPEC_WEIGHTS, benchmark_name

SUITE_LABELS = {
    "dpc3":   "SPEC CPU2006 (DPC3)",
    "google": "Google Warehouse",
    "qmm":    "Qualcomm Mobile",
}

# ── Grouping helpers ──────────────────────────────────────────────────────────

def _group_name(trace: str, suite: str) -> str:
    if suite == "dpc3":
        m = re.match(r"^(.+)-\d+[A-Z]+$", trace)
        return m.group(1) if m else trace
    if suite == "google":
        return re.sub(r"_\d+$", "", trace)
    return trace   # qmm: each trace is its own group


def _short_label(name: str, suite: str) -> str:
    if suite == "dpc3" and "." in name:
        return name.split(".", 1)[1]   # "600.perlbench_s" → "perlbench_s"
    return name


# ── IPC parsing ───────────────────────────────────────────────────────────────

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


# ── Aggregation ───────────────────────────────────────────────────────────────

def _wgeomean(speedups: list, weights: list) -> float:
    """Weighted (or equal-weight) geomean of speedup-percent values."""
    pairs = [(s / 100.0 + 1.0, w) for s, w in zip(speedups, weights)]
    valid_w = [(r, w) for r, w in pairs if r > 0 and w is not None]
    if valid_w:
        total = sum(w for _, w in valid_w)
        if total > 0:
            return (np.exp(
                sum((w / total) * np.log(r) for r, w in valid_w)
            ) - 1.0) * 100.0
    valid = [r for r, _ in pairs if r > 0]
    return (np.exp(np.mean(np.log(valid))) - 1.0) * 100.0 if valid else float("nan")


def _geomean(vals: list) -> float:
    pos = [v / 100.0 + 1.0 for v in vals if not np.isnan(v) and v > -100]
    return (np.exp(np.mean(np.log(pos))) - 1.0) * 100.0 if pos else float("nan")


# ── Config directory name helpers ─────────────────────────────────────────────

def _cfg_dir(key) -> str:
    if isinstance(key, int):
        return f"pthd{key}"
    n, m = key
    return f"pthd{n}_bthd{m}"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results_dir")
    ap.add_argument("--suite", default="dpc3", choices=["dpc3", "google", "qmm"])
    ap.add_argument("--mode", default="cbpred", choices=["dppred", "cbpred", "both"])
    ap.add_argument("--default-n", type=int, default=6, dest="default_n",
                    help="Default pthd value (default: 6)")
    ap.add_argument("--default-b", type=int, default=6, dest="default_b",
                    help="Default bthd value for cbpred mode (default: 6)")
    ap.add_argument("--max-bars", type=int, default=None, dest="max_bars",
                    help="Limit top panel to this many groups (top by optimal speedup). "
                         "Distribution panel always uses all groups.")
    ap.add_argument("--min-speedup", type=float, default=0.0, dest="min_speedup",
                    help="Exclude groups whose |optimal speedup| is below this value (%%). "
                         "Distribution panel always uses all groups.")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    base    = Path(args.results_dir)
    suite   = args.suite
    mode    = args.mode
    def_n   = args.default_n
    def_b   = args.default_b
    use_wts = (suite == "dpc3")
    nr      = list(range(7))  # 0..6

    # "both" uses cbpred configs for filtering/cbpred-bars and dppred configs for dppred-bars
    default_key    = def_n if mode == "dppred" else (def_n, def_b)
    dp_default_key = def_n  # pthd-only default (used in both mode)

    # ── Baselines ─────────────────────────────────────────────────────────────
    bl_dir = base / "baseline"
    if not bl_dir.is_dir():
        sys.exit(f"ERROR: baseline/ not found under {base}")
    traces    = sorted(d.name for d in bl_dir.iterdir() if d.is_dir())
    baselines = {t: _parse_ipc(bl_dir / t / "champsim.out")
                 for t in traces}
    baselines = {t: v for t, v in baselines.items() if v is not None}

    # ── Candidate config keys ─────────────────────────────────────────────────
    if mode == "dppred":
        all_keys = nr
    else:
        all_keys = [(n, m) for n in nr for m in nr]  # cbpred (also used in both)

    # ── Per-trace speedup lookup ──────────────────────────────────────────────
    grid: "dict[str, dict]" = {}
    for t, bi in baselines.items():
        grid[t] = {}
        for key in all_keys + [default_key]:
            v = _parse_ipc(base / _cfg_dir(key) / t / "champsim.out")
            if v is not None and bi > 0:
                grid[t][key] = (v / bi - 1.0) * 100.0

    # In "both" mode also load dpPred-only configs into a separate lookup
    dp_grid: "dict[str, dict]" = {}
    if mode == "both":
        for t, bi in baselines.items():
            dp_grid[t] = {}
            for key in nr + [dp_default_key]:
                v = _parse_ipc(base / _cfg_dir(key) / t / "champsim.out")
                if v is not None and bi > 0:
                    dp_grid[t][key] = (v / bi - 1.0) * 100.0

    # ── Group traces ──────────────────────────────────────────────────────────
    groups: "dict[str, list[str]]" = defaultdict(list)
    for t in grid:
        groups[_group_name(t, suite)].append(t)

    # ── Per-group: optimal key and default speedup ────────────────────────────
    def group_speedup(tlist: list, key) -> float:
        sps, wts = [], []
        for t in tlist:
            if key in grid.get(t, {}):
                sps.append(grid[t][key])
                wts.append(SPEC_WEIGHTS.get(t) if use_wts else None)
        return _wgeomean(sps, wts) if sps else float("nan")

    def dp_group_speedup(tlist: list, key) -> float:
        sps, wts = [], []
        for t in tlist:
            if key in dp_grid.get(t, {}):
                sps.append(dp_grid[t][key])
                wts.append(SPEC_WEIGHTS.get(t) if use_wts else None)
        return _wgeomean(sps, wts) if sps else float("nan")

    results: dict = {}
    for grp, tlist in sorted(groups.items()):
        best_key, best_val = None, float("-inf")
        for key in all_keys:
            v = group_speedup(tlist, key)
            if not np.isnan(v) and v > best_val:
                best_val, best_key = v, key
        if best_key is None:
            continue
        results[grp] = {
            "opt_key": best_key,
            "opt_spd": best_val,
            "def_spd": group_speedup(tlist, default_key),
        }
        if mode == "both":
            best_dp_key, best_dp_val = None, float("-inf")
            for key in nr:
                v = dp_group_speedup(tlist, key)
                if not np.isnan(v) and v > best_dp_val:
                    best_dp_val, best_dp_key = v, key
            results[grp]["dp_opt_key"] = best_dp_key
            results[grp]["dp_opt_spd"] = best_dp_val if best_dp_key is not None else float("nan")
            results[grp]["dp_def_spd"] = dp_group_speedup(tlist, dp_default_key)

    if not results:
        sys.exit("ERROR: no usable data")

    # Snapshot before any filtering — used for geomeans and distribution heatmap
    pre_sorted   = sorted(results, key=lambda g: results[g]["opt_spd"], reverse=True)
    all_opt_spds = [results[g]["opt_spd"] for g in pre_sorted]
    all_def_spds = [results[g]["def_spd"] for g in pre_sorted]
    all_opt_keys = [results[g]["opt_key"] for g in pre_sorted]
    n_all        = len(pre_sorted)
    if mode == "both":
        all_dp_opt_spds = [results[g]["dp_opt_spd"] for g in pre_sorted]
        all_dp_def_spds = [results[g]["dp_def_spd"] for g in pre_sorted]

    if args.min_speedup > 0:
        results = {g: v for g, v in results.items()
                   if abs(v["opt_spd"]) >= args.min_speedup}
    if not results:
        sys.exit("ERROR: no groups remain after --min-speedup filter")

    sorted_grps = sorted(results, key=lambda g: results[g]["opt_spd"], reverse=True)
    n_grps      = len(sorted_grps)

    # Distribution keys: Google → every individual trace; others → all groups pre-filter
    if suite == "google" and mode != "dppred":
        dist_opt_keys = []
        for t in sorted(baselines):
            best_key, best_val = None, float("-inf")
            for key in all_keys:
                v = grid[t].get(key)
                if v is not None and v > best_val:
                    best_val, best_key = v, key
            if best_key is not None:
                dist_opt_keys.append(best_key)
        dist_label = f"all {len(dist_opt_keys)} traces"
    else:
        dist_opt_keys = all_opt_keys
        dist_label    = f"all {n_all}"

    # Geomean over ALL groups (pre-filter snapshot)
    gm_opt = _geomean(all_opt_spds)
    gm_def = _geomean(all_def_spds)

    # Top-panel subset: top --max-bars groups by optimal speedup (already sorted)
    if args.max_bars is not None and n_grps > args.max_bars:
        bar_grps = sorted_grps[: args.max_bars]
        bar_note = f"top {args.max_bars} of {n_all}"
    elif n_grps < n_all:
        bar_grps = sorted_grps
        bar_note = f"|opt| ≥ {args.min_speedup:.2g}%: {n_grps} of {n_all}"
    else:
        bar_grps = sorted_grps
        bar_note = None

    bar_opt_spds = [results[g]["opt_spd"] for g in bar_grps]
    bar_def_spds = [results[g]["def_spd"] for g in bar_grps]
    bar_opt_keys = [results[g]["opt_key"] for g in bar_grps]
    bar_x_labels = [_short_label(g, suite)  for g in bar_grps]
    n_bar        = len(bar_grps)

    # dpPred-only data for "both" mode
    if mode == "both":
        bar_dp_opt_spds = [results[g]["dp_opt_spd"] for g in bar_grps]
        bar_dp_def_spds = [results[g]["dp_def_spd"] for g in bar_grps]
        bar_dp_opt_keys = [results[g]["dp_opt_key"] for g in bar_grps]
        gm_dp_opt = _geomean(all_dp_opt_spds)
        gm_dp_def = _geomean(all_dp_def_spds)

    # ── Colors (pthd 0=green … 6=red) ────────────────────────────────────────
    cmap     = plt.cm.RdYlGn_r
    n_colors = [cmap(k / 6.0) for k in nr]

    def bar_color(key):
        return n_colors[key if isinstance(key, int) else key[0]]

    def_label    = (f"pthd={def_n}" if mode == "dppred" else f"({def_n},{def_b})")
    dp_def_label = f"pthd={def_n}"

    suite_label = SUITE_LABELS.get(suite, base.name)

    # ── Figure geometry ───────────────────────────────────────────────────────
    per_grp = 0.95 if n_bar > 15 else 1.2
    fig_w   = max(11, n_bar * per_grp)

    if mode == "both":
        # Two equal bar-chart panels, no distribution heatmap
        fig, (ax_top, ax_bot) = plt.subplots(
            2, 1, figsize=(fig_w, 9.0),
            gridspec_kw={"height_ratios": [1, 1]},
        )
    else:
        bot_ratio = 1.5 if mode == "cbpred" else 1.6
        fig, (ax_top, ax_bot) = plt.subplots(
            2, 1, figsize=(fig_w, 9.5),
            gridspec_kw={"height_ratios": [3, bot_ratio]},
        )

    # ── Shared bar geometry ────────────────────────────────────────────────────
    bar_w  = 0.38
    gap    = 0.06
    xs     = np.arange(n_bar, dtype=float)
    xs_opt = xs - (bar_w + gap) / 2
    xs_def = xs + (bar_w + gap) / 2

    ann_fs  = 6.0 if (mode in ("cbpred", "both") or n_bar > 20) else 7.5
    lbl_fs  = 8   if n_bar > 15 else 9

    def _draw_bars(ax, opt_spds, opt_keys, def_spds, is_cbpred,
                   dl, gm_o, gm_d, panel_title):
        """Draw a paired-bar panel. Returns the y_span used."""
        y_vals = opt_spds + [d for d in def_spds if not np.isnan(d)]
        y_lo   = min(min(y_vals), 0.0)
        y_hi   = max(max(y_vals), 0.0)
        y_span = max(y_hi - y_lo, 0.5)
        ith    = y_span * 0.15   # inside-threshold
        pad    = y_span * 0.025

        for xi, (spd, key, dspd) in enumerate(zip(opt_spds, opt_keys, def_spds)):
            ax.bar(xs_opt[xi], spd, width=bar_w, color=bar_color(key),
                   edgecolor="black", linewidth=0.5, zorder=2,
                   label="Optimal" if xi == 0 else None)
            if not np.isnan(dspd):
                ax.bar(xs_def[xi], dspd, width=bar_w, color="#b0b0b0",
                       edgecolor="black", linewidth=0.5, zorder=2,
                       label=f"Default {dl}" if xi == 0 else None)

            thd_str = (f"({key[0]},{key[1]})" if is_cbpred else str(key))
            top_y   = spd + pad if spd >= 0 else spd - pad
            top_va  = "bottom"  if spd >= 0 else "top"
            if abs(spd) > ith:
                ax.text(xs_opt[xi], spd / 2.0, thd_str,
                        ha="center", va="center",
                        fontsize=ann_fs, fontweight="bold", color="white",
                        clip_on=True)
                delta = spd - dspd if not np.isnan(dspd) else float("nan")
                if not np.isnan(delta):
                    d_str = f"+{delta:.2f}%" if delta >= 0 else f"{delta:.2f}%"
                    ax.text(xs_opt[xi], top_y, d_str,
                            ha="center", va=top_va,
                            fontsize=ann_fs, color="black", clip_on=True)
            else:
                ax.text(xs_opt[xi], top_y, thd_str,
                        ha="center", va=top_va,
                        fontsize=ann_fs, fontweight="bold", color="black",
                        clip_on=True)

        ax.set_ylim(y_lo - y_span * 0.05, y_hi + y_span * 0.35)
        gm_suffix = f" — all {n_all}" if bar_note else ""
        ax.axhline(gm_o, color="#1a6627", lw=1.5, ls="--", zorder=3,
                   label=f"Geomean optimal ({gm_o:+.2f}%{gm_suffix})")
        ax.axhline(gm_d, color="#555",    lw=1.2, ls=":",  zorder=3,
                   label=f"Geomean default ({gm_d:+.2f}%{gm_suffix})")
        ax.axhline(0, color="black", lw=0.8, zorder=1)
        ax.set_xticks(xs)
        ax.set_xticklabels(bar_x_labels, rotation=45, ha="right", fontsize=lbl_fs)
        ax.set_xlim(-0.65, n_bar - 0.35)
        ax.set_ylabel("IPC speedup vs baseline (%)", fontsize=10)
        title_suffix = f"  [{bar_note} shown by speedup]" if bar_note else ""
        ax.set_title(f"{panel_title} — {suite_label}{title_suffix}",
                     fontsize=10, fontweight="bold")
        ax.legend(fontsize=8.5, loc="upper right", framealpha=0.9)
        ax.yaxis.grid(True, ls="--", color="gray", alpha=0.3, zorder=0)
        ax.set_axisbelow(True)
        return y_span

    # ── Top panel ─────────────────────────────────────────────────────────────
    if mode == "both":
        _draw_bars(ax_top,
                   bar_dp_opt_spds, bar_dp_opt_keys, bar_dp_def_spds,
                   is_cbpred=False, dl=dp_def_label,
                   gm_o=gm_dp_opt, gm_d=gm_dp_def,
                   panel_title="dpPred-only — optimal vs default threshold")
    else:
        _draw_bars(ax_top,
                   bar_opt_spds, bar_opt_keys, bar_def_spds,
                   is_cbpred=(mode == "cbpred"), dl=def_label,
                   gm_o=gm_opt, gm_d=gm_def,
                   panel_title=("dpPred-only" if mode == "dppred"
                                else "dpPred+cbPred") +
                               " — optimal vs default threshold")

    # ── Bottom panel ──────────────────────────────────────────────────────────
    if mode == "both":
        # cbPred bars on the bottom panel
        _draw_bars(ax_bot,
                   bar_opt_spds, bar_opt_keys, bar_def_spds,
                   is_cbpred=True, dl=def_label,
                   gm_o=gm_opt, gm_d=gm_def,
                   panel_title="dpPred+cbPred — optimal vs default threshold")

    elif mode == "dppred":
        # Distribution bar of optimal pthd values
        n_dist = [sum(1 for k in all_opt_keys if k == i) for i in nr]
        for k, cnt in enumerate(n_dist):
            ec = "#111" if k == def_n else "black"
            lw = 1.8    if k == def_n else 0.6
            ax_bot.bar(k, cnt, color=n_colors[k], edgecolor=ec,
                       linewidth=lw, zorder=2)
            if cnt > 0:
                ax_bot.text(k, cnt + 0.08, str(cnt), ha="center",
                            va="bottom", fontsize=9, fontweight="bold")
        ax_bot.set_xticks(nr)
        ax_bot.set_xticklabels([str(k) for k in nr], fontsize=9)
        ax_bot.set_xlabel("dpPred threshold (pthd)", fontsize=10)
        ax_bot.set_ylabel("No. of benchmarks", fontsize=10)
        ax_bot.set_title("Distribution of optimal pthd", fontsize=10)
        ax_bot.set_xlim(-0.6, 6.6)
        ax_bot.set_ylim(bottom=0)
        ax_bot.yaxis.grid(True, ls="--", color="gray", alpha=0.3, zorder=0)
        ax_bot.set_axisbelow(True)

    else:  # cbpred
        # 7×7 count heatmap — rows=pthd, cols=bthd
        counts = np.zeros((7, 7), dtype=int)
        for key in dist_opt_keys:
            counts[key[0], key[1]] += 1
        vmax = max(counts.max(), 1)
        im   = ax_bot.imshow(counts, cmap="Blues", vmin=0, vmax=vmax,
                             origin="lower", aspect="equal")
        plt.colorbar(im, ax=ax_bot, label=f"Count ({dist_label})",
                     fraction=0.03, pad=0.02)
        for n in nr:
            for m in nr:
                c = counts[n, m]
                tc = "white" if c > vmax * 0.55 else "black"
                ax_bot.text(m, n, str(c), ha="center", va="center",
                            fontsize=10, color=tc,
                            fontweight="bold" if c > 0 else "normal")
        ax_bot.add_patch(plt.Rectangle(
            (def_b - 0.5, def_n - 0.5), 1, 1,
            fill=False, edgecolor="#d62728", lw=2.5, zorder=3,
        ))
        ax_bot.set_xticks(nr)
        ax_bot.set_xticklabels([str(m) for m in nr], fontsize=9)
        ax_bot.set_yticks(nr)
        ax_bot.set_yticklabels([str(n) for n in nr], fontsize=9)
        ax_bot.set_xlabel("cbPred threshold (bthd)", fontsize=10)
        ax_bot.set_ylabel("dpPred threshold (pthd)", fontsize=10)
        ax_bot.set_title(
            f"Distribution of optimal (pthd, bthd) pairs  "
            f"[{dist_label} · red border = default (6,6)]",
            fontsize=10,
        )

    plt.tight_layout()

    out = (Path(args.out) if args.out
           else Path(f"threshold_optimal_{mode}_{base.name}.png"))
    out.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
