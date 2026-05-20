"""
colors.py — shared color constants for all analysis plots.

Centralising colors here ensures visual consistency across figures and
makes palette changes a single-point edit.
"""

# ── Suite identity ────────────────────────────────────────────────────────────
# Extended palette — canonical order: SPEC, Google, Qualcomm, GAP, Ligra, GMS, ML.
SUITE_COLORS = [
    "#2C7BB6",  # blue        — SPEC
    "#D7191C",  # red         — Google
    "#1A9641",  # green       — Qualcomm
    "#FF7F00",  # orange      — GAP
    "#984EA3",  # purple      — Ligra
    "#A65628",  # brown       — GMS
    "#F781BF",  # pink        — ML
]

# ── Replacement policy ────────────────────────────────────────────────────────
LRU_COLOR  = "#1a9850"
LFU_COLOR  = "#4393c3"
HASH_COLOR = "#d73027"

POLICY_COLORS = {
    # SRRIP family (peach/orange/teal tones)
    # *_both variants share the LLC-only hue; hatch (see POLICY_HATCHES) marks LLC+STLB.
    "srrip":            "#E8A87C",  # soft peach         (LLC only)
    "srrip_both":       "#E8A87C",  # soft peach + hatch  (LLC+STLB)
    "srrip_live":       "#2E8B6A",  # teal green          (LLC, liveness)
    "srrip_live_both":  "#2E8B6A",  # teal green + hatch  (LLC+STLB, liveness)
    "stlb_srrip":       "#F0C090",  # pale peach          (STLB only)
    "stlb_srrip_live":  "#3A7EB5",  # steel blue          (STLB, liveness)
    # lru_mid family (purple tones)
    "lru_mid":          "#A67CB9",  # muted purple        (LLC only)
    "lru_mid_both":     "#A67CB9",  # muted purple + hatch (LLC+STLB)
    "stlb_lru_mid":     "#C9A8D8",  # pale purple         (STLB only)
    "lru_mid_pred":     "#6A3D8A",  # deep purple         (pred variant)
    # IPV family (gold tones — LLC; cyan tones — STLB)
    "ipv":              "#D4AC0D",  # golden yellow       (LLC only)
    "ipv_both":         "#D4AC0D",  # golden yellow + hatch (LLC+STLB)
    "ipv_live":         "#8E6914",  # amber gold          (LLC, liveness)
    "ipv_live_both":    "#8E6914",  # amber gold + hatch  (LLC+STLB, liveness)
    "stlb_ipv":         "#30B0C0",  # cyan                (STLB only)
    "stlb_ipv_live":    "#1A7080",  # dark cyan           (STLB, liveness)
    # Predictor / dp-only variants
    "lru_dp_only":      "#5B9BD5",  # cornflower blue
    "lru_pred":         "#2C5F8A",  # deep blue
    "srrip_pred":       "#C46A30",  # burnt orange
    # DRRIP
    "drrip":            "#E05050",  # coral red
    "drrip_pred":       "#A02020",  # dark red
}
POLICY_HATCHES = {
    "srrip":            "",
    "srrip_both":       "//",
    "srrip_live":       "",
    "srrip_live_both":  "xx",
    "stlb_srrip":       "..",
    "stlb_srrip_live":  "//",
    "lru_mid":          "",
    "lru_mid_both":     "//",
    "stlb_lru_mid":     "..",
    "lru_mid_pred":     "//",
    "ipv":              "",
    "ipv_both":         "//",
    "ipv_live":         "xx",
    "ipv_live_both":    "oo",
    "stlb_ipv":         "..",
    "stlb_ipv_live":    "//",
    "lru_dp_only":      "..",
    "lru_pred":         "//",
    "srrip_pred":       "//",
    "drrip":            "",
    "drrip_pred":       "//",
}

# ── Cache liveness ────────────────────────────────────────────────────────────
LIVENESS_COLORS = {
    "doa":          "#5B7FA6",  # steel blue
    "mostly_dead":  "#E8A87C",  # soft peach
    "mostly_alive": "#7CB9A8",  # soft teal
}
# Text contrast colour for each liveness segment bar label.
LIVENESS_LABEL_COLORS = {
    "doa":          "white",
    "mostly_dead":  "black",
    "mostly_alive": "white",
}
# Sequential palette for hit-histogram reuse-distance bars (cold → hot).
HIT_HIST_COLORS = [
    "#d73027", "#f46d43", "#fdae61", "#fee08b",
    "#d9ef8b", "#a6d96a", "#66bd63", "#1a9850", "#006837",
]
