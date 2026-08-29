from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle


ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = ROOT / "results" / "cti_rlex_base.json"
VERIFY_PATH = ROOT / "results" / "cti_rlex_verification.json"
EXPERIMENT_PATH = ROOT / "results" / "cti_rlex_experiments.json"
BENCHMARK_PATH = ROOT / "data" / "LittleBearRiver_2025_Benchmark" / "benchmark.json"
RESULTS_DIR = ROOT / "results"
FIGURE_DIR = RESULTS_DIR / "figures"
TABLE_DIR = RESULTS_DIR / "tables"

CLAIMANTS = ("company_088", "company_130", "company_132")
CLAIMANT_LABEL = {
    "company_088": "Hyrum",
    "company_130": "Paradise",
    "company_132": "Porcupine Highline",
}
SHORT_CLAIMANT_LABEL = {
    "company_088": "Hyrum",
    "company_130": "Paradise",
    "company_132": "Highline",
}
SCENARIO_ORDER = (
    "nominal",
    "moderate_system_shortage",
    "severe_system_shortage",
    "paradise_diversion_outage_under_shortage",
    "hyrum_canal_restriction_under_shortage",
)
SCENARIO_LABEL = {
    "nominal": "Nominal",
    "moderate_system_shortage": "Moderate shortage",
    "severe_system_shortage": "Severe shortage",
    "paradise_diversion_outage_under_shortage": "Paradise outage",
    "hyrum_canal_restriction_under_shortage": "Hyrum restriction",
}
SCENARIO_SHORT = {
    "nominal": "Nominal",
    "moderate_system_shortage": "Moderate",
    "severe_system_shortage": "Severe",
    "paradise_diversion_outage_under_shortage": "Paradise\noutage",
    "hyrum_canal_restriction_under_shortage": "Hyrum\nrestriction",
}
PERIOD_ORDER = ("2025-05", "2025-06", "2025-07", "2025-08", "2025-09")
PERIOD_LABEL = ("May", "Jun", "Jul", "Aug", "Sep")
METHOD_ORDER = (
    "UTIL-BR",
    "PROP-BR",
    "CTI-RLex rigid",
    "CTI-RLex proposed",
    "CTI-RLex nominal only",
)
SOURCE_COLORS = {
    "s_10434": "#4C78A8",
    "s_15269": "#72B7B2",
    "s_15286": "#F58518",
    "s_15957": "#B8B8B8",
}

# Figures 3, 4 and 8 in the manuscript are printed at 14 cm, whereas the
# reference figures (5--7) are used at their native circa-7.1-inch width.
# Scaling the type by this factor keeps the *printed* label size consistent
# after Word reduces the compact figures to 14 cm.
COMPACT_14_CM_FONT_SCALE = 7.1 * 2.54 / 14.0


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def configure_plotting() -> None:
    mpl.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Palatino Linotype", "Book Antiqua", "DejaVu Serif"],
            "font.size": 8.5,
            "axes.labelsize": 9,
            "axes.titlesize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8,
            "axes.linewidth": 0.7,
            "lines.linewidth": 1.4,
            "lines.markersize": 4.8,
            "savefig.facecolor": "white",
            "figure.facecolor": "white",
            "svg.fonttype": "none",
        }
    )


def configure_compact_14_cm_plotting() -> None:
    """Match the printed type size of the full-width reference figures."""
    configure_plotting()
    scale = COMPACT_14_CM_FONT_SCALE
    mpl.rcParams.update(
        {
            "font.size": 8.5 * scale,
            "axes.labelsize": 9 * scale,
            "axes.titlesize": 9 * scale,
            "xtick.labelsize": 8 * scale,
            "ytick.labelsize": 8 * scale,
            "legend.fontsize": 8 * scale,
        }
    )


def save_figure(fig: plt.Figure, stem: str) -> None:
    fig.savefig(FIGURE_DIR / f"{stem}.png", dpi=600, bbox_inches="tight", pad_inches=0.04)
    fig.savefig(FIGURE_DIR / f"{stem}.svg", bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)


def method_lookup(experiments: dict) -> dict[str, dict]:
    return {row["method"]: row for row in experiments["method_comparison"]}


def build_table_1(result: dict, benchmark: dict) -> None:
    demand = defaultdict(float)
    for row in benchmark["demands"]:
        demand[row["claimant_id"]] += float(row["demand_af"])
    alpha: dict[str, float] = {}
    for row in benchmark["terminal_parameters"]:
        alpha.setdefault(row["claimant_id"], float(row["application_efficiency"]))

    rows = []
    for claimant in CLAIMANTS:
        guarantee = float(result["guarantees"][claimant])
        binding = []
        for scenario in SCENARIO_ORDER:
            for period in PERIOD_ORDER:
                ratio = float(result["period_service_ratio"][f"{scenario}|{period}|{claimant}"])
                if abs(ratio - guarantee) <= 1e-7:
                    binding.append(f"{SCENARIO_LABEL[scenario]}:{period[-2:]}")
        rows.append(
            {
                "claimant": CLAIMANT_LABEL[claimant],
                "seasonal_net_demand_af": f"{demand[claimant]:.1f}",
                "application_efficiency": f"{alpha[claimant]:.2f}",
                "robust_period_guarantee": f"{guarantee:.4f}",
                "nominal_seasonal_ratio": f'{float(result["seasonal_service_ratio"][f"nominal|{claimant}"]):.4f}',
                "severe_seasonal_ratio": f'{float(result["seasonal_service_ratio"][f"severe_system_shortage|{claimant}"]):.4f}',
                "binding_cell_count": len(binding),
                "binding_cells": "; ".join(binding),
            }
        )
    write_csv(TABLE_DIR / "Table_1_claimant_performance.csv", list(rows[0]), rows)


def build_table_2(experiments: dict) -> None:
    methods = method_lookup(experiments)
    rows = []
    for name in METHOD_ORDER:
        item = methods[name]
        rows.append(
            {
                "method": name,
                "minimum_guarantee": f'{item["minimum_guarantee"]:.4f}',
                "hyrum_guarantee": f'{item["guarantees"]["company_088"]:.4f}',
                "paradise_guarantee": f'{item["guarantees"]["company_130"]:.4f}',
                "highline_guarantee": f'{item["guarantees"]["company_132"]:.4f}',
                "jain_index": f'{item["jain_guarantee_index"]:.4f}',
                "nominal_delivery_af": f'{item["nominal_beneficial_delivery_af"]:.1f}',
                "worst_scenario_delivery_af": f'{item["worst_scenario_beneficial_delivery_af"]:.1f}',
                "recourse_effort": f'{item["normalized_recourse_effort"]:.3f}',
                "runtime_s": f'{item["runtime_seconds"]:.3f}',
            }
        )
    write_csv(TABLE_DIR / "Table_2_method_comparison.csv", list(rows[0]), rows)


def build_table_3(experiments: dict) -> None:
    activation = experiments["operational_audit"]["source_activation"]
    names = {row["source_id"]: row["source_name"] for row in activation}
    rows = []
    for item in experiments["source_ablation"]:
        rows.append(
            {
                "disabled_source": names[item["disabled_source_id"]],
                "source_class": item["disabled_source_class"].replace("_", " "),
                "minimum_guarantee": f'{max(0.0, item["minimum_guarantee"]):.4f}',
                "change_minimum_guarantee_pp": f'{100 * item["change_in_minimum_guarantee"]:.2f}',
                "nominal_delivery_af": f'{item["nominal_beneficial_delivery_af"]:.1f}',
                "change_nominal_delivery_af": f'{item["change_in_nominal_delivery_af"]:.1f}',
                "worst_scenario_delivery_af": f'{item["worst_scenario_beneficial_delivery_af"]:.1f}',
            }
        )
    write_csv(TABLE_DIR / "Table_3_source_ablation.csv", list(rows[0]), rows)


def build_table_4(experiments: dict) -> None:
    sensitivity = experiments["sensitivity"]
    factor_labels = (
        ("demand_duty_af_per_acre", "Net duty (acre-ft acre-1)"),
        ("conveyance_loss_multiplier", "Conveyance-loss multiplier"),
        ("source_limit_scale", "Source-limit scale"),
        ("recourse_budget_scale", "Recourse-budget scale"),
    )
    rows = []
    for key, label in factor_labels:
        for level in sorted({float(row[key]) for row in sensitivity}):
            values = [float(row["minimum_guarantee"]) for row in sensitivity if float(row[key]) == level]
            rows.append(
                {
                    "factor": label,
                    "level": f"{level:g}",
                    "case_count": len(values),
                    "mean_minimum_guarantee": f"{mean(values):.4f}",
                    "minimum": f"{min(values):.4f}",
                    "maximum": f"{max(values):.4f}",
                }
            )
    write_csv(TABLE_DIR / "Table_4_sensitivity_main_effects.csv", list(rows[0]), rows)


def build_table_5(verification: dict, experiments: dict) -> None:
    rows = [
        {
            "audit": "Terminal-record invariance",
            "case": f'm={item["copies"]}',
            "observed": f'{item["guarantee_infinity_norm_error"]:.3e}',
            "criterion": "<=1.0e-8",
            "outcome": "Pass" if item["pass_at_1e-8"] else "Fail",
        }
        for item in verification["representation_tests"]
    ]
    residuals = verification["base_residuals"]
    rows.extend(
        [
            {
                "audit": "Base LP equality residual",
                "case": "5 scenarios",
                "observed": f'{residuals["max_equality_residual"]:.3e}',
                "criterion": "<=1.0e-7",
                "outcome": "Pass",
            },
            {
                "audit": "Base LP inequality violation",
                "case": "5 scenarios",
                "observed": f'{residuals["max_inequality_violation"]:.3e}',
                "criterion": "<=1.0e-7",
                "outcome": "Pass",
            },
            {
                "audit": "Full-factorial LP residual",
                "case": "135 cases",
                "observed": f'{max(row["maximum_lp_residual"] for row in experiments["sensitivity"]):.3e}',
                "criterion": "<=1.0e-7",
                "outcome": "Pass",
            },
        ]
    )
    for item in experiments["scalability"]:
        rows.append(
            {
                "audit": "LP size and solve time",
                "case": f'{item["scenario_count"]} scenario(s)',
                "observed": (
                    f'{item["variables"]} var; {item["equality_constraints"] + item["inequality_constraints"]} con; '
                    f'{item["median_runtime_seconds"]:.3f} s'
                ),
                # Read the repeat count the run itself recorded. This was a hardcoded
                # "3 repeats" that survived the move to the single five-repeat protocol, so
                # the published CSV contradicted both the manuscript and its own timings.
                "criterion": f'{item["repeats"]} repeats',
                "outcome": "Reported",
            }
        )
    write_csv(TABLE_DIR / "Table_5_numerical_computational_audit.csv", list(rows[0]), rows)


def build_tables(result: dict, verification: dict, experiments: dict, benchmark: dict) -> None:
    build_table_1(result, benchmark)
    build_table_2(experiments)
    build_table_3(experiments)
    build_table_4(experiments)
    build_table_5(verification, experiments)


def figure_claimant_guarantees(verification: dict) -> None:
    configure_compact_14_cm_plotting()
    rigid = verification["recourse_frontier"][0]["guarantees"]
    base = verification["base_guarantees"]
    x = np.arange(len(CLAIMANTS))
    width = 0.34
    fig, ax = plt.subplots(figsize=(7.1, 3.05), constrained_layout=True)
    bars1 = ax.bar(
        x - width / 2,
        [rigid[item] for item in CLAIMANTS],
        width,
        color="#D0D5DA",
        edgecolor="#3F4850",
        linewidth=0.7,
        hatch="////",
        label="Rigid plan ($b=0$)",
    )
    bars2 = ax.bar(
        x + width / 2,
        [base[item] for item in CLAIMANTS],
        width,
        color="#2F6B9A",
        edgecolor="#17364E",
        linewidth=0.7,
        label="Bounded recourse (base)",
    )
    ax.set_ylabel("Robust period-wise guarantee, $\\rho_f$")
    ax.set_xticks(x, [CLAIMANT_LABEL[item] for item in CLAIMANTS])
    ax.set_ylim(0, 0.52)
    ax.set_yticks(np.arange(0, 0.51, 0.10))
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.55)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=2, loc="lower center", bbox_to_anchor=(0.5, 1.005))
    for bars in (bars1, bars2):
        for bar in bars:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.008,
                f"{bar.get_height():.3f}",
                ha="center",
                va="bottom",
                fontsize=7.8 * COMPACT_14_CM_FONT_SCALE,
            )
    save_figure(fig, "Figure_1_claimant_guarantees")
    configure_plotting()


def figure_recourse_frontier(verification: dict) -> None:
    frontier = verification["recourse_frontier"]
    scale = np.asarray([float(row["budget_scale"]) for row in frontier])
    hyrum = np.asarray([float(row["guarantees"]["company_088"]) for row in frontier])
    shared = np.asarray([float(row["guarantees"]["company_130"]) for row in frontier])
    effort = np.asarray([float(row["normalized_recourse_effort"]) for row in frontier])
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.1, 3.05), constrained_layout=True)
    ax1.plot(scale, hyrum, color="#2F6B9A", marker="s", label="Hyrum")
    ax1.plot(scale, shared, color="#C65D21", marker="o", linestyle="--", label="Paradise and Highline")
    ax1.set_xlabel("Recourse-budget scale, $b$")
    ax1.set_ylabel("Robust guarantee, $\\rho_f$")
    ax1.set_xticks(scale)
    ax1.set_ylim(0.36, 0.47)
    ax1.grid(color="#D9D9D9", linewidth=0.55)
    ax1.legend(frameon=False, loc="lower right")
    ax1.text(-0.13, 1.02, "(a)", transform=ax1.transAxes, fontweight="bold")
    ax2.plot(scale, effort, color="#317873", marker="D")
    ax2.set_xlabel("Recourse-budget scale, $b$")
    ax2.set_ylabel("Normalized recourse effort")
    ax2.set_xticks(scale)
    ax2.set_ylim(bottom=0)
    ax2.grid(color="#D9D9D9", linewidth=0.55)
    ax2.text(-0.13, 1.02, "(b)", transform=ax2.transAxes, fontweight="bold")
    for axis in (ax1, ax2):
        axis.spines[["top", "right"]].set_visible(False)
        axis.set_axisbelow(True)
    save_figure(fig, "Figure_2_recourse_frontier")


def figure_service_heatmap(result: dict) -> None:
    rows = []
    row_labels = []
    bindings = []
    for scenario in SCENARIO_ORDER:
        for claimant in CLAIMANTS:
            values = [
                float(result["period_service_ratio"][f"{scenario}|{period}|{claimant}"])
                for period in PERIOD_ORDER
            ]
            rows.append(values)
            row_labels.append(f"{SCENARIO_LABEL[scenario]} - {SHORT_CLAIMANT_LABEL[claimant]}")
            guarantee = float(result["guarantees"][claimant])
            bindings.append([abs(value - guarantee) <= 1e-7 for value in values])
    matrix = np.asarray(rows)
    fig, ax = plt.subplots(figsize=(7.1, 5.0), constrained_layout=True)
    image = ax.imshow(matrix, cmap="cividis", vmin=0.40, vmax=1.00, aspect="auto")
    ax.set_xticks(np.arange(len(PERIOD_LABEL)), PERIOD_LABEL)
    ax.set_yticks(np.arange(len(row_labels)), row_labels)
    ax.tick_params(axis="y", labelsize=7.2)
    ax.tick_params(axis="x", top=True, labeltop=True, bottom=False, labelbottom=False)
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            color = "white" if matrix[i, j] < 0.67 else "black"
            ax.text(j, i, f"{matrix[i, j]:.2f}", ha="center", va="center", color=color, fontsize=6.9)
            if bindings[i][j]:
                ax.add_patch(
                    Rectangle(
                        (j - 0.47, i - 0.47),
                        0.94,
                        0.94,
                        fill=False,
                        edgecolor="white" if matrix[i, j] < 0.67 else "black",
                        linewidth=1.1,
                    )
                )
    for boundary in (2.5, 5.5, 8.5, 11.5):
        ax.axhline(boundary, color="white", linewidth=1.4)
    colorbar = fig.colorbar(image, ax=ax, fraction=0.035, pad=0.02)
    colorbar.set_label("Delivered-demand ratio")
    ax.set_xlabel("Planning period")
    ax.xaxis.set_label_position("top")
    save_figure(fig, "Figure_3_period_service_heatmap")


def figure_source_activation(experiments: dict) -> None:
    rows = experiments["operational_audit"]["source_activation"]
    water = {row["scenario_id"]: row for row in experiments["operational_audit"]["scenario_water_balance"]}
    names = {}
    values = defaultdict(dict)
    for row in rows:
        names[row["source_id"]] = row["source_name"]
        values[row["scenario_id"]][row["source_id"]] = row["seasonal_injection_af"]
    x = np.arange(len(SCENARIO_ORDER))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.1, 3.25), constrained_layout=True, gridspec_kw={"width_ratios": [1.55, 1]})
    bottom = np.zeros(len(SCENARIO_ORDER))
    for source in ("s_10434", "s_15269", "s_15286", "s_15957"):
        data = np.asarray([values[scenario].get(source, 0.0) for scenario in SCENARIO_ORDER])
        ax1.bar(
            x,
            data,
            bottom=bottom,
            color=SOURCE_COLORS[source],
            edgecolor="white",
            linewidth=0.4,
            label=names[source].replace("Surface diversion at node ", "Diversion "),
        )
        bottom += data
    beneficial = [water[scenario]["beneficial_delivery_af"] for scenario in SCENARIO_ORDER]
    ax1.plot(x, beneficial, color="#222222", marker="o", linewidth=1.3, label="Beneficial delivery")
    ax1.set_ylabel("Seasonal volume (acre-ft)")
    ax1.set_xticks(x, [SCENARIO_SHORT[item] for item in SCENARIO_ORDER])
    ax1.tick_params(axis="x", labelsize=7.2)
    ax1.grid(axis="y", color="#E0E0E0", linewidth=0.5)
    ax1.set_axisbelow(True)
    ax1.legend(frameon=False, ncol=2, loc="lower center", bbox_to_anchor=(0.5, 1.01), fontsize=7.1)
    ax1.text(-0.10, 1.03, "(a)", transform=ax1.transAxes, fontweight="bold")
    conveyance = [water[scenario]["conveyance_loss_af"] for scenario in SCENARIO_ORDER]
    application = [water[scenario]["application_loss_af"] for scenario in SCENARIO_ORDER]
    ax2.barh(x, conveyance, color="#9ECAE1", label="Conveyance loss")
    ax2.barh(x, application, left=conveyance, color="#FDD0A2", label="Application loss")
    ax2.set_yticks(x, [SCENARIO_SHORT[item].replace("\n", " ") for item in SCENARIO_ORDER])
    ax2.invert_yaxis()
    ax2.set_xlabel("Seasonal loss (acre-ft)")
    ax2.grid(axis="x", color="#E0E0E0", linewidth=0.5)
    ax2.set_axisbelow(True)
    ax2.legend(frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.01), fontsize=7.1)
    ax2.text(-0.18, 1.03, "(b)", transform=ax2.transAxes, fontweight="bold")
    for axis in (ax1, ax2):
        axis.spines[["top", "right"]].set_visible(False)
    save_figure(fig, "Figure_4_source_activation_water_balance")


def figure_sensitivity_heatmaps(experiments: dict) -> None:
    configure_compact_14_cm_plotting()
    rows = [row for row in experiments["sensitivity"] if abs(float(row["recourse_budget_scale"]) - 1.0) <= 1e-12]
    duty = [1.5, 2.0, 2.5]
    supply = [0.8, 1.0, 1.2]
    losses = [0.5, 1.0, 2.0]
    lookup = {
        (float(row["conveyance_loss_multiplier"]), float(row["demand_duty_af_per_acre"]), float(row["source_limit_scale"])): float(row["minimum_guarantee"])
        for row in rows
    }
    matrices = [np.asarray([[lookup[loss, item_duty, item_supply] for item_supply in supply] for item_duty in duty]) for loss in losses]
    vmin = min(float(matrix.min()) for matrix in matrices)
    vmax = max(float(matrix.max()) for matrix in matrices)
    fig, axes = plt.subplots(1, 3, figsize=(7.1, 2.75), constrained_layout=True)
    image = None
    for index, (axis, loss, matrix) in enumerate(zip(axes, losses, matrices)):
        image = axis.imshow(matrix, cmap="viridis", vmin=vmin, vmax=vmax, aspect="equal")
        axis.set_xticks(range(3), [f"{value:g}" for value in supply])
        axis.set_yticks(range(3), [f"{value:g}" for value in duty])
        axis.set_xlabel("Source-limit scale")
        if index == 0:
            axis.set_ylabel("Net duty (acre-ft acre$^{-1}$)")
        axis.set_title(f"Loss multiplier = {loss:g}")
        axis.text(-0.18, 1.04, f"({chr(97 + index)})", transform=axis.transAxes, fontweight="bold")
        for i in range(3):
            for j in range(3):
                color = "white" if matrix[i, j] < (vmin + vmax) / 2 else "black"
                axis.text(
                    j,
                    i,
                    f"{matrix[i, j]:.3f}",
                    ha="center",
                    va="center",
                    color=color,
                    fontsize=7.2 * COMPACT_14_CM_FONT_SCALE,
                )
    assert image is not None
    colorbar = fig.colorbar(image, ax=axes, fraction=0.035, pad=0.02)
    colorbar.set_label("Minimum robust guarantee")
    save_figure(fig, "Figure_5_sensitivity_heatmaps")
    configure_plotting()


def figure_method_tradeoff(experiments: dict) -> None:
    configure_compact_14_cm_plotting()
    methods = method_lookup(experiments)
    styles = {
        "UTIL-BR": ("o", "#C65D21"),
        "PROP-BR": ("s", "#8C6BB1"),
        "CTI-RLex rigid": ("D", "#7A7A7A"),
        "CTI-RLex proposed": ("^", "#2F6B9A"),
        "CTI-RLex nominal only": ("X", "#317873"),
    }
    fig, ax = plt.subplots(figsize=(7.1, 3.45), constrained_layout=True)
    for method in METHOD_ORDER:
        item = methods[method]
        marker, color = styles[method]
        ax.scatter(
            item["nominal_beneficial_delivery_af"],
            item["minimum_guarantee"],
            marker=marker,
            s=48,
            color=color,
            edgecolor="white",
            linewidth=0.7,
            label=method,
            zorder=3,
        )
    point = methods["CTI-RLex proposed"]
    ax.annotate(
        "PROP-BR and proposed\ncoincide in this instance",
        xy=(point["nominal_beneficial_delivery_af"], point["minimum_guarantee"]),
        xytext=(-115, 28),
        textcoords="offset points",
        arrowprops={"arrowstyle": "-", "color": "#555555", "lw": 0.7},
        fontsize=7.7 * COMPACT_14_CM_FONT_SCALE,
    )
    nominal = methods["CTI-RLex nominal only"]
    ax.annotate(
        "Not contingency-robust",
        xy=(nominal["nominal_beneficial_delivery_af"], nominal["minimum_guarantee"]),
        xytext=(-105, -20),
        textcoords="offset points",
        fontsize=7.7 * COMPACT_14_CM_FONT_SCALE,
    )
    ax.set_xlabel("Nominal beneficial delivery (acre-ft)")
    ax.set_ylabel("Minimum guaranteed service ratio")
    ax.grid(color="#E0E0E0", linewidth=0.55)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(
        frameon=False,
        ncol=3,
        loc="lower center",
        bbox_to_anchor=(0.5, 1.01),
        fontsize=7.2 * COMPACT_14_CM_FONT_SCALE,
    )
    save_figure(fig, "Figure_6_method_tradeoff")
    configure_plotting()


def main() -> None:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    verification = json.loads(VERIFY_PATH.read_text(encoding="utf-8"))
    experiments = json.loads(EXPERIMENT_PATH.read_text(encoding="utf-8"))
    benchmark = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    configure_plotting()
    build_tables(result, verification, experiments, benchmark)
    figure_claimant_guarantees(verification)
    figure_recourse_frontier(verification)
    figure_service_heatmap(result)
    figure_source_activation(experiments)
    figure_sensitivity_heatmaps(experiments)
    figure_method_tradeoff(experiments)


if __name__ == "__main__":
    main()
