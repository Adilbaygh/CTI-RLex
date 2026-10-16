"""Draw Figure 2 of the manuscript: the CTI-RLex computational workflow.

The first version of this figure was drawn by hand. It is now drawn by this script so that
its wording follows the text: the three stages after the guarantee vector are the delivery
and recourse stages of the objective hierarchy (Section 2.4.3), not tie-breaks that would
make the schedule unique (Reviewer 3, comment 2), and the construction step checks
acyclicity rather than imposing it (Reviewer 1, comment 1.1).

Run:  python scripts/draw_figure2_workflow.py
Writes: results/figures/Figure_2_cti_rlex_solution_workflow.png at 600 dpi, and .svg
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
FIGURE_DIR = ROOT / "results" / "figures"
STEM = "Figure_2_cti_rlex_solution_workflow"

BLUE = ("#2F6EA3", "#EAF2FA")
GREEN = ("#3E8E41", "#EAF6EA")
ORANGE = ("#C8741C", "#FDF1E4")
PURPLE = ("#8B5BA6", "#F3EAF8")
ARROW = "#45556A"
LABEL = "#5A6470"

TOP = [
    ("Load validated\nbenchmark", BLUE),
    ("Validate schema,\nunits and acyclicity", GREEN),
    ("Build the joint\nmulti-scenario LP", ORANGE),
    ("Progressively fill\nclaimant guarantees", PURPLE),
]
BOTTOM = [
    ("Export tables and\n600 dpi/SVG\nfigures", BLUE),
    ("Audit residuals and\nrepresentation\ninvariance", GREEN),
    ("Solve the delivery\nand recourse\nstages", ORANGE),
    ("Fix the complete\nleximin guarantee\nvector", PURPLE),
]


def configure() -> None:
    mpl.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Palatino Linotype", "TeX Gyre Pagella", "Book Antiqua", "DejaVu Serif"],
        "savefig.facecolor": "white",
        "figure.facecolor": "white",
        "svg.fonttype": "none",
    })


def box(ax, x, y, w, h, text, colors) -> None:
    edge, face = colors
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.06",
                                linewidth=1.6, edgecolor=edge, facecolor=face))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=11.2,
            fontweight="bold", color="#222222", linespacing=1.15)


def arrow(ax, start, end) -> None:
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=13,
                                 linewidth=1.6, color=ARROW))


def main() -> None:
    configure()
    fig = plt.figure(figsize=(7.0, 2.69))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 10.22)
    ax.set_ylim(0, 3.84)
    ax.axis("off")
    w, h, gap, x0 = 2.16, 0.98, 0.48, 0.06
    xs = [x0 + i * (w + gap) for i in range(4)]
    y_top, y_bottom = 2.30, 0.48
    for (text, colors), x in zip(TOP, xs):
        box(ax, x, y_top, w, h, text, colors)
    for (text, colors), x in zip(BOTTOM, xs):
        box(ax, x, y_bottom, w, h, text, colors)
    for i in range(3):
        arrow(ax, (xs[i] + w, y_top + h / 2), (xs[i + 1], y_top + h / 2))
        arrow(ax, (xs[i + 1], y_bottom + h / 2), (xs[i] + w, y_bottom + h / 2))
    arrow(ax, (xs[3] + w / 2, y_top), (xs[3] + w / 2, y_bottom + h))
    ax.text(x0, 3.62, "Input and model construction", fontsize=12.5, color=LABEL, va="center")
    ax.text(x0, 0.20, "Verification and reporting", fontsize=12.5, color=LABEL, va="center")
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE_DIR / f"{STEM}.png", dpi=600)
    fig.savefig(FIGURE_DIR / f"{STEM}.svg")
    plt.close(fig)
    print(f"written {FIGURE_DIR / STEM}.png and .svg")


if __name__ == "__main__":
    main()
