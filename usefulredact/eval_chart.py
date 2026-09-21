"""The evaluation chart: documents handled correctly, by redaction method.

"Handled correctly" is the document-level outcome: flagged when the file has an
issue, passed when it has none. That reads the same way for every method, where
"share flagged" would want 100% on some rows and 0% on others.

Colours are the first three slots of a palette checked for colour-blind
separation on all pairs; identity never rests on colour alone (legend, plus a
count on every bar short of full marks), and the report carries the same
numbers as a table.
"""

from __future__ import annotations

from pathlib import Path

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"

SERIES = [  # (label, colour, how to read a row's outcome)
    ("Full pipeline", "#2a78d6", lambda r: r.flagged),
    (
        "Full pipeline, sender's own details on the ignore list",
        "#1baf7a",
        lambda r: r.flagged_ignoring,
    ),
    ("Baseline: text layer + regex", "#eb6834", lambda r: r.baseline_flagged),
]

METHOD_NAMES = {
    "m1_none": "No redaction",
    "m3_drawn_box": "Black box drawn over text",
    "m4_annotation": "Black annotation, never applied",
    "m5_see_through": "See-through fill or highlight",
    "m8_pasted_image": "Black image pasted over text",
    "m6_scan_marker_60": "Scan, marker at 60% opacity",
    "m6_scan_marker_85": "Scan, marker at 85% opacity",
    "m2_proper": "Control: redaction properly applied",
    "m6_scan_marker_100": "Control: scan, fully opaque marker",
    "m7_control": "Control: no PI in the document",
}


def draw(rows, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    methods = [m for m in METHOD_NAMES if any(r.method == m for r in rows)]
    bar, gap = 0.22, 0.04
    fig, ax = plt.subplots(figsize=(9.6, 0.6 * len(methods) + 1.9), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    for row_index, method in enumerate(methods):
        group = [r for r in rows if r.method == method]
        for series_index, (_, colour, flagged) in enumerate(SERIES):
            right = sum(flagged(r) == r.expected_issue for r in group)
            share = right / len(group)
            y = row_index + (series_index - 1) * (bar + gap)
            ax.barh(y, share, height=bar, color=colour, zorder=3)
            if right < len(group):  # label the exceptions, not every bar
                ax.text(max(share, 0) + 0.012, y, f"{right}/{len(group)}", va="center",
                        ha="left", fontsize=8.5, color=TEXT_SECONDARY, zorder=4)  # fmt: skip

    n = len([r for r in rows if r.method == methods[0]])
    ax.set_yticks(range(len(methods)))
    ax.set_yticklabels([METHOD_NAMES[m] for m in methods], fontsize=9.5, color=TEXT)
    ax.set_ylim(len(methods) - 0.45, -0.55)
    ax.set_xlim(0, 1.0)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"], fontsize=8.5, color=TEXT_SECONDARY)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    ax.tick_params(length=0)
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_visible(False)

    fig.suptitle("Documents handled correctly, by redaction method", x=0.02, ha="left",
                 fontsize=13, fontweight="bold", color=TEXT)  # fmt: skip
    fig.text(
        0.02, 0.93,
        f"Synthetic corpus, {len(rows)} invented documents, {n} per method. Correct = flagged "
        "when there is an issue, passed when there is none.\nBars short of 100% are labelled "
        "with their count.",
        ha="left", va="top", fontsize=8.8, color=TEXT_SECONDARY,
    )  # fmt: skip
    handles = [plt.Rectangle((0, 0), 1, 1, color=colour) for _, colour, _ in SERIES]
    fig.legend(handles, [label for label, _, _ in SERIES], loc="lower left",
               bbox_to_anchor=(0.02, 0.005), ncol=1, frameon=False, fontsize=8.8,
               labelcolor=TEXT, handlelength=1.2, handleheight=0.9)  # fmt: skip
    fig.subplots_adjust(left=0.30, right=0.95, top=0.86, bottom=0.17)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
