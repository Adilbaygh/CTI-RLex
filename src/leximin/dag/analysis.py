"""Benchmark-driven effectiveness and robustness analysis for CTI-RLex.

This module is part of the reusable solver library.  It deliberately has no knowledge
of manuscripts, project working folders, or pre-generated result files.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from statistics import median
from time import perf_counter
from typing import Any

from .domain import CTIBenchmark
from .experiments import (
    disable_source,
    lp_dimensions,
    scale_benchmark,
    solve_robust_proportional,
    solve_utilitarian,
    subset_scenarios,
    timed_solve,
)
from .solver import CTIRLexSolution, solve_cti_rlex
from .verification import split_terminal_record


ProgressCallback = Callable[[int, int, str], None]
CancelCallback = Callable[[], bool]


class AnalysisCancelled(RuntimeError):
    """Raised at safe solve boundaries when a user cancels a long analysis."""


def _notify(
    callback: ProgressCallback | None,
    current: int,
    total: int,
    message: str,
) -> None:
    if callback is not None:
        callback(current, total, message)


def _check_cancelled(callback: CancelCallback | None) -> None:
    if callback is not None and callback():
        raise AnalysisCancelled("Analysis cancelled by the user.")


def jain_index(values: list[float]) -> float:
    denominator = len(values) * sum(value * value for value in values)
    return sum(values) ** 2 / denominator if denominator else 1.0


def scenario_delivery_totals(
    model: CTIBenchmark, solution: CTIRLexSolution
) -> dict[str, float]:
    return {
        scenario: sum(
            value
            for (item_scenario, _period, _terminal), value in solution.beneficial_delivery.items()
            if item_scenario == scenario
        )
        for scenario in model.scenarios
    }


def maximum_residual(solution: CTIRLexSolution) -> float:
    return max((abs(value) for value in solution.residuals.values()), default=0.0)


def method_summary(
    method: str,
    scope: str,
    model: CTIBenchmark,
    solution: CTIRLexSolution,
    runtime_seconds: float,
) -> dict[str, Any]:
    totals = scenario_delivery_totals(model, solution)
    guarantees = dict(solution.guarantees)
    return {
        "method": method,
        "guarantee_scope": scope,
        "guarantees": guarantees,
        "leximin_vector": sorted(guarantees.values()),
        "minimum_guarantee": min(guarantees.values()),
        "jain_guarantee_index": jain_index(list(guarantees.values())),
        "nominal_beneficial_delivery_af": solution.nominal_beneficial_delivery,
        "weighted_contingency_beneficial_delivery_af": (
            solution.weighted_contingency_beneficial_delivery
        ),
        "scenario_beneficial_delivery_af": totals,
        "worst_scenario_beneficial_delivery_af": min(totals.values()),
        "normalized_recourse_effort": solution.normalized_recourse_effort,
        "runtime_seconds": runtime_seconds,
        "maximum_lp_residual": maximum_residual(solution),
    }


def operational_audit(
    model: CTIBenchmark,
    solution: CTIRLexSolution,
    raw: dict[str, Any],
) -> dict[str, Any]:
    source_metadata = {row["source_id"]: row for row in raw.get("sources", [])}
    scenario_metadata = {row["scenario_id"]: row for row in raw.get("scenarios", [])}
    roles_by_source: dict[str, list[str]] = {source: [] for source in model.source_ids}
    for row in raw.get("source_roles", []):
        roles_by_source.setdefault(row["source_id"], []).append(
            f'{row.get("claimant_id", "")}:{row.get("operational_role", "")}'
        )

    source_rows: list[dict[str, Any]] = []
    scenario_rows: list[dict[str, Any]] = []
    edge_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []
    for scenario in model.scenarios:
        total_injection = 0.0
        for source in model.source_ids:
            injection = sum(
                solution.source_injection[scenario, period, source]
                for period in model.periods
            )
            limit = model.source_seasonal_limit[scenario, source]
            total_injection += injection
            meta = source_metadata.get(source, {})
            source_rows.append(
                {
                    "scenario_id": scenario,
                    "scenario_label": scenario_metadata.get(scenario, {}).get("label", scenario),
                    "source_id": source,
                    "source_name": meta.get("source_name", source),
                    "source_class": meta.get("source_class", "unknown"),
                    "operational_roles": roles_by_source.get(source, []),
                    "seasonal_injection_af": injection,
                    "seasonal_limit_af": limit,
                    "seasonal_utilization": injection / limit if limit > 0 else 0.0,
                }
            )
        gross = sum(
            value
            for (item_scenario, _period, _terminal), value in solution.gross_terminal_withdrawal.items()
            if item_scenario == scenario
        )
        beneficial = sum(
            value
            for (item_scenario, _period, _terminal), value in solution.beneficial_delivery.items()
            if item_scenario == scenario
        )
        scenario_rows.append(
            {
                "scenario_id": scenario,
                "scenario_label": scenario_metadata.get(scenario, {}).get("label", scenario),
                "source_injection_af": total_injection,
                "gross_terminal_withdrawal_af": gross,
                "beneficial_delivery_af": beneficial,
                "conveyance_loss_af": max(0.0, total_injection - gross),
                "application_loss_af": max(0.0, gross - beneficial),
                "end_to_end_efficiency": beneficial / total_injection if total_injection else 1.0,
                "recourse_effort": solution.recourse_by_scenario.get(scenario, 0.0),
                "recourse_budget": model.recourse_budget[scenario],
            }
        )
        for period in model.periods:
            for edge in model.edge_ids:
                flow = solution.edge_flow[scenario, period, edge]
                capacity = model.edge_capacity[scenario, period, edge]
                edge_rows.append(
                    {
                        "scenario_id": scenario,
                        "period_id": period,
                        "edge_id": edge,
                        "flow_af": flow,
                        "capacity_af": capacity,
                        "utilization": flow / capacity if capacity > 0 else 0.0,
                    }
                )
            for group in model.source_groups:
                use = sum(
                    beta * solution.source_injection[scenario, period, source]
                    for source, beta in model.group_members[group]
                )
                limit = model.shared_source_limit[scenario, period, group]
                group_rows.append(
                    {
                        "scenario_id": scenario,
                        "period_id": period,
                        "group_id": group,
                        "weighted_use_af": use,
                        "limit_af": limit,
                        "utilization": use / limit if limit > 0 else 0.0,
                    }
                )
    edge_rows.sort(key=lambda row: row["utilization"], reverse=True)
    group_rows.sort(key=lambda row: row["utilization"], reverse=True)
    return {
        "source_activation": source_rows,
        "scenario_water_balance": scenario_rows,
        "most_utilized_edges": edge_rows[: min(20, len(edge_rows))],
        "most_utilized_source_groups": group_rows[: min(20, len(group_rows))],
    }


def _repeated_solve(solver, model: CTIBenchmark, repeats: int) -> tuple[CTIRLexSolution, float]:
    runtimes: list[float] = []
    solution: CTIRLexSolution | None = None
    for _ in range(repeats):
        solution, runtime = timed_solve(solver, model)
        runtimes.append(runtime)
    assert solution is not None
    return solution, median(runtimes)


def _sensitivity_model(model: CTIBenchmark, row: dict[str, Any]) -> CTIBenchmark:
    required = (
        "demand_duty_af_per_acre",
        "conveyance_loss_multiplier",
        "source_limit_scale",
        "recourse_budget_scale",
    )
    missing = [key for key in required if key not in row]
    if missing:
        raise ValueError("Sensitivity case fields missing: " + ", ".join(missing))
    return scale_benchmark(
        model,
        demand_duty=float(row["demand_duty_af_per_acre"]),
        conveyance_loss_multiplier=float(row["conveyance_loss_multiplier"]),
        source_limit_scale=float(row["source_limit_scale"]),
        recourse_budget_scale=float(row["recourse_budget_scale"]),
    )


def run_full_analysis(
    model: CTIBenchmark,
    raw: dict[str, Any],
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
    runtime_repeats: int = 3,
) -> dict[str, Any]:
    """Compute solver effectiveness, robustness, and numerical diagnostics.

    The returned mapping is fully serializable and can be exported by any client.
    Sensitivity coordinates are taken directly from the benchmark document.
    """

    sensitivity_cases = list(raw.get("sensitivity_cases", []))
    total_steps = 5 + len(model.sources) + 5 + len(sensitivity_cases) + 3
    step = 0

    def advance(message: str) -> None:
        nonlocal step
        step += 1
        _notify(progress, step, total_steps, message)

    _check_cancelled(cancelled)
    method_runs = [
        ("Utilitarian", "all scenarios, bounded recourse", model, solve_utilitarian),
        (
            "Robust proportional",
            "all scenarios, common robust floor",
            model,
            solve_robust_proportional,
        ),
        (
            "CTI-RLex rigid",
            "all scenarios, zero recourse",
            replace(model, recourse_budget={key: 0.0 for key in model.scenarios}),
            solve_cti_rlex,
        ),
        ("CTI-RLex proposed", "all scenarios, bounded recourse", model, solve_cti_rlex),
        (
            "CTI-RLex nominal only",
            "nominal scenario only",
            subset_scenarios(model, (model.nominal_scenario,)),
            solve_cti_rlex,
        ),
    ]
    methods: list[dict[str, Any]] = []
    solutions: dict[str, CTIRLexSolution] = {}
    for method, scope, item_model, solver in method_runs:
        _check_cancelled(cancelled)
        solution, runtime = _repeated_solve(solver, item_model, runtime_repeats)
        methods.append(method_summary(method, scope, item_model, solution, runtime))
        solutions[method] = solution
        advance(f"Method completed: {method}")

    proposed = solutions["CTI-RLex proposed"]
    by_method = {row["method"]: row for row in methods}
    proposed_summary = by_method["CTI-RLex proposed"]
    rigid_summary = by_method["CTI-RLex rigid"]
    utilitarian_summary = by_method["Utilitarian"]

    ablation: list[dict[str, Any]] = []
    source_meta = {row["source_id"]: row for row in raw.get("sources", [])}
    for source in model.source_ids:
        _check_cancelled(cancelled)
        ablated = disable_source(model, source)
        solution, runtime = timed_solve(solve_cti_rlex, ablated)
        totals = scenario_delivery_totals(ablated, solution)
        ablation.append(
            {
                "disabled_source_id": source,
                "disabled_source_name": source_meta.get(source, {}).get("source_name", source),
                "disabled_source_class": source_meta.get(source, {}).get("source_class", "unknown"),
                "minimum_guarantee": min(solution.guarantees.values()),
                "change_in_minimum_guarantee": (
                    min(solution.guarantees.values())
                    - proposed_summary["minimum_guarantee"]
                ),
                "nominal_beneficial_delivery_af": solution.nominal_beneficial_delivery,
                "change_in_nominal_delivery_af": (
                    solution.nominal_beneficial_delivery
                    - proposed_summary["nominal_beneficial_delivery_af"]
                ),
                "worst_scenario_beneficial_delivery_af": min(totals.values()),
                "runtime_seconds": runtime,
                "maximum_lp_residual": maximum_residual(solution),
            }
        )
        advance(f"Source ablation completed: {source}")

    frontier: list[dict[str, Any]] = []
    for scale in (0.0, 0.25, 0.5, 1.0, 2.0):
        _check_cancelled(cancelled)
        scaled = replace(
            model,
            recourse_budget={key: value * scale for key, value in model.recourse_budget.items()},
        )
        solution, runtime = timed_solve(solve_cti_rlex, scaled)
        frontier.append(
            {
                "budget_scale": scale,
                "first_leximin_level": solution.first_leximin_level,
                "guarantees": dict(solution.guarantees),
                "normalized_recourse_effort": solution.normalized_recourse_effort,
                "runtime_seconds": runtime,
            }
        )
        advance(f"Recourse frontier completed: scale {scale:g}")

    sensitivity: list[dict[str, Any]] = []
    for index, row in enumerate(sensitivity_cases, start=1):
        _check_cancelled(cancelled)
        scaled = _sensitivity_model(model, row)
        solution, runtime = timed_solve(solve_cti_rlex, scaled)
        totals = scenario_delivery_totals(scaled, solution)
        sensitivity.append(
            {
                "case_id": row.get("case_id", f"case_{index:04d}"),
                "is_base_case": str(row.get("is_base_case", "false")).lower() == "true",
                "demand_duty_af_per_acre": float(row["demand_duty_af_per_acre"]),
                "conveyance_loss_multiplier": float(row["conveyance_loss_multiplier"]),
                "source_limit_scale": float(row["source_limit_scale"]),
                "recourse_budget_scale": float(row["recourse_budget_scale"]),
                "guarantees": dict(solution.guarantees),
                "minimum_guarantee": min(solution.guarantees.values()),
                "nominal_beneficial_delivery_af": solution.nominal_beneficial_delivery,
                "worst_scenario_beneficial_delivery_af": min(totals.values()),
                "normalized_recourse_effort": solution.normalized_recourse_effort,
                "runtime_seconds": runtime,
                "maximum_lp_residual": maximum_residual(solution),
            }
        )
        advance(f"Sensitivity case {index}/{len(sensitivity_cases)}")

    _check_cancelled(cancelled)
    base = proposed.to_dict()
    terminal_id = model.terminals[0].terminal_id
    representation: list[dict[str, Any]] = []
    for copies in (2, 4, 8):
        split = solve_cti_rlex(split_terminal_record(model, terminal_id, copies))
        error = max(
            abs(proposed.guarantees[claimant] - split.guarantees[claimant])
            for claimant in model.claimants
        )
        representation.append(
            {
                "terminal_id": terminal_id,
                "copies": copies,
                "guarantee_infinity_norm_error": error,
                "pass_at_1e-8": error <= 1e-8,
            }
        )
    advance("Terminal representation invariance completed")

    scalability: list[dict[str, Any]] = []
    counts = sorted({1, min(3, len(model.scenarios)), len(model.scenarios)})
    for count in counts:
        scenarios = (model.nominal_scenario,) + tuple(model.contingency_scenarios[: count - 1])
        reduced = subset_scenarios(model, scenarios)
        runtimes: list[float] = []
        solution: CTIRLexSolution | None = None
        for _ in range(runtime_repeats):
            started = perf_counter()
            solution = solve_cti_rlex(reduced)
            runtimes.append(perf_counter() - started)
        assert solution is not None
        scalability.append(
            {
                "scenario_count": count,
                "scenarios": list(scenarios),
                **lp_dimensions(reduced),
                "runtime_seconds_repeats": runtimes,
                "median_runtime_seconds": median(runtimes),
                "minimum_guarantee": min(solution.guarantees.values()),
                "maximum_lp_residual": maximum_residual(solution),
            }
        )
    advance("Scalability audit completed")

    indicators = {
        "price_of_fairness_nominal_fraction": 1.0
        - proposed_summary["nominal_beneficial_delivery_af"]
        / utilitarian_summary["nominal_beneficial_delivery_af"],
        "value_of_recourse_minimum_guarantee_absolute": (
            proposed_summary["minimum_guarantee"] - rigid_summary["minimum_guarantee"]
        ),
        "value_of_recourse_minimum_guarantee_percent": 100.0
        * (
            proposed_summary["minimum_guarantee"]
            / rigid_summary["minimum_guarantee"]
            - 1.0
        )
        if rigid_summary["minimum_guarantee"] > 0
        else float("inf"),
    }
    advance("Effectiveness indicators completed")
    return {
        "analysis_schema": "cti-rlex-analysis-v1",
        "benchmark_id": model.benchmark_id,
        "base_solution": base,
        "configuration": {
            "runtime_repeats": runtime_repeats,
            "sensitivity_case_count": len(sensitivity),
            "methods": [row["method"] for row in methods],
        },
        "method_comparison": methods,
        "effectiveness_indicators": indicators,
        "operational_audit": operational_audit(model, proposed, raw),
        "source_ablation": ablation,
        "recourse_frontier": frontier,
        "sensitivity": sensitivity,
        "representation_tests": representation,
        "scalability": scalability,
        "base_residuals": dict(proposed.residuals),
    }
