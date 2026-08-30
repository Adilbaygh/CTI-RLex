"""Benchmark and serializable-result adapters used by the standalone GUI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from .i18n import DEFAULT_LANGUAGE, pick


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    root: Path
    default_benchmark: Path

    @classmethod
    def from_root(cls, root: Path) -> "ProjectPaths":
        resolved = root.resolve()
        return cls(
            root=resolved,
            default_benchmark=(
                resolved / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json"
            ),
        )


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def project_version(root: Path) -> str:
    """The release version, read from CITATION.cff.

    The GUI, the citation file and the archived release name one and the same software, so
    the version is read from the file that the release carries rather than repeated in the
    code, where it would drift away at the next release.
    """

    try:
        for line in (root / "CITATION.cff").read_text(encoding="utf-8").splitlines():
            if line.startswith("version:"):
                return line.split(":", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return "unreleased"


def validate_benchmark_document(raw: dict[str, Any], language: str = DEFAULT_LANGUAGE) -> None:
    required = {
        "benchmark_id",
        "claimants",
        "claimant_terminals",
        "nodes",
        "edges",
        "sources",
        "periods",
        "scenarios",
        "demands",
        "edge_parameters",
        "source_limits",
        "terminal_parameters",
    }
    missing = sorted(required.difference(raw))
    if missing:
        raise ValueError(
            pick(
                language,
                "Benchmark майдонлари етишмайди: ",
                "Required benchmark fields are missing: ",
            )
            + ", ".join(missing)
        )
    if not raw["benchmark_id"]:
        raise ValueError(
            pick(
                language,
                "benchmark_id бўш бўлиши мумкин эмас.",
                "benchmark_id must not be empty.",
            )
        )


def load_benchmark_document(path: Path, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
    raw = read_json(path)
    validate_benchmark_document(raw, language)
    return raw


def benchmark_counts(raw: dict[str, Any]) -> dict[str, int]:
    return {
        "claimants": len(raw.get("claimants", [])),
        "terminals": len(raw.get("claimant_terminals", [])),
        "sources": len(raw.get("sources", [])),
        "nodes": len(raw.get("nodes", [])),
        "edges": len(raw.get("edges", [])),
        "periods": len(raw.get("periods", [])),
        "scenarios": len(raw.get("scenarios", [])),
        "controls": len(raw.get("control_assets", [])),
        "sensitivity": len(raw.get("sensitivity_cases", [])),
    }


def rows_from_dicts(
    records: Iterable[dict[str, Any]],
    columns: list[tuple[str, str]],
) -> tuple[list[str], list[list[Any]]]:
    materialized = list(records)
    return (
        [label for _key, label in columns],
        [[record.get(key, "") for key, _label in columns] for record in materialized],
    )


def claimant_table(
    raw: dict[str, Any], language: str = DEFAULT_LANGUAGE
) -> tuple[list[str], list[list[Any]]]:
    return rows_from_dicts(
        raw.get("claimants", []),
        [
            ("claimant_id", pick(language, "Талабгор ID", "Claimant ID")),
            ("claimant_name", pick(language, "Номи", "Name")),
            (
                "irrigated_demand_acres",
                pick(language, "Суғориладиган майдон (acre)", "Irrigated area (acre)"),
            ),
            ("assigned_wrlu_polygons", pick(language, "WRLU полигони", "WRLU polygon")),
            ("subarea", pick(language, "Қуйи ҳудуд", "Subarea")),
            ("water_rights_text", pick(language, "Сув ҳуқуқлари", "Water rights")),
        ],
    )


def source_table(
    raw: dict[str, Any], language: str = DEFAULT_LANGUAGE
) -> tuple[list[str], list[list[Any]]]:
    return rows_from_dicts(
        raw.get("sources", []),
        [
            ("source_id", pick(language, "Манба ID", "Source ID")),
            ("source_name", pick(language, "Манба номи", "Source name")),
            ("source_class", pick(language, "Класси", "Class")),
            ("node_id", pick(language, "Тугун", "Node")),
            ("design_envelope_cfs", pick(language, "Чегара (cfs)", "Envelope (cfs)")),
            ("limit_status", pick(language, "Маълумот ҳолати", "Data status")),
        ],
    )


def scenario_table(
    raw: dict[str, Any], language: str = DEFAULT_LANGUAGE
) -> tuple[list[str], list[list[Any]]]:
    return rows_from_dicts(
        raw.get("scenarios", []),
        [
            ("scenario_id", pick(language, "Сценарий ID", "Scenario ID")),
            ("label", pick(language, "Номи", "Name")),
            ("probability_weight", pick(language, "Вазн", "Weight")),
            ("recourse_budget", pick(language, "Қайта мослашув бюджети", "Recourse budget")),
            ("description", pick(language, "Тавсиф", "Description")),
        ],
    )


def flatten_mapping_table(
    mapping: dict[str, Any], key_labels: list[str], value_label: str
) -> tuple[list[str], list[list[Any]]]:
    rows = [[*compound_key.split("|"), value] for compound_key, value in mapping.items()]
    return [*key_labels, value_label], rows


def base_result_tables(
    base: dict[str, Any], language: str = DEFAULT_LANGUAGE
) -> dict[str, tuple[list[str], list[list[Any]]]]:
    return {
        pick(language, "Кафолатлар", "Guarantees"): (
            [pick(language, "Талабгор", "Claimant"), pick(language, "Робаст кафолат", "Robust guarantee")],
            [[key, value] for key, value in base.get("guarantees", {}).items()],
        ),
        pick(language, "Мақсад функциялари", "Objectives"): (
            [pick(language, "Мақсад функцияси", "Objective"), pick(language, "Қиймат", "Value")],
            [[key, value] for key, value in base.get("objectives", {}).items()],
        ),
        pick(language, "LP қолдиқлари", "LP residuals"): (
            [pick(language, "Қолдиқ", "Residual"), pick(language, "Қиймат", "Value")],
            [[key, value] for key, value in base.get("residuals", {}).items()],
        ),
        pick(language, "Қайта мослашув", "Recourse"): (
            [pick(language, "Сценарий", "Scenario"), pick(language, "Нормаллаштирилган сарф", "Normalized effort")],
            [[key, value] for key, value in base.get("recourse_by_scenario", {}).items()],
        ),
        pick(language, "Мавсумий нисбатлар", "Seasonal ratios"): flatten_mapping_table(
            base.get("seasonal_service_ratio", {}),
            [pick(language, "Сценарий", "Scenario"), pick(language, "Талабгор", "Claimant")],
            pick(language, "Мавсумий нисбат", "Seasonal ratio"),
        ),
        pick(language, "Ойлик нисбатлар", "Period ratios"): flatten_mapping_table(
            base.get("period_service_ratio", {}),
            [pick(language, "Сценарий", "Scenario"), pick(language, "Давр", "Period"), pick(language, "Талабгор", "Claimant")],
            pick(language, "Хизмат нисбати", "Service ratio"),
        ),
        pick(language, "Манба оқимлари", "Source injections"): flatten_mapping_table(
            base.get("source_injection_af", {}),
            [pick(language, "Сценарий", "Scenario"), pick(language, "Давр", "Period"), pick(language, "Манба", "Source")],
            pick(language, "Оқим (acre-ft)", "Injection (acre-ft)"),
        ),
        pick(language, "Тармоқ оқимлари", "Network flows"): flatten_mapping_table(
            base.get("edge_flow_af", {}),
            [pick(language, "Сценарий", "Scenario"), pick(language, "Давр", "Period"), pick(language, "Қирра", "Edge")],
            pick(language, "Оқим (acre-ft)", "Flow (acre-ft)"),
        ),
        pick(language, "Фойдали етказиш", "Beneficial delivery"): flatten_mapping_table(
            base.get("beneficial_delivery_af", {}),
            [pick(language, "Сценарий", "Scenario"), pick(language, "Давр", "Period"), pick(language, "Терминал", "Terminal")],
            pick(language, "Фойдали етказиш (acre-ft)", "Beneficial delivery (acre-ft)"),
        ),
    }


def allocation_table(
    raw: dict[str, Any], base: dict[str, Any], language: str = DEFAULT_LANGUAGE
) -> tuple[list[str], list[list[Any]]]:
    names = {
        row["claimant_id"]: row.get("claimant_name", row["claimant_id"])
        for row in raw.get("claimants", [])
    }
    demand: dict[str, float] = {key: 0.0 for key in names}
    for row in raw.get("demands", []):
        demand[row["claimant_id"]] = demand.get(row["claimant_id"], 0.0) + float(
            row["demand_af"]
        )
    application: dict[str, list[float]] = {key: [] for key in names}
    for row in raw.get("terminal_parameters", []):
        application.setdefault(row["claimant_id"], []).append(
            float(row["application_efficiency"])
        )
    guarantees = base.get("guarantees", {})
    period_ratios = base.get("period_service_ratio", {})
    seasonal = base.get("seasonal_service_ratio", {})
    rows: list[list[Any]] = []
    for claimant, guarantee in guarantees.items():
        values = application.get(claimant, [])
        ratios = [
            float(value)
            for key, value in period_ratios.items()
            if key.endswith("|" + claimant)
        ]
        binding = sum(abs(value - float(guarantee)) <= 1e-7 for value in ratios)
        seasonal_values = [
            float(value)
            for key, value in seasonal.items()
            if key.endswith("|" + claimant)
        ]
        rows.append(
            [
                claimant,
                names.get(claimant, claimant),
                demand.get(claimant, 0.0),
                mean(values) if values else 0.0,
                guarantee,
                min(seasonal_values) if seasonal_values else 0.0,
                binding,
            ]
        )
    return (
        [
            pick(language, "Талабгор ID", "Claimant ID"),
            pick(language, "Номи", "Name"),
            pick(language, "Мавсумий талаб (acre-ft)", "Seasonal demand (acre-ft)"),
            pick(language, "Қўллаш самарадорлиги", "Application efficiency"),
            pick(language, "Робаст кафолат", "Robust guarantee"),
            pick(language, "Энг ёмон мавсумий нисбат", "Worst seasonal ratio"),
            pick(language, "Боғловчи катаклар", "Binding cells"),
        ],
        rows,
    )


def method_table(
    analysis: dict[str, Any], language: str = DEFAULT_LANGUAGE
) -> tuple[list[str], list[list[Any]]]:
    return rows_from_dicts(
        analysis.get("method_comparison", []),
        [
            ("method", pick(language, "Усул", "Method")),
            ("guarantee_scope", pick(language, "Қамров", "Scope")),
            ("minimum_guarantee", pick(language, "Минимал кафолат", "Minimum guarantee")),
            ("jain_guarantee_index", pick(language, "Jain индекси", "Jain index")),
            ("nominal_beneficial_delivery_af", pick(language, "Номинал етказиш (acre-ft)", "Nominal delivery (acre-ft)")),
            ("worst_scenario_beneficial_delivery_af", pick(language, "Энг ёмон етказиш (acre-ft)", "Worst delivery (acre-ft)")),
            ("normalized_recourse_effort", pick(language, "Қайта мослашув сарфи", "Recourse effort")),
            ("runtime_seconds", pick(language, "Ҳисоблаш вақти (s)", "Runtime (s)")),
        ],
    )


def recourse_table(
    raw: dict[str, Any], analysis: dict[str, Any], language: str = DEFAULT_LANGUAGE
) -> tuple[list[str], list[list[Any]]]:
    claimant_ids = [row["claimant_id"] for row in raw.get("claimants", [])]
    headers = [
        pick(language, "Бюджет масштаби", "Budget scale"),
        pick(language, "Минимал кафолат", "Minimum guarantee"),
        *claimant_ids,
        pick(language, "Қайта мослашув сарфи", "Recourse effort"),
        pick(language, "Ҳисоблаш вақти (s)", "Runtime (s)"),
    ]
    rows = []
    for record in analysis.get("recourse_frontier", []):
        rows.append(
            [
                record["budget_scale"],
                record["first_leximin_level"],
                *[record["guarantees"].get(key, "") for key in claimant_ids],
                record["normalized_recourse_effort"],
                record["runtime_seconds"],
            ]
        )
    return headers, rows


def sensitivity_main_effects(
    analysis: dict[str, Any], language: str = DEFAULT_LANGUAGE
) -> tuple[list[str], list[list[Any]]]:
    factors = [
        "demand_duty_af_per_acre",
        "conveyance_loss_multiplier",
        "source_limit_scale",
        "recourse_budget_scale",
    ]
    records = analysis.get("sensitivity", [])
    rows: list[list[Any]] = []
    for factor in factors:
        levels = sorted({float(row[factor]) for row in records})
        for level in levels:
            values = [
                float(row["minimum_guarantee"])
                for row in records
                if float(row[factor]) == level
            ]
            rows.append([factor, level, len(values), mean(values), min(values), max(values)])
    return [
        pick(language, "Омил", "Factor"),
        pick(language, "Даража", "Level"),
        pick(language, "Ҳолатлар", "Cases"),
        pick(language, "Ўртача", "Mean"),
        pick(language, "Минимум", "Minimum"),
        pick(language, "Максимум", "Maximum"),
    ], rows


def sensitivity_range(analysis: dict[str, Any]) -> tuple[float, float, int]:
    values = [float(row["minimum_guarantee"]) for row in analysis.get("sensitivity", [])]
    return (min(values), max(values), len(values)) if values else (0.0, 0.0, 0)
