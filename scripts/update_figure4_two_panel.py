"""Rebuild manuscript Figure 4 as a two-panel comparison.

Panel (a) keeps the delivery-fairness trade-off of the three-claimant instance, where
the common-floor comparator and the proposed method coincide. Panel (b) adds what that
instance cannot show: the two sorted guarantee vectors of the ten-claimant instance and
the position at which they first differ.

The plotting style is copied from ``scripts/create_results_artifacts.py`` so the new
figure carries the same type size, palette and grid as every other figure in the paper.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt

REPO = Path(__file__).resolve().parents[1]
EXPERIMENTS = REPO / "results" / "cti_rlex_experiments.json"
REVISION = REPO / "results" / "revision_experiments.json"
# The published figure set lives beside the other artifacts so that a reader can find it
# from the repository; the article numbers this panel pair Figure 4.
OUTPUT = REPO / "results" / "figures"
STEM = "Figure_6_method_tradeoff_two_panel"

COMPACT_14_CM_FONT_SCALE = 7.1 * 2.54 / 14.0

METHOD_ORDER = [
    "UTIL-BR",
    "PROP-BR",
    "CTI-RLex rigid",
    "CTI-RLex proposed",
    "CTI-RLex nominal only",
]
STYLES = {
    "UTIL-BR": ("o", "#C65D21"),
    "PROP-BR": ("s", "#8C6BB1"),
    "CTI-RLex rigid": ("D", "#7A7A7A"),
    "CTI-RLex proposed": ("^", "#2F6B9A"),
    "CTI-RLex nominal only": ("X", "#317873"),
}


def configure() -> None:
    scale = COMPACT_14_CM_FONT_SCALE
    mpl.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Palatino Linotype", "P052", "Book Antiqua", "DejaVu Serif"],
            "font.size": 8.5 * scale,
            "axes.labelsize": 9 * scale,
            "axes.titlesize": 9 * scale,
            "xtick.labelsize": 8 * scale,
            "ytick.labelsize": 8 * scale,
            "legend.fontsize": 8 * scale,
            "axes.linewidth": 0.7,
            "lines.linewidth": 1.4,
            "lines.markersize": 4.8,
            "savefig.facecolor": "white",
            "figure.facecolor": "white",
            "svg.fonttype": "none",
        }
    )


def panel_tradeoff(ax, methods: dict) -> None:
    for method in METHOD_ORDER:
        row = methods[method]
        marker, color = STYLES[method]
        ax.scatter(
            row["nominal_beneficial_delivery_af"],
            row["minimum_guarantee"],
            marker=marker,
            s=44,
            color=color,
            edgecolor="white",
            linewidth=0.7,
            label=method,
            zorder=3,
        )
    proposed = methods["CTI-RLex proposed"]
    ax.annotate(
        "PROP-BR and proposed\ncoincide here",
        xy=(proposed["nominal_beneficial_delivery_af"], proposed["minimum_guarantee"]),
        xytext=(18, 46),
        textcoords="offset points",
        arrowprops={"arrowstyle": "-", "color": "#555555", "lw": 0.7},
        fontsize=7.7 * COMPACT_14_CM_FONT_SCALE,
    )
    nominal = methods["CTI-RLex nominal only"]
    ax.annotate(
        "Not contingency-robust",
        xy=(nominal["nominal_beneficial_delivery_af"], nominal["minimum_guarantee"]),
        xytext=(-118, -22),
        textcoords="offset points",
        fontsize=7.7 * COMPACT_14_CM_FONT_SCALE,
    )
    ax.set_xlabel("Nominal beneficial delivery (acre-ft)")
    ax.set_ylabel("Minimum guaranteed service ratio")
    ax.grid(color="#E0E0E0", linewidth=0.55)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)


def panel_sorted_vectors(ax, revision: dict) -> None:
    case = revision["cache_valley_v3"]
    rlex = case["cti_rlex"]["sorted_rho"]
    prop = case["prop_br"]["sorted_rho"]
    positions = list(range(1, len(rlex) + 1))
    first = case["lexicographic_comparison"]["first_differing_position"]

    ax.axvline(first, color="#B0B0B0", linewidth=0.8, linestyle=(0, (4, 3)), zorder=1)
    ax.plot(
        positions,
        prop,
        marker="s",
        color="#8C6BB1",
        linestyle="--",
        label="PROP-BR common floor",
        zorder=3,
    )
    ax.plot(
        positions,
        rlex,
        marker="^",
        color="#2F6B9A",
        label="CTI-RLex proposed",
        zorder=4,
    )
    ax.annotate(
        f"first difference at position {first}:\n{rlex[first - 1]:.4f} against {prop[first - 1]:.4f}",
        xy=(first, rlex[first - 1]),
        xytext=(0.33, 0.09),
        textcoords="axes fraction",
        ha="left",
        va="bottom",
        arrowprops={"arrowstyle": "-", "color": "#555555", "lw": 0.7},
        fontsize=7.7 * COMPACT_14_CM_FONT_SCALE,
    )
    ax.set_xlabel("Position in the sorted guarantee vector")
    ax.set_ylabel("Claimant guarantee")
    ax.set_xticks(positions)
    ax.set_ylim(-0.03, 1.08)
    ax.grid(color="#E0E0E0", linewidth=0.55)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)


def main() -> None:
    configure()
    experiments = json.loads(EXPERIMENTS.read_text(encoding="utf-8"))
    revision = json.loads(REVISION.read_text(encoding="utf-8"))
    methods = {row["method"]: row for row in experiments["method_comparison"]}

    fig, (left, right) = plt.subplots(1, 2, figsize=(7.1, 3.15), constrained_layout=True)
    panel_tradeoff(left, methods)
    panel_sorted_vectors(right, revision)

    handles, labels = left.get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        frameon=False,
        ncol=5,
        loc="lower center",
        bbox_to_anchor=(0.5, 1.0),
        fontsize=7.0 * COMPACT_14_CM_FONT_SCALE,
    )
    right.legend(frameon=False, loc="upper left", fontsize=7.0 * COMPACT_14_CM_FONT_SCALE)
    left.text(-0.16, 1.02, "(a)", transform=left.transAxes, fontweight="bold")
    right.text(-0.14, 1.02, "(b)", transform=right.transAxes, fontweight="bold")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT / f"{STEM}.png", dpi=600, bbox_inches="tight", pad_inches=0.04)
    fig.savefig(OUTPUT / f"{STEM}.svg", bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    print("wrote", OUTPUT / f"{STEM}.png")
    print("wrote", OUTPUT / f"{STEM}.svg")


if __name__ == "__main__":
    main()
