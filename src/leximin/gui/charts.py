"""Dynamic charts generated only from the selected benchmark and solver output."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402

from .i18n import DEFAULT_LANGUAGE, pick


PALETTE = ["#0284C7", "#0F766E", "#D97706", "#7C3AED", "#DC2626", "#475569"]


class ChartStore:
    """Own a disposable chart cache and expose stable paths during one GUI session."""

    def __init__(self) -> None:
        self._temp = TemporaryDirectory(prefix="cti_rlex_gui_")
        self.directory = Path(self._temp.name)
        self.paths: dict[str, Path] = {}
        self._configure()

    def close(self) -> None:
        self._temp.cleanup()

    def _configure(self) -> None:
        plt.rcParams.update(
            {
                "font.family": "sans-serif",
                "font.sans-serif": ["Segoe UI", "Arial", "DejaVu Sans"],
                "font.size": 9.5,
                "axes.titlesize": 11,
                "axes.labelsize": 9.5,
                "axes.spines.top": False,
                "axes.spines.right": False,
                "axes.grid": True,
                "grid.color": "#E2E8F0",
                "grid.linewidth": 0.65,
                "figure.facecolor": "white",
                "axes.facecolor": "white",
                "svg.fonttype": "none",
            }
        )

    def save(self, key: str, figure: plt.Figure) -> Path:
        self._configure()
        png = self.directory / f"{key}.png"
        svg = self.directory / f"{key}.svg"
        figure.savefig(png, dpi=220, bbox_inches="tight", pad_inches=0.08)
        figure.savefig(svg, bbox_inches="tight", pad_inches=0.08)
        plt.close(figure)
        self.paths[key] = png
        return png

    def network(self, raw: dict[str, Any], language: str = DEFAULT_LANGUAGE) -> Path:
        nodes = {row["node_id"]: row for row in raw.get("nodes", [])}
        graph = nx.DiGraph()
        graph.add_nodes_from(nodes)
        for edge in raw.get("edges", []):
            graph.add_edge(edge["from_node"], edge["to_node"])
        geographic: dict[str, tuple[float, float]] = {}
        for node_id, row in nodes.items():
            lon, lat = row.get("longitude"), row.get("latitude")
            if lon is not None and lat is not None:
                geographic[node_id] = (float(lon), float(lat))
        positions = (
            geographic
            if len(geographic) == len(nodes)
            else nx.spring_layout(graph, seed=17, k=1.5)
        )
        figure, axis = plt.subplots(figsize=(9.2, 6.0))
        nx.draw_networkx_edges(
            graph,
            positions,
            ax=axis,
            edge_color="#94A3B8",
            width=1.2,
            arrows=True,
            arrowsize=10,
            connectionstyle="arc3,rad=0.03",
        )
        nx.draw_networkx_nodes(
            graph,
            positions,
            ax=axis,
            node_size=25,
            node_color="#CBD5E1",
            edgecolors="#64748B",
            linewidths=0.5,
        )
        source_nodes = {row["node_id"] for row in raw.get("sources", [])}
        terminal_nodes = {row["terminal_node"] for row in raw.get("claimant_terminals", [])}
        if source_nodes:
            nx.draw_networkx_nodes(
                graph,
                positions,
                nodelist=list(source_nodes),
                ax=axis,
                node_size=95,
                node_color="#0EA5E9",
                edgecolors="#075985",
                linewidths=0.9,
                node_shape="^",
                label=pick(language, "Манба", "Source"),
            )
        if terminal_nodes:
            nx.draw_networkx_nodes(
                graph,
                positions,
                nodelist=list(terminal_nodes),
                ax=axis,
                node_size=85,
                node_color="#F59E0B",
                edgecolors="#92400E",
                linewidths=0.9,
                node_shape="s",
                label=pick(language, "Талабгор терминали", "Claimant terminal"),
            )
        labels: dict[str, str] = {}
        for row in raw.get("sources", []):
            labels[row["node_id"]] = row.get("source_name", row["source_id"])
        claimant_names = {
            row["claimant_id"]: row.get("claimant_name", row["claimant_id"])
            for row in raw.get("claimants", [])
        }
        for row in raw.get("claimant_terminals", []):
            labels[row["terminal_node"]] = claimant_names.get(
                row["claimant_id"], row["claimant_id"]
            )
        nx.draw_networkx_labels(
            graph, positions, labels=labels, ax=axis, font_size=7.5, font_color="#0F172A"
        )
        axis.set_title(
            pick(language, "Benchmark ирригация тармоғи", "Benchmark irrigation network")
        )
        axis.legend(frameon=False, loc="best")
        axis.set_axis_off()
        return self.save("network_topology", figure)

    def guarantees(
        self,
        raw: dict[str, Any],
        base: dict[str, Any],
        analysis: dict[str, Any] | None = None,
        language: str = DEFAULT_LANGUAGE,
    ) -> Path:
        proposed = base.get("guarantees", {})
        claimants = list(proposed)
        names = {
            row["claimant_id"]: row.get("claimant_name", row["claimant_id"])
            for row in raw.get("claimants", [])
        }
        labels = [names.get(item, item) for item in claimants]
        figure, axis = plt.subplots(figsize=(9.2, 4.3))
        x = np.arange(len(claimants))
        if analysis:
            rigid = next(
                row for row in analysis["method_comparison"] if row["method"] == "CTI-RLex rigid"
            )
            width = 0.36
            axis.bar(
                x - width / 2,
                [rigid["guarantees"][item] for item in claimants],
                width,
                color="#CBD5E1",
                edgecolor="#475569",
                hatch="///",
                label=pick(language, "Қатъий бошқарув", "Rigid operation"),
            )
            axis.bar(
                x + width / 2,
                [proposed[item] for item in claimants],
                width,
                color="#0284C7",
                label=pick(language, "Чегараланган қайта мослашув", "Bounded recourse"),
            )
        else:
            axis.bar(x, [proposed[item] for item in claimants], 0.52, color="#0284C7")
        axis.set_xticks(x, labels, rotation=12, ha="right")
        axis.set_ylabel(
            pick(language, "Даврлар бўйича робаст кафолат", "Robust period-wise guarantee")
        )
        axis.set_ylim(0, max(1.0, max(proposed.values(), default=1.0) * 1.18))
        axis.set_title(
            pick(language, "Талабгорлар кесимидаги робаст кафолатлар", "Claimant-level robust guarantees")
        )
        if analysis:
            axis.legend(frameon=False)
        figure.tight_layout()
        return self.save("claimant_guarantees", figure)

    def method_tradeoff(self, analysis: dict[str, Any], language: str = DEFAULT_LANGUAGE) -> Path:
        figure, axis = plt.subplots(figsize=(9.2, 4.8))
        for index, row in enumerate(analysis["method_comparison"]):
            axis.scatter(
                row["nominal_beneficial_delivery_af"],
                row["minimum_guarantee"],
                s=60,
                color=PALETTE[index % len(PALETTE)],
                label=row["method"],
                zorder=3,
            )
            axis.annotate(
                row["method"],
                (row["nominal_beneficial_delivery_af"], row["minimum_guarantee"]),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=7.5,
            )
        axis.set_xlabel(
            pick(language, "Номинал фойдали етказиш (acre-ft)", "Nominal beneficial delivery (acre-ft)")
        )
        axis.set_ylabel(pick(language, "Минимал робаст кафолат", "Minimum robust guarantee"))
        axis.set_title(
            pick(language, "Самарадорлик–адолат таққосланиши", "Efficiency–fairness comparison")
        )
        axis.legend(frameon=False, ncol=2, fontsize=7.5)
        figure.tight_layout()
        return self.save("method_tradeoff", figure)

    def recourse_frontier(
        self, raw: dict[str, Any], analysis: dict[str, Any], language: str = DEFAULT_LANGUAGE
    ) -> Path:
        frontier = analysis["recourse_frontier"]
        claimant_ids = list(frontier[0]["guarantees"]) if frontier else []
        names = {
            row["claimant_id"]: row.get("claimant_name", row["claimant_id"])
            for row in raw.get("claimants", [])
        }
        scales = [row["budget_scale"] for row in frontier]
        figure, (left, right) = plt.subplots(1, 2, figsize=(9.2, 4.2))
        for index, claimant in enumerate(claimant_ids):
            left.plot(
                scales,
                [row["guarantees"][claimant] for row in frontier],
                marker="o",
                color=PALETTE[index % len(PALETTE)],
                label=names.get(claimant, claimant),
            )
        left.set_xlabel(pick(language, "Қайта мослашув бюджети масштаби", "Recourse-budget scale"))
        left.set_ylabel(pick(language, "Робаст кафолат", "Robust guarantee"))
        left.set_title(pick(language, "Кафолат фронти", "Guarantee frontier"))
        left.legend(frameon=False, fontsize=7.5)
        right.plot(
            scales,
            [row["normalized_recourse_effort"] for row in frontier],
            marker="o",
            color="#0F766E",
        )
        right.set_xlabel(pick(language, "Қайта мослашув бюджети масштаби", "Recourse-budget scale"))
        right.set_ylabel(pick(language, "Нормаллаштирилган сарф", "Normalized effort"))
        right.set_title(pick(language, "Операцион сарф", "Operational effort"))
        figure.tight_layout()
        return self.save("recourse_frontier", figure)

    def service_heatmap(
        self, raw: dict[str, Any], base: dict[str, Any], language: str = DEFAULT_LANGUAGE
    ) -> Path:
        claimants = [row["claimant_id"] for row in raw.get("claimants", [])]
        scenarios = [row["scenario_id"] for row in raw.get("scenarios", [])]
        periods = [row["period_id"] for row in raw.get("periods", [])]
        names = {
            row["claimant_id"]: row.get("claimant_name", row["claimant_id"])
            for row in raw.get("claimants", [])
        }
        scenario_names = {
            row["scenario_id"]: row.get("label", row["scenario_id"])
            for row in raw.get("scenarios", [])
        }
        ratios = base.get("period_service_ratio", {})
        matrix = np.array(
            [
                [float(ratios.get(f"{scenario}|{period}|{claimant}", np.nan)) for period in periods]
                for scenario in scenarios
                for claimant in claimants
            ]
        )
        labels = [
            f"{scenario_names.get(scenario, scenario)} — {names.get(claimant, claimant)}"
            for scenario in scenarios
            for claimant in claimants
        ]
        height = max(4.8, 0.34 * len(labels) + 1.5)
        figure, axis = plt.subplots(figsize=(9.2, height))
        image = axis.imshow(matrix, cmap="YlGnBu", aspect="auto", vmin=0, vmax=max(1.0, np.nanmax(matrix)))
        axis.set_xticks(range(len(periods)), periods, rotation=25, ha="right")
        axis.set_yticks(range(len(labels)), labels, fontsize=7.1)
        axis.set_title(
            pick(language, "Сценарий–давр хизмат нисбатлари", "Scenario–period service ratios")
        )
        for row in range(matrix.shape[0]):
            for column in range(matrix.shape[1]):
                value = matrix[row, column]
                if np.isfinite(value):
                    axis.text(column, row, f"{value:.2f}", ha="center", va="center", fontsize=6.3)
        figure.colorbar(
            image,
            ax=axis,
            label=pick(language, "Етказилган сув / талаб", "Delivered / demand"),
        )
        figure.tight_layout()
        return self.save("service_heatmap", figure)

    def source_balance(self, analysis: dict[str, Any], language: str = DEFAULT_LANGUAGE) -> Path:
        audit = analysis["operational_audit"]
        source_rows = audit["source_activation"]
        balance_rows = audit["scenario_water_balance"]
        scenarios = list(dict.fromkeys(row["scenario_id"] for row in source_rows))
        sources = list(dict.fromkeys(row["source_id"] for row in source_rows))
        names = {
            row["source_id"]: row.get("source_name", row["source_id"])
            for row in source_rows
        }
        scenario_labels = {
            row["scenario_id"]: row.get("scenario_label", row["scenario_id"])
            for row in balance_rows
        }
        lookup = {(row["scenario_id"], row["source_id"]): row for row in source_rows}
        x = np.arange(len(scenarios))
        figure, (left, right) = plt.subplots(1, 2, figsize=(9.2, 4.5))
        bottom = np.zeros(len(scenarios))
        for index, source in enumerate(sources):
            values = np.array(
                [lookup[(scenario, source)]["seasonal_injection_af"] for scenario in scenarios]
            )
            left.bar(x, values, bottom=bottom, color=PALETTE[index % len(PALETTE)], label=names[source])
            bottom += values
        beneficial = {row["scenario_id"]: row["beneficial_delivery_af"] for row in balance_rows}
        left.plot(
            x,
            [beneficial[item] for item in scenarios],
            color="#0F172A",
            marker="o",
            label=pick(language, "Фойдали етказиш", "Beneficial delivery"),
        )
        left.set_xticks(x, [scenario_labels[item] for item in scenarios], rotation=25, ha="right")
        left.set_ylabel(pick(language, "Мавсумий ҳажм (acre-ft)", "Seasonal volume (acre-ft)"))
        left.set_title(pick(language, "Манбалар фаоллиги", "Source activation"))
        left.legend(frameon=False, fontsize=7)
        conveyance = [row["conveyance_loss_af"] for row in balance_rows]
        application = [row["application_loss_af"] for row in balance_rows]
        right.bar(
            x,
            conveyance,
            color="#94A3B8",
            label=pick(language, "Узатиш йўқотиши", "Conveyance loss"),
        )
        right.bar(
            x,
            application,
            bottom=conveyance,
            color="#F59E0B",
            label=pick(language, "Қўллаш йўқотиши", "Application loss"),
        )
        right.set_xticks(x, [scenario_labels[item] for item in scenarios], rotation=25, ha="right")
        right.set_ylabel(pick(language, "Моделланган йўқотиш (acre-ft)", "Modeled loss (acre-ft)"))
        right.set_title(pick(language, "Сув баланси йўқотишлари", "Water-balance losses"))
        right.legend(frameon=False, fontsize=7)
        figure.tight_layout()
        return self.save("source_water_balance", figure)

    def source_ablation(self, analysis: dict[str, Any], language: str = DEFAULT_LANGUAGE) -> Path:
        rows = analysis["source_ablation"]
        labels = [row["disabled_source_name"] for row in rows]
        changes = [100 * row["change_in_minimum_guarantee"] for row in rows]
        figure, axis = plt.subplots(figsize=(9.2, 4.4))
        colors = ["#DC2626" if value < -1e-8 else "#94A3B8" for value in changes]
        axis.barh(np.arange(len(rows)), changes, color=colors)
        axis.set_yticks(np.arange(len(rows)), labels)
        axis.axvline(0, color="#0F172A", linewidth=0.8)
        axis.set_xlabel(
            pick(
                language,
                "Минимал кафолат ўзгариши (фоиз пункт)",
                "Change in minimum guarantee (percentage points)",
            )
        )
        axis.set_title(
            pick(language, "Манба ўчирилгандаги критиклик", "Source criticality under removal")
        )
        figure.tight_layout()
        return self.save("source_ablation", figure)

    def sensitivity(self, analysis: dict[str, Any], language: str = DEFAULT_LANGUAGE) -> Path:
        records = analysis.get("sensitivity", [])
        factors = [
            ("demand_duty_af_per_acre", pick(language, "Сув талаби меъёри", "Demand duty")),
            ("conveyance_loss_multiplier", pick(language, "Йўқотиш кўпайтиргичи", "Loss multiplier")),
            ("source_limit_scale", pick(language, "Манба мавжудлиги", "Source availability")),
            ("recourse_budget_scale", pick(language, "Қайта мослашув бюджети", "Recourse budget")),
        ]
        figure, axes = plt.subplots(2, 2, figsize=(9.2, 6.6))
        if not records:
            for axis in axes.flat:
                axis.set_axis_off()
            figure.text(
                0.5,
                0.5,
                pick(language, "Бу benchmarkда сезгирлик ҳолатлари йўқ", "No sensitivity cases in this benchmark"),
                ha="center",
                va="center",
            )
            return self.save("sensitivity_main_effects", figure)
        for axis, (factor, title) in zip(axes.flat, factors, strict=True):
            groups: dict[float, list[float]] = defaultdict(list)
            for row in records:
                groups[float(row[factor])].append(float(row["minimum_guarantee"]))
            levels = sorted(groups)
            means = [mean(groups[level]) for level in levels]
            lows = [min(groups[level]) for level in levels]
            highs = [max(groups[level]) for level in levels]
            axis.plot(
                levels,
                means,
                marker="o",
                color="#0284C7",
                label=pick(language, "Ўртача", "Mean"),
            )
            axis.fill_between(
                levels,
                lows,
                highs,
                color="#BAE6FD",
                alpha=0.55,
                label=pick(language, "Диапазон", "Range"),
            )
            axis.set_title(title)
            axis.set_xlabel(pick(language, "Омил даражаси", "Factor level"))
            axis.set_ylabel(pick(language, "Минимал кафолат", "Minimum guarantee"))
        axes[0, 0].legend(frameon=False, fontsize=8)
        figure.suptitle(
            pick(
                language,
                "Тўлиқ факторли робастлик: тавсифий асосий таъсирлар",
                "Full-factorial robustness: descriptive main effects",
            ),
            y=1.01,
        )
        figure.tight_layout()
        return self.save("sensitivity_main_effects", figure)

    def scalability(self, analysis: dict[str, Any], language: str = DEFAULT_LANGUAGE) -> Path:
        rows = analysis.get("scalability", [])
        figure, left = plt.subplots(figsize=(9.2, 4.3))
        scenarios = [row["scenario_count"] for row in rows]
        runtimes = [row["median_runtime_seconds"] for row in rows]
        variables = [row["variables"] for row in rows]
        left.plot(
            scenarios,
            runtimes,
            marker="o",
            color="#0284C7",
            label=pick(language, "Медиан ҳисоблаш вақти", "Median runtime"),
        )
        left.set_xlabel(pick(language, "Сценарийлар сони", "Scenario count"))
        left.set_ylabel(pick(language, "Ҳисоблаш вақти (s)", "Runtime (s)"), color="#0284C7")
        right = left.twinx()
        right.plot(
            scenarios,
            variables,
            marker="s",
            color="#D97706",
            label=pick(language, "LP ўзгарувчилари", "LP variables"),
        )
        right.set_ylabel(pick(language, "LP ўзгарувчилари сони", "LP variable count"), color="#D97706")
        left.set_title(pick(language, "Ҳисоблаш масштабланиши", "Computational scalability"))
        figure.tight_layout()
        return self.save("scalability", figure)

    def render_base(
        self, raw: dict[str, Any], base: dict[str, Any], language: str = DEFAULT_LANGUAGE
    ) -> dict[str, Path]:
        return {
            "network": self.network(raw, language),
            "guarantees": self.guarantees(raw, base, language=language),
            "service": self.service_heatmap(raw, base, language),
        }

    def render_full(
        self,
        raw: dict[str, Any],
        analysis: dict[str, Any],
        language: str = DEFAULT_LANGUAGE,
    ) -> dict[str, Path]:
        base = analysis["base_solution"]
        return {
            "network": self.network(raw, language),
            "guarantees": self.guarantees(raw, base, analysis, language),
            "methods": self.method_tradeoff(analysis, language),
            "recourse": self.recourse_frontier(raw, analysis, language),
            "service": self.service_heatmap(raw, base, language),
            "source_balance": self.source_balance(analysis, language),
            "source_ablation": self.source_ablation(analysis, language),
            "sensitivity": self.sensitivity(analysis, language),
            "scalability": self.scalability(analysis, language),
        }
