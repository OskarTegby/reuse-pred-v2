#!/usr/bin/env python3
"""Academic-style (Beamer-like) PDF presentation.

Design rules
------------
- White background, thin navy title bar, no decorative chrome.
- Figure and observations on the same slide wherever possible.
- Observations use explicit panel references ("left panel", "upper row", etc.).
- Dense text, numbered/bulleted lists, tight spacing.
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# ── Paths ─────────────────────────────────────────────────────────────────────
PLOTS = Path("results/plots")
LIV   = PLOTS / "liveness"
MID   = PLOTS / "mid_lru"
OUT   = PLOTS / "presentation.pdf"

# ── Typography ────────────────────────────────────────────────────────────────
NAVY  = "#1A2B4A"
WHITE = "#FFFFFF"
BLUE  = "#2C7BB6"
BLACK = "#0D0D0D"
DGRAY = "#444444"
RED   = "#B22222"

W, H  = 16, 9
BAR_H = 0.085        # title bar height (fraction of figure)
FS_T  = 19           # title font size
FS_H  = 14.5         # in-slide sub-header
FS_B  = 13.5         # body text
LS    = 1.38         # line spacing


# ── Shared primitives ─────────────────────────────────────────────────────────

def save(pdf, fig):
    pdf.savefig(fig)
    plt.close(fig)


def _title_bar(fig, title):
    bar = fig.add_axes([0, 1 - BAR_H, 1, BAR_H])
    bar.set_facecolor(NAVY); bar.axis("off")
    bar.text(0.013, 0.5, title, va="center", fontsize=FS_T,
             fontweight="bold", color=WHITE, transform=bar.transAxes)


def _img(fig, rect, path):
    ax = fig.add_axes(rect)
    ax.axis("off")
    ax.imshow(plt.imread(str(path)), aspect="auto")


def _text_block(fig, rect, lines):
    """Render a list of strings top-to-bottom.

    Prefixes:
      "## text"  → bold dark-navy sub-header (no bullet)
      "⚠ text"   → red text
      ""          → small gap
      anything   → body text (rendered as-is; include "1. ", "·  " etc.)
    """
    ax = fig.add_axes(rect)
    ax.set_facecolor(WHITE)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)

    y = 0.99
    for line in lines:
        if line == "":
            y -= 0.030
            continue
        if line.startswith("## "):
            text = line[3:]
            ax.text(0, y, text, va="top", fontsize=FS_H, fontweight="bold",
                    color=NAVY, transform=ax.transAxes)
            n    = text.count("\n") + 1
            step = 0.072 + 0.056 * (n - 1)
        elif line.startswith("⚠"):
            n = line.count("\n") + 1
            ax.text(0, y, line, va="top", fontsize=FS_B, color=RED,
                    fontweight="bold", transform=ax.transAxes, linespacing=LS)
            step = 0.055 + 0.050 * (n - 1)
        else:
            n = line.count("\n") + 1
            ax.text(0, y, line, va="top", fontsize=FS_B, color=BLACK,
                    transform=ax.transAxes, linespacing=LS)
            step = 0.056 + 0.050 * (n - 1)
        y -= step


# ── Layout builders ───────────────────────────────────────────────────────────

CONTENT_BOT = 0.03
CONTENT_TOP = 1 - BAR_H - 0.01     # just below title bar

def slide_lr(title, img_path, lines, img_w=0.54, fig_caption=""):
    """Figure on left, text on right."""
    fig = plt.figure(figsize=(W, H), facecolor=WHITE)
    _title_bar(fig, title)
    h = CONTENT_TOP - CONTENT_BOT
    _img(fig, [0.005, CONTENT_BOT, img_w - 0.01, h], img_path)
    if fig_caption:
        cap = fig.add_axes([0.005, CONTENT_BOT - 0.028, img_w - 0.01, 0.028])
        cap.axis("off")
        cap.text(0.0, 0.9, fig_caption, va="top", fontsize=10,
                 color=DGRAY, style="italic", transform=cap.transAxes)
    _text_block(fig, [img_w + 0.01, CONTENT_BOT, 1 - img_w - 0.02, h], lines)
    return fig


def slide_tb(title, img_path, lines, img_h=0.50, fig_caption=""):
    """Figure on top, text on bottom."""
    fig = plt.figure(figsize=(W, H), facecolor=WHITE)
    _title_bar(fig, title)
    bot_h = CONTENT_TOP - img_h - 0.01 - CONTENT_BOT
    _img(fig, [0.01, CONTENT_TOP - img_h, 0.98, img_h], img_path)
    if fig_caption:
        cap = fig.add_axes([0.01, CONTENT_TOP - img_h - 0.030, 0.98, 0.028])
        cap.axis("off")
        cap.text(0.0, 0.9, fig_caption, va="top", fontsize=10,
                 color=DGRAY, style="italic", transform=cap.transAxes)
    _text_block(fig, [0.01, CONTENT_BOT, 0.98, bot_h - 0.032], lines)
    return fig


def slide_full(img_path, caption=""):
    """Full-bleed image with optional caption strip."""
    fig = plt.figure(figsize=(W, H), facecolor="black")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.imshow(plt.imread(str(img_path)), aspect="auto")
    if caption:
        c = fig.add_axes([0, 0, 1, 0.048])
        c.set_facecolor((0, 0, 0, 0.60)); c.axis("off")
        c.text(0.010, 0.5, caption, va="center", fontsize=11,
               color=WHITE, transform=c.transAxes)
    return fig


def slide_text(title, lines, subtitle=""):
    """Text-only slide (no figure)."""
    fig = plt.figure(figsize=(W, H), facecolor=WHITE)
    _title_bar(fig, title)
    if subtitle:
        sub = fig.add_axes([0, 1 - BAR_H - 0.060, 1, 0.055])
        sub.set_facecolor("#EEF2F8"); sub.axis("off")
        sub.text(0.015, 0.5, subtitle, va="center", fontsize=12,
                 color=DGRAY, style="italic", transform=sub.transAxes)
        bot_ofs = 0.060
    else:
        bot_ofs = 0
    h = CONTENT_TOP - CONTENT_BOT - bot_ofs
    _text_block(fig, [0.04, CONTENT_BOT, 0.92, h - bot_ofs], lines)
    return fig


# ── Title slide ───────────────────────────────────────────────────────────────

def slide_title():
    fig = plt.figure(figsize=(W, H), facecolor=NAVY)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(NAVY); ax.axis("off")

    rule = fig.add_axes([0.07, 0.43, 0.86, 0.005])
    rule.set_facecolor(BLUE); rule.axis("off")

    ax.text(0.50, 0.72, "Cache Liveness & Mid-Insertion",
            va="center", ha="center", fontsize=32, fontweight="bold",
            color=WHITE, transform=ax.transAxes)
    ax.text(0.50, 0.58, "Preliminary results — April 2026",
            va="center", ha="center", fontsize=18, color="#9BB5CC",
            transform=ax.transAxes)
    ax.text(0.50, 0.31,
            "Goal: exploit dead-block eviction history to reduce wasted LLC and STLB capacity\n"
            "via mid-point insertion. We first characterise liveness across three benchmark\n"
            "suites (SPEC, Google, Qualcomm), then evaluate insertion policy choices.",
            va="center", ha="center", fontsize=13.5, color="#BBCCDD",
            transform=ax.transAxes, linespacing=1.8)
    return fig


# ── Section intro (kept simple/academic) ─────────────────────────────────────

def section_intro(number, title, topics):
    fig = plt.figure(figsize=(W, H), facecolor=NAVY)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(NAVY); ax.axis("off")

    ax.text(0.07, 0.82, number, fontsize=13, color="#5A8FB5",
            fontweight="bold", transform=ax.transAxes)
    ax.text(0.07, 0.70, title, fontsize=28, fontweight="bold",
            color=WHITE, transform=ax.transAxes)

    rule = fig.add_axes([0.07, 0.62, 0.86, 0.003])
    rule.set_facecolor(BLUE); rule.axis("off")

    y = 0.55
    for t in topics:
        ax.text(0.09, y, t, fontsize=14, color="#99B8CC",
                transform=ax.transAxes, linespacing=1.6)
        y -= 0.10
    return fig


# ═════════════════════════════════════════════════════════════════════════════
# §1  LIVENESS CHARACTERISATION
# ═════════════════════════════════════════════════════════════════════════════

def slide_sec1():
    return section_intro("Section 1", "Liveness Characterisation", [
        "1.  What fraction of evictions are dead on arrival (DoA)?",
        "2.  How much does this vary across workloads?",
        "3.  Does STLB DoA predict LLC DoA (cross-cache correlation)?",
        "4.  Is deadness concentrated in a few PCs (Lorenz curves)?",
    ])


def slide_liveness_agg():
    return slide_tb(
        "Liveness aggregate — LLC and STLB geomean per suite",
        LIV / "suite_liveness_bar_LLC_STLB.png",
        [
            "## Figure above: LLC (left panel) and STLB (right panel) — geomean across workloads.",
            "",
            "1.  LLC panel:  SPEC 75% DoA,  Google 60% DoA,  Qualcomm 52% DoA.",
            "    STLB panel: SPEC 88%,  Google 62%,  Qualcomm 56%.  The STLB is always"
            "  worse.",
            "",
            "2.  Mostly-alive fraction is negligible for SPEC (0.4%) and small for"
            "  Google (2%).",
            "    Qualcomm is the best case at ~36% mostly-alive — still >52% wasted.",
            "",
            "3.  Conclusion: every suite has a large target for mid-insertion in both caches.",
        ],
        img_h=0.50,
        fig_caption="Fig. 1",
    )


def slide_liveness_spec():
    return slide_tb(
        "Per-workload liveness — SPEC (DPC3, 95 workloads)",
        LIV / "spec_liveness_workloads.png",
        [
            "## Fig. 2  (upper panel = STLB,  lower panel = LLC;  red = DoA,  orange ="
            "  mostly-dead,  green = mostly-alive)",
            "",
            "1.  Distribution is bimodal: a handful of workloads are nearly 100% DoA"
            "  (streaming, pointer-chasing),",
            "    while a few others have a notable mostly-alive fraction.",
            "",
            "2.  The dead outliers pull the suite geomean down significantly.",
            "    Within-suite variance is the largest of the three suites.",
        ],
        img_h=0.50,
        fig_caption="Fig. 2",
    )


def slide_liveness_google():
    return slide_tb(
        "Per-workload liveness — Google (43 workloads)",
        LIV / "google_liveness_workloads.png",
        [
            "## Fig. 3  (upper = STLB,  lower = LLC)",
            "",
            "1.  Remarkably uniform: almost every workload sits in the 55–70% DoA band"
            "  in both caches.",
            "",
            "2.  Low within-suite variance means a single policy tuned once will apply"
            "  broadly.",
            "    There are no problematic outlier workloads to worry about.",
        ],
        img_h=0.50,
        fig_caption="Fig. 3",
    )


def slide_liveness_qmm():
    return slide_tb(
        "Per-workload liveness — Qualcomm (45 workloads)",
        LIV / "qmm_liveness_workloads.png",
        [
            "## Fig. 4  (upper = STLB,  lower = LLC)",
            "",
            "1.  Widest within-suite spread: several workloads have >40% mostly-alive"
            "  evictions.",
            "",
            "2.  Those workloads will benefit less from mid-insertion and may be harmed"
            "  if",
            "    the predictor is imprecise — they constrain how aggressive we can be.",
        ],
        img_h=0.50,
        fig_caption="Fig. 4",
    )


def slide_doa_corr():
    return slide_tb(
        "STLB–LLC DoA correlation",
        LIV / "liveness_corr_strip.png",
        [
            "## Fig. 5  —  Left: STLB DoA rate.  Centre: LLC DoA rate.  "
            "Right: of all LLC DoA blocks, what % live on a STLB-dead page?",
            "",
            "1.  Left & centre panels: STLB and LLC DoA rates are similar (60–67%)."
            "  The problem is not cache-specific.",
            "",
            "2.  Right panel — key result:"
            "  SPEC 43%,  Google 4.7%,  Qualcomm 1.8%.",
            "    For SPEC, a page-level STLB signal strongly predicts LLC deadness.",
            "    For Google/Qualcomm the caches are independently dead — a per-PC"
            "  signal is needed.",
        ],
        img_h=0.50,
        fig_caption="Fig. 5",
    )


def slide_lorenz_howto():
    return slide_text(
        "How to read a per-PC Lorenz curve",
        [
            "## Setup",
            "·  PCs sorted ascending by eviction count  →  x-axis.",
            "·  y-axis: cumulative share of DoA (or mostly-dead) evictions accounted for.",
            "·  Diagonal dashed line = reference for a perfectly uniform dead rate.",
            "",
            "## Curve above the diagonal  →  concentrated deadness",
            "·  Rarely-evicted PCs cause a disproportionate share of dead evictions.",
            "·  A per-PC predictor only needs to learn a short list of 'bad' PCs.",
            "·  More bowing = stronger leverage for the predictor.",
            "",
            "## Curve near the diagonal  →  uniform deadness",
            "·  Dead evictions are spread evenly; no PC stands out.",
            "·  A per-PC predictor has little structural advantage here.",
        ],
        subtitle="Figs. 6–7 on the next two slides — LLC then STLB, each a 2×3 grid "
                 "(rows: DoA / mostly-dead;  columns: SPEC / Google / Qualcomm)",
    )


def slide_lorenz_llc():
    return slide_full(
        LIV / "liveness_lorenz_LLC.png",
        caption="Fig. 6 — LLC per-PC Lorenz curves  "
                "·  Rows: DoA (top), Mostly-dead (bottom)  "
                "·  Cols: SPEC · Google · Qualcomm  "
                "·  Faded = individual workloads · solid bold = mean · dashed = pooled",
    )


def slide_lorenz_stlb():
    return slide_full(
        LIV / "liveness_lorenz_STLB.png",
        caption="Fig. 7 — STLB per-PC Lorenz curves  ·  Same layout as Fig. 6",
    )


def slide_lorenz_obs():
    return slide_text(
        "Lorenz curves — observations (Figs. 6–7)",
        [
            "## SPEC  (leftmost column in both figures)",
            "·  Strong bow above diagonal in both DoA and mostly-dead rows, LLC and STLB.",
            "·  A small set of PCs generates the large majority of dead evictions.",
            "·  STLB concentration is even more extreme than LLC.",
            "",
            "## Google  (centre column)",
            "·  Moderate bow, consistent across individual workloads (faded lines agree).",
            "·  Per-PC predictor has clear structural leverage.",
            "",
            "## Qualcomm  (rightmost column)",
            "·  Curves hug the diagonal in both caches — deadness is spread uniformly.",
            "·  Weakest case for a per-PC predictor.",
            "·  Yet PC + promote still wins in §2 — promotion corrects false positives.",
        ],
    )


# ═════════════════════════════════════════════════════════════════════════════
# §2  MID-INSERTION
# ═════════════════════════════════════════════════════════════════════════════

def slide_sec2():
    return section_intro("Section 2", "Mid-Insertion Threshold Study", [
        "1.  Which key: per-address or per-PC?",
        "2.  Should mid-inserted blocks be promoted to MRU on first hit?",
        "3.  What is the optimal threshold (mid_thd) per suite?",
    ])


def slide_mid_summary():
    return slide_lr(
        "Key selection and promotion — geomean IPC speedup vs LRU",
        MID / "addr_vs_pc_summary.png",
        [
            "## Fig. 8  —  4 bars/suite: addr/PC × promote/no-promote,\neach at its own optimal mid_thd.",
            "",
            "1.  PC+promote (darkest bar) is tallest in every suite.\n    Google: +1.95% vs +0.24% (addr+no-promote) — 8× gain.",
            "",
            "2.  Per-PC > per-address: instructions have stable patterns.\n    A load dead last time is likely dead again.\n    Address key is coarser and noisier.",
            "",
            "3.  Promote: wrongly mid-inserted live block stays at\n    midpoint without it; first hit corrects (MID_PROMOTE=1).\n    Most impactful for Google.",
            "",
            "4.  Decision: PC + promote selected for §3 sweep.",
        ],
        img_w=0.53,
        fig_caption="Fig. 8",
    )


def slide_mid_wl():
    return slide_tb(
        "Per-workload: addr key vs PC key at optimal threshold",
        MID / "addr_vs_pc_all.png",
        [
            "## Fig. 9  —  Blue = addr (N=optimal).  Orange = PC (N=optimal)."
            "  Rightmost bar = geomean.  Top: SPEC.  Middle: Google.  Bottom: Qualcomm.",
            "",
            "1.  Orange ≥ blue on almost every individual workload in all three suites.",
            "",
            "2.  SPEC (top panel): most workloads gain <2%, but a handful spike — these"
            "  are",
            "    exactly the workloads with strong STLB→LLC correlation (Fig. 5, right panel).",
            "",
            "3.  Google (middle): clean uniform advantage of ~1–2 pp per workload.",
            "    Qualcomm (bottom): PC wins but margins are narrower, consistent with"
            "  Fig. 7.",
        ],
        img_h=0.53,
        fig_caption="Fig. 9",
    )


# ═════════════════════════════════════════════════════════════════════════════
# §3  POLICY SWEEP
# ═════════════════════════════════════════════════════════════════════════════

def slide_sec3():
    return section_intro("Section 3", "Policy Sweep", [
        "1.  Compare lru_mid vs SRRIP vs DRRIP (all normalised to LRU).",
        "2.  No predictor active — isolates the mid-insertion threshold effect.",
        "⚠  3.  Prefetcher not yet configured correctly — results are directional only.",
    ])


def slide_sweep():
    return slide_lr(
        "Policy sweep — geomean IPC vs LRU (no predictor, no prefetcher)",
        PLOTS / "suite_ipc.png",
        [
            "## Fig. 10  —  lru_mid (purple) · SRRIP (orange) · DRRIP (teal).",
            "⚠  Prefetcher misconfigured — results are directional only.",
            "",
            "1.  lru_mid ≈ LRU: mid-insertion only fires for blocks with\n    existing dead history; cold-start history is sparse.",
            "",
            "2.  DRRIP: −15% on Google. Set-duelling misfires without\n    the correct prefetcher — applies wrong strategy suite-wide.\n    Known sensitivity of DRRIP to prefetch traffic.",
            "",
            "3.  SRRIP: broadly neutral across all suites.",
            "",
            "4.  Next step: rerun with --paper-pref (EPI + Berti +\n    next-line) and DPPRED=1 for a valid comparison.",
        ],
        img_w=0.50,
        fig_caption="Fig. 10",
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    slides = [
        slide_title,
        slide_sec1,
        slide_liveness_agg,
        slide_liveness_spec,
        slide_liveness_google,
        slide_liveness_qmm,
        slide_doa_corr,
        slide_lorenz_howto,
        slide_lorenz_llc,
        slide_lorenz_stlb,
        slide_lorenz_obs,
        slide_sec2,
        slide_mid_summary,
        slide_mid_wl,
        slide_sec3,
        slide_sweep,
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(OUT) as pdf:
        for fn in slides:
            save(pdf, fn())
        n = pdf.get_pagecount()
    print(f"Saved: {OUT}  ({n} slides)")


if __name__ == "__main__":
    main()
