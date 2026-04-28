#!/usr/bin/env python3
"""make_presentation_pdf.py — assemble plots into a presentation PDF.

Sections (in order):
  1. Liveness analysis
  2. Mid-insertion policy (lru_mid)
  3. IPC & MPKI comparison

Each plot gets a full A4-landscape page. A title page is prepended.

Usage
-----
    python3 scripts/analysis/make_presentation_pdf.py \
        [--out results/plots/presentation.pdf]
"""

import argparse
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.backends.backend_pdf import PdfPages

# ── Plot manifest (section title, caption, file path) ────────────────────────
PLOTS_BASE = Path("results/plots")

SECTIONS = [
    {
        "title": "Liveness Analysis",
        "plots": [
            (
                "Liveness bar chart — STLB & LLC (all suites)",
                PLOTS_BASE / "liveness/suite_liveness_bar_LLC_STLB.png",
            ),
            (
                "Per-workload liveness — SPEC (DPC3)",
                PLOTS_BASE / "liveness/spec_liveness_workloads.png",
            ),
            (
                "Per-workload liveness — Google",
                PLOTS_BASE / "liveness/google_liveness_workloads.png",
            ),
            (
                "Per-workload liveness — Qualcomm",
                PLOTS_BASE / "liveness/qmm_liveness_workloads.png",
            ),
            (
                "Per-PC Lorenz curves — LLC deadness concentration",
                PLOTS_BASE / "liveness/liveness_lorenz_LLC.png",
            ),
            (
                "Per-PC Lorenz curves — STLB deadness concentration",
                PLOTS_BASE / "liveness/liveness_lorenz_STLB.png",
            ),
            (
                "STLB–LLC DoA correlation strip chart",
                PLOTS_BASE / "liveness/liveness_corr_strip.png",
            ),
        ],
    },
    {
        "title": "Mid-Insertion Policy (lru_mid)",
        "plots": [
            (
                "IPC speedup vs mid_thd — all scenarios × suites",
                PLOTS_BASE / "mid_lru/mid_thd_combined.png",
            ),
            (
                "Addr vs PC key: summary at optimal mid_thd",
                PLOTS_BASE / "mid_lru/addr_vs_pc_summary.png",
            ),
            (
                "Addr vs PC key: full mid_thd sweep (all suites)",
                PLOTS_BASE / "mid_lru/addr_vs_pc_all.png",
            ),
        ],
    },
    {
        "title": "IPC & MPKI Comparison Across Replacement Policies",
        "plots": [
            (
                "Suite geomean IPC speedup — all policies (incl. DRRIP)",
                PLOTS_BASE / "ipc_mpki/suite_ipc.png",
            ),
            (
                "Suite geomean IPC speedup — DRRIP excluded",
                PLOTS_BASE / "ipc_mpki/suite_ipc_no_drrip.png",
            ),
            (
                "Suite geomean MPKI — all policies (incl. DRRIP)",
                PLOTS_BASE / "ipc_mpki/suite_mpki.png",
            ),
            (
                "Suite geomean MPKI — DRRIP excluded",
                PLOTS_BASE / "ipc_mpki/suite_mpki_no_drrip.png",
            ),
        ],
    },
]


def title_page(pdf: PdfPages, today: str):
    fig = plt.figure(figsize=(11.69, 8.27))  # A4 landscape
    fig.patch.set_facecolor("#1A2A4A")

    fig.text(0.5, 0.62,
             "Cache Liveness Prediction & Mid-Insertion Policy",
             ha="center", va="center",
             fontsize=22, fontweight="bold", color="white",
             wrap=True)
    fig.text(0.5, 0.50,
             "Simulation Results Overview",
             ha="center", va="center",
             fontsize=16, color="#A8C4E0")
    fig.text(0.5, 0.38,
             today,
             ha="center", va="center",
             fontsize=13, color="#7090B0")

    # Horizontal rule
    ax = fig.add_axes([0.15, 0.45, 0.70, 0.002])
    ax.set_facecolor("#4A6A9A")
    ax.axis("off")

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def section_divider(pdf: PdfPages, title: str, section_num: int):
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.patch.set_facecolor("#2A3A5A")

    fig.text(0.5, 0.58,
             f"Section {section_num}",
             ha="center", va="center",
             fontsize=14, color="#8AAAC8")
    fig.text(0.5, 0.48,
             title,
             ha="center", va="center",
             fontsize=24, fontweight="bold", color="white")

    ax = fig.add_axes([0.20, 0.43, 0.60, 0.002])
    ax.set_facecolor("#5A7AAA")
    ax.axis("off")

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def plot_page(pdf: PdfPages, img_path: Path, caption: str):
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.patch.set_facecolor("white")

    # Caption bar at top
    fig.text(0.5, 0.965, caption,
             ha="center", va="top",
             fontsize=10, color="#333333",
             style="italic")

    # Image fills the rest
    ax = fig.add_axes([0.01, 0.02, 0.98, 0.92])
    ax.axis("off")

    try:
        img = mpimg.imread(str(img_path))
        ax.imshow(img, aspect="equal")
    except Exception as e:
        ax.text(0.5, 0.5, f"[Image not found]\n{img_path}",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=12, color="red")
        print(f"  WARNING: {e}")

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="results/plots/presentation.pdf",
                    help="Output PDF path (default: results/plots/presentation.pdf)")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().strftime("%B %d, %Y")

    with PdfPages(str(out_path)) as pdf:
        title_page(pdf, today)

        for si, section in enumerate(SECTIONS, start=1):
            section_divider(pdf, section["title"], si)
            for caption, img_path in section["plots"]:
                print(f"  Adding: {img_path.name}")
                plot_page(pdf, img_path, caption)

    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
