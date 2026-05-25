#!/usr/bin/env python3
"""plot_liveness_bar.py — per-workload liveness bar chart (Figures 2 & 4 style).

Reproduces the style of Figures 2 and 4 in Mazumdar et al. (HPCA 2021):
one stacked bar per workload, showing the fraction of evictions that are
DoA / mostly-dead / mostly-alive.  Two panels: one for the STLB, one for the LLC.

Bars are sorted by descending (DoA + mostly-dead) fraction so the worst
workloads appear on the left, matching the paper's presentation.

Usage
-----
    # All *.out files in a directory (one bar per file)
    python3 scripts/plot_liveness_bar.py results/maz_<date>/baseline/ \\
        --out maz_liveness_bar.png

    # Multiple suites side-by-side (one panel per suite, or interleaved)
    python3 scripts/plot_liveness_bar.py \\
        results/maz_<date>/baseline/ results/qmm_<date>/baseline/ \\
        --labels maz qmm --out liveness_bar.png
"""

import argparse
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

from liveness_utils import load_suite
from spec_weights import aggregate_spec_liveness, benchmark_weighted_geomean_frac

MAX_WORKLOADS = 25   # maximum per-workload bars shown in each panel


def _short_name(wl: str, suite: str = "") -> str:
    """Return a concise display name for a workload filename."""
    s = suite.lower()
    # SPEC/DPC3 (post-aggregation): "607.cactuBSSN_s" -> "cactuBSSN"
    if re.match(r'^\d{3}\.', wl):
        return re.sub(r'^\d+\.(.+?)(?:_[sr])?$', r'\1', wl)
    # Ligra: "ligra_BellmanFord.com-lj.ungraph.gcc_6..." -> "BellmanFord"
    if wl.startswith("ligra_"):
        return wl[len("ligra_"):].split(".")[0]
    # GMS: "gms.k_clique_count_set_based.soc-pokec-relationships.slice-4.champsimtrace" -> "kclique_cnt.4"
    if wl.startswith("gms."):
        bench = wl[len("gms."):].split(".")[0]
        _gms = {
            "k_clique_count_set_based":            "kclique_cnt",
            "k_clique_count":                      "kclique",
            "k_clique_list_danisch_edge_parallel":  "kclique_ep",
            "k_clique_list_danisch_node_parallel":  "kclique_np",
            "k_clique_list_danisch_serial":         "kclique_ser",
            "k_clique_star_list":                  "kclique_star",
            "maximal_clique_enum_bron_kerbosch":    "max_clique",
            "triangle_count":                      "tri_cnt",
            "betweenness_centrality":              "bc",
            "connected_components":                "cc",
            "label_propagation":                   "lp",
            "pagerank":                            "pagerank",
            "bfs":                                 "bfs",
        }
        short = _gms.get(bench, bench[:12])
        m = re.search(r'slice-(\d+)', wl)
        return f"{short}.{m.group(1)}" if m else short
    # ML: multiple naming conventions
    if "ml" in s or "ai" in s:
        # "clip_trace_1" / "whisper_trace_1" / "rwkv_trace_2"
        m = re.match(r'^([a-zA-Z]+)_trace_(\d+)$', wl)
        if m:
            return f"{m.group(1)}.{m.group(2)}"
        parts = wl.split(".")
        app = parts[0]
        inst = parts[-1] if parts[-1].isdigit() else ""
        # stable-diffusion: "stable-diffusion.cpp-sd-v1-4.ckpt.1" -> "sd.v1.4.1"
        if app == "stable-diffusion":
            vm = re.search(r'[vs](\d+[-_]\d+)', parts[1]) if len(parts) > 1 else None
            if vm:
                ver = re.sub(r'[-_]', '.', vm.group(1))
                return f"sd.v{ver}.{inst}" if inst else f"sd.v{ver}"
            return f"sd.{inst}" if inst else "sd"
        # vit: "vit.cpp-base-ggml..." -> "vit-base.1"
        if app == "vit" and len(parts) > 1:
            vm = re.search(r'-(base|large|small|tiny)', parts[1])
            if vm:
                return f"vit-{vm.group(1)}.{inst}" if inst else f"vit-{vm.group(1)}"
        # llama2: "llama2.c-stories110M.1" -> "llama2-110M.1"
        if "llama" in app and len(parts) > 1:
            sm = re.search(r'(\d+[MBKGkmb])', parts[1], re.IGNORECASE)
            if sm:
                return f"{app}-{sm.group(1).upper()}.{inst}" if inst else f"{app}-{sm.group(1).upper()}"
        return f"{app[:12]}.{inst}" if inst else app[:12]
    # Google: "arizona_0000" -> "arizona.0", "charlie_0003" -> "charlie.3", "sierra.a.3_0001" -> "sierra.a.3.1"
    if "google" in s:
        m = re.match(r'^(.+)_(\d{4})$', wl)
        if m:
            return f"{m.group(1)}.{int(m.group(2))}"
        return wl
    # GAP: names already short ("bc-0", "bfs-10"); QMM: "srv_222" — return as-is
    return wl


def _diverse_select(items, feature_fn, k):
    """Greedy farthest-point sampling in normalised feature space.  Returns indices."""
    n = len(items)
    if n <= k:
        return list(range(n))
    vecs = np.array([feature_fn(item) for item in items], dtype=float)
    lo, hi = vecs.min(axis=0), vecs.max(axis=0)
    span = np.where(hi > lo, hi - lo, 1.0)
    v = (vecs - lo) / span
    centroid = v.mean(axis=0)
    selected = [int(np.argmin(np.linalg.norm(v - centroid, axis=1)))]
    min_d = np.full(n, np.inf)
    while len(selected) < k:
        d = np.linalg.norm(v - v[selected[-1]], axis=1)
        min_d = np.minimum(min_d, d)
        min_d[selected] = -1.0
        selected.append(int(np.argmax(min_d)))
    return selected






# Soft, muted palettes — slight hue variation per suite while keeping the same feel
# Each entry: (DoA, mostly-dead, mostly-alive)
SUITE_PALETTES = {
    "spec":     ("#5B7FA6", "#E8A87C", "#7CB9A8"),  # steel-blue / peach / teal  (canonical)
    "google":   ("#5B8CB3", "#EBC070", "#86BBA0"),  # sky-blue   / gold  / olive-teal
    "qualcomm": ("#6672A6", "#D4956C", "#7ABFC8"),  # slate-blue / rust  / cyan-teal
    "default":  ("#5B7FA6", "#E8A87C", "#7CB9A8"),
}

# Fallback module-level colors (overridden per-suite in main)
COLOR_DOA, COLOR_MD, COLOR_MA = SUITE_PALETTES["default"]


def _contrast(hex_color: str) -> str:
    """Return 'white' or 'black' for best contrast against the given hex background."""
    r, g, b = (int(hex_color[i:i+2], 16) / 255 for i in (1, 3, 5))
    return "white" if (0.299 * r + 0.587 * g + 0.114 * b) < 0.55 else "black"

# ── Plot ──────────────────────────────────────────────────────────────────────

def plot_cache_panel(ax, rows, cache_name, sort_by_dead=True, colors=None, geomean_rows=None):
    """Draw one panel (one cache) onto ax.  rows = [(label, data_dict), ...].

    SPEC simpoints in rows must already be aggregated into parent benchmarks
    before calling this function (see aggregate_spec_liveness).
    colors: (color_doa, color_md, color_ma) tuple; defaults to module-level palette.
    geomean_rows: if provided, compute the geomean over this set instead of rows
                  (use the full uncapped suite data when --max-per-suite is active).
    """
    c_doa, c_md, c_ma = colors if colors else (COLOR_DOA, COLOR_MD, COLOR_MA)
    # Filter to workloads that have data for this cache
    valid = [(lbl, d[cache_name]) for lbl, d in rows if cache_name in d]
    if not valid:
        ax.set_visible(False)
        return

    # Select diverse display subset if needed; full set used for geomean below
    all_valid = valid
    if len(valid) > MAX_WORKLOADS:
        def _fvec(r):
            tot = max(r[1]["total"], 1)
            return [r[1]["doa"] / tot, r[1]["mostly_dead"] / tot]
        sel = _diverse_select(valid, _fvec, MAX_WORKLOADS)
        valid = [valid[i] for i in sel]

    # Use the full uncapped data for geomean when provided
    if geomean_rows is not None:
        all_valid = [(lbl, d[cache_name]) for lbl, d in geomean_rows if cache_name in d]

    # Sort selected subset by dead fraction for left-to-right readability
    if sort_by_dead:
        valid.sort(key=lambda r: (r[1]["doa"] + r[1]["mostly_dead"]) /
                                  max(r[1]["total"], 1),
                   reverse=True)

    labels_all = [lbl for lbl, _ in all_valid]
    labels = [lbl for lbl, _ in valid]
    totals = np.array([d["total"] for _, d in valid], dtype=float)
    doa_pct = np.array([d["doa"] for _, d in valid]) / np.where(totals > 0, totals, 1) * 100
    md_pct  = np.array([d["mostly_dead"]  for _, d in valid]) / np.where(totals > 0, totals, 1) * 100
    ma_pct  = np.array([d["mostly_alive"] for _, d in valid]) / np.where(totals > 0, totals, 1) * 100

    # Geomean computed over ALL workloads (not just the displayed subset)
    totals_all = np.array([d["total"] for _, d in all_valid], dtype=float)
    doa_all = np.array([d["doa"] for _, d in all_valid]) / np.where(totals_all > 0, totals_all, 1) * 100
    md_all  = np.array([d["mostly_dead"]  for _, d in all_valid]) / np.where(totals_all > 0, totals_all, 1) * 100
    ma_all  = np.array([d["mostly_alive"] for _, d in all_valid]) / np.where(totals_all > 0, totals_all, 1) * 100

    # ── Geomean bar: benchmark-weighted geomean of each fraction, renormalised ──
    gm_ma  = benchmark_weighted_geomean_frac(labels_all, ma_all)
    gm_md  = benchmark_weighted_geomean_frac(labels_all, md_all)
    gm_doa = benchmark_weighted_geomean_frac(labels_all, doa_all)
    gm_sum = gm_ma + gm_md + gm_doa
    gm_ma  = gm_ma  / gm_sum * 100 if gm_sum > 0 else 0.0
    gm_md  = gm_md  / gm_sum * 100 if gm_sum > 0 else 0.0
    gm_doa = gm_doa / gm_sum * 100 if gm_sum > 0 else 0.0

    # Append geomean as a separate bar, separated by a gap
    n = len(labels)
    gap = 1.2          # extra space between workloads and geomean bar
    x_wl = np.arange(n)
    x_gm = n + gap     # geomean bar position

    w = 0.6

    def draw_bars(xs, ma, md, doa, width, legend=True):
        kw = dict(edgecolor="black", linewidth=0.5)
        ax.bar(xs, doa, width, label="DoA"         if legend else "_", color=c_doa, **kw)
        ax.bar(xs, md,  width, bottom=doa,          label="Mostly-dead" if legend else "_", color=c_md,  **kw)
        ax.bar(xs, ma,  width, bottom=doa + md,     label="Mostly-alive" if legend else "_", color=c_ma,  **kw)

    draw_bars(x_wl, ma_pct, md_pct, doa_pct, w, legend=True)
    draw_bars(x_gm, gm_ma,  gm_md,  gm_doa,  w * 1.1, legend=False)

    # Value labels inside individual workload bars
    for i, (ma, md, doa) in enumerate(zip(ma_pct, md_pct, doa_pct)):
        if doa > 5: ax.text(i, doa / 2,           f"{doa:.0f}%", ha="center", va="center", fontsize=8, color=_contrast(c_doa), fontweight="bold")
        if md  > 5: ax.text(i, doa + md / 2,      f"{md:.0f}%",  ha="center", va="center", fontsize=8, color=_contrast(c_md),  fontweight="bold")
        if ma  > 5: ax.text(i, doa + md + ma / 2, f"{ma:.0f}%",  ha="center", va="center", fontsize=8, color=_contrast(c_ma),  fontweight="bold")

    # Value labels inside geomean bar (larger font)
    for val, base, col in [
        (gm_doa, 0,               c_doa),
        (gm_md,  gm_doa,          c_md),
        (gm_ma,  gm_doa + gm_md,  c_ma),
    ]:
        if val > 4:
            ax.text(x_gm, base + val / 2, f"{val:.0f}%",
                    ha="center", va="center", fontsize=10, color=_contrast(col), fontweight="bold")

    # Vertical separator line between workloads and geomean
    ax.axvline(n + gap / 2, color="gray", linewidth=0.8, linestyle=":", zorder=1)

    display = {"cpu0_STLB": "STLB", "LLC": "LLC"}
    all_x      = list(x_wl) + [x_gm]
    all_labels = labels + ["Geomean"]
    ax.set_xticks(all_x)
    ax.set_xticklabels(all_labels, rotation=35, ha="right", fontsize=8)
    # Make the Geomean label bold
    for tick, lbl in zip(ax.get_xticklabels(), all_labels):
        if lbl == "Geomean":
            tick.set_fontweight("bold")
    ax.set_ylabel("Evictions (%)", fontsize=10)
    ax.set_xlim(-0.7, x_gm + 0.7)
    ax.set_ylim(0, 105)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax.set_title(f"{display.get(cache_name, cache_name)} evictions", fontsize=13)
    ax.legend(loc="upper left", fontsize=9, framealpha=0.85)
    ax.grid(axis="y", alpha=0.3, linewidth=0.5)


# ── Main ──────────────────────────────────────────────────────────────────────

def suite_geomean_row(label: str, rows: list, cache: str):
    """Collapse all workloads in a suite into a single benchmark-weighted geomean row."""
    wl_names, doa_rates, md_rates, ma_rates = [], [], [], []
    for wl, data in rows:
        d = data.get(cache, {})
        tot = d.get("total", 0) or 1
        wl_names.append(wl)
        doa_rates.append(d.get("doa", 0) / tot * 100)
        md_rates.append(d.get("mostly_dead", 0) / tot * 100)
        ma_rates.append(d.get("mostly_alive", 0) / tot * 100)
    if not doa_rates:
        return None
    gm_doa = benchmark_weighted_geomean_frac(wl_names, doa_rates)
    gm_md  = benchmark_weighted_geomean_frac(wl_names, md_rates)
    gm_ma  = benchmark_weighted_geomean_frac(wl_names, ma_rates)
    gm_sum = gm_doa + gm_md + gm_ma
    # Synthetic data dict that plot_cache_panel can consume
    n = len(doa_rates)
    return (label, {cache: {
        "total":        n,
        "doa":          int(gm_doa / gm_sum * n) if gm_sum > 0 else 0,
        "mostly_dead":  int(gm_md  / gm_sum * n) if gm_sum > 0 else 0,
        "mostly_alive": int(gm_ma  / gm_sum * n) if gm_sum > 0 else 0,
    }})


_SUITE_DISPLAY = {
    "spec":   "SPEC (DPC3)",
    "dpc3":   "SPEC (DPC3)",
    "google": "Google",
    "qmm":    "Qualcomm (QMM)",
    "gap":    "GAP",
    "gms":    "GMS",
    "ligra":  "Ligra",
    "ml":     "AI/ML",
}

def _dead_pct(data, cache):
    if cache not in data:
        return None
    d = data[cache]
    tot = d.get("total", 0)
    if tot == 0:
        return None
    return (d.get("doa", 0) + d.get("mostly_dead", 0)) / tot * 100


def _latex(s: str) -> str:
    """Escape LaTeX special characters in plain text."""
    return s.replace("_", r"\_").replace("%", r"\%").replace("&", r"\&")


def _print_latex_table(suites, orig_suites):
    """Print a LaTeX table of selected workloads with STLB/LLC dead fractions."""
    lines = []
    lines.append(r"\begin{table}[tbp]")
    lines.append(r"\caption{Selected workloads per suite (top-4 by combined LLC+STLB dead fraction)."
                 r"  Dead\% = DoA + mostly-dead evictions at LLC or STLB eviction;")
    lines.append(r"           dashes indicate fewer than one eviction recorded.}")
    lines.append(r"\label{tab:selected_workloads}")
    lines.append(r"\centering\small")
    lines.append(r"\begin{tabular}{llrr}")
    lines.append(r"\toprule")
    lines.append(r"Suite & Workload & LLC dead\% & STLB dead\% \\")
    lines.append(r"\midrule")
    for lbl, rows in suites:
        suite_name = _SUITE_DISPLAY.get(lbl.lower(), lbl)
        for wl, data in rows:
            short = _latex(_short_name(wl, lbl))
            llc_dead  = _dead_pct(data, "LLC")
            stlb_dead = _dead_pct(data, "cpu0_STLB")
            llc_str  = f"{llc_dead:.0f}" if llc_dead is not None else "---"
            stlb_str = f"{stlb_dead:.0f}" if stlb_dead is not None else "---"
            lines.append(rf"  {suite_name} & \texttt{{{short}}} & {llc_str} & {stlb_str} \\")
        lines.append(r"\addlinespace")
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    lines.append(r"\end{table}")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("results_dirs", nargs="+",
                    help="Directories containing *.out files (one per suite)")
    ap.add_argument("--labels", nargs="*",
                    help="Suite labels (default: directory names)")
    ap.add_argument("--out",    default="liveness_bar.png",
                    help="Output PNG (default: liveness_bar.png)")
    ap.add_argument("--no-sort", action="store_true",
                    help="Keep workloads in filename order instead of sorting by dead fraction")
    ap.add_argument("--summary", action="store_true",
                    help="Show one geomean bar per suite (policy comparison) instead of one bar per workload")
    ap.add_argument("--max-per-suite", type=int, default=None, metavar="N",
                    help="Keep at most N workloads per suite (top N by dead fraction)")
    ap.add_argument("--print-table", action="store_true",
                    help="Print a LaTeX table of selected workloads (with dead fractions) to stdout")
    args = ap.parse_args()

    dirs = [Path(d) for d in args.results_dirs]
    for d in dirs:
        if not d.is_dir():
            sys.exit(f"ERROR: {d} is not a directory")

    labels = args.labels or [d.parent.name if d.name == "baseline" else d.name
                              for d in dirs]
    if len(labels) != len(dirs):
        sys.exit("ERROR: --labels count must match number of directories")

    # Load all suites; aggregate SPEC simpoints into parent benchmarks
    suites = []
    for lbl, d in zip(labels, dirs):
        print(f"Loading '{lbl}' from {d} ...", file=sys.stderr)
        suite_rows = load_suite(d)
        suite_rows = aggregate_spec_liveness(suite_rows)
        suites.append((lbl, suite_rows))
        print(f"  {len(suite_rows)} workloads (after simpoint aggregation)", file=sys.stderr)

    if not suites:
        sys.exit("ERROR: no data loaded")

    orig_suites = list(suites)  # full data, used for accurate geomean

    # Cap each suite to the top N workloads by dead fraction before combining
    if args.max_per_suite is not None:
        capped = []
        for lbl, rows in suites:
            if len(rows) > args.max_per_suite:
                def _dead_key(r):
                    for ck in ["LLC", "cpu0_STLB"]:
                        d = r[1].get(ck, {})
                        tot = max(d.get("total", 0), 1)
                        if tot > 1:
                            return (d.get("doa", 0) + d.get("mostly_dead", 0)) / tot
                    return 0.0
                rows = sorted(rows, key=_dead_key, reverse=True)[:args.max_per_suite]
                print(f"  '{lbl}': capped to {args.max_per_suite} workloads by dead fraction", file=sys.stderr)
            capped.append((lbl, rows))
        suites = capped

    # Print workload selection table if requested
    if args.print_table:
        _print_latex_table(suites, orig_suites)
        return

    suite_desc = " + ".join(labels)
    out_path_obj = Path(args.out)
    out_stem = out_path_obj.stem
    out_suffix = out_path_obj.suffix or ".png"
    out_dir = out_path_obj.parent

    cache_display = {"cpu0_STLB": "STLB", "LLC": "LLC"}
    for cache in ["cpu0_STLB", "LLC"]:
        if args.summary:
            # One geomean bar per suite — policy comparison view
            all_rows = [r for lbl, rows in suites
                        for r in [suite_geomean_row(lbl, rows, cache)] if r]
            geomean_rows = None
            fig_w = max(6, len(all_rows) * 1.0 + 2)
        else:
            # One bar per workload across all suites (display-capped set)
            all_rows = []
            for lbl, rows in suites:
                tagged = [(f"{lbl}/{_short_name(wl, lbl)}" if len(suites) > 1 else _short_name(wl, lbl), data)
                          for wl, data in rows]
                all_rows.extend(tagged)
            # Full uncapped set for geomean (avoids bias from top-N dead selection)
            geomean_rows = []
            for lbl, rows in orig_suites:
                tagged = [(f"{lbl}/{_short_name(wl, lbl)}" if len(orig_suites) > 1 else _short_name(wl, lbl), data)
                          for wl, data in rows]
                geomean_rows.extend(tagged)
            # Figure width based on displayed workloads (capped at MAX_WORKLOADS)
            n_display = min(len(all_rows), MAX_WORKLOADS)
            fig_w = max(8, n_display * 0.75 + 3)

        if not all_rows:
            print(f"  WARNING: no data for {cache} — skipped", file=sys.stderr)
            continue

        # Pick palette from the first suite label (or default if multiple suites)
        if len(suites) == 1:
            lbl_lower = labels[0].lower()
            if "spec" in lbl_lower:
                palette_key = "spec"
            elif "google" in lbl_lower:
                palette_key = "google"
            elif "qual" in lbl_lower or "qmm" in lbl_lower:
                palette_key = "qualcomm"
            else:
                palette_key = "default"
        else:
            palette_key = "default"
        suite_colors = SUITE_PALETTES[palette_key]

        fig, ax = plt.subplots(figsize=(fig_w, 6))
        plot_cache_panel(ax, all_rows, cache,
                         sort_by_dead=not args.no_sort and not args.summary,
                         colors=suite_colors,
                         geomean_rows=geomean_rows)
        n_total = len(all_rows)
        if args.summary:
            title = f"{cache_display[cache]} liveness at eviction"
        elif args.max_per_suite is not None:
            title = (f"{cache_display[cache]} liveness at eviction — {suite_desc}\n"
                     f"(top-{args.max_per_suite} per suite by dead fraction; geomean over all)")
        else:
            title = (f"{cache_display[cache]} liveness at eviction — {suite_desc}\n"
                     f"({min(n_total, MAX_WORKLOADS)} most diverse of {n_total}; geomean over all)")
        fig.suptitle(title, fontsize=14)
        fig.tight_layout()
        out_path = str(out_dir / f"{out_stem}_{cache_display[cache]}{out_suffix}")
        fig.savefig(out_path, dpi=200, bbox_inches="tight")
        plt.close(fig)
        print(f"Saved: {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
