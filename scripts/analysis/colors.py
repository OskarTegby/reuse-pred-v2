"""
colors.py — shared color constants for all analysis plots.

Centralising colors here ensures visual consistency across figures and
makes palette changes a single-point edit.
"""

# ── Suite identity ────────────────────────────────────────────────────────────
# Order matches the canonical suite order: SPEC CPU2006/2017, Google, Qualcomm.
SUITE_COLORS = ["#2C7BB6", "#D7191C", "#1A9641"]

# ── Replacement policy ────────────────────────────────────────────────────────
LRU_COLOR  = "#1a9850"
LFU_COLOR  = "#4393c3"
HASH_COLOR = "#d73027"

POLICY_COLORS = {
    "srrip":        "#E8A87C",  # soft peach
    "srrip_live":   "#2E8B6A",  # teal green
    "lru_mid":      "#A67CB9",  # muted purple
    "lru_dp_only":  "#5B9BD5",  # cornflower blue
    "lru_pred":     "#2C5F8A",  # deep blue
    "srrip_pred":   "#C46A30",  # burnt orange
    "lru_mid_pred": "#6A3D8A",  # deep purple
}
POLICY_HATCHES = {
    "srrip":        "",
    "srrip_live":   "xx",
    "lru_mid":      "",
    "lru_dp_only":  "..",
    "lru_pred":     "//",
    "srrip_pred":   "//",
    "lru_mid_pred": "//",
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
