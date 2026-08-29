from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

# Run from a clone without installing the package: put src/ on the import path first.
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from timing_protocol import REPEATS as TIMING_REPEATS, timed  # noqa: E402
from leximin.dag import (  # noqa: E402
    CTIBenchmark,
    CTIRLexSolution,
    disable_source,
    load_cti_benchmark,
    lp_dimensions,
    scale_benchmark,
    solve_cti_rlex,
    solve_robust_proportional,
    solve_utilitarian_fair,
    subset_scenarios,
)


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
    return max(solution.residuals.values(), default=0.0)


def method_summary(
    method: str,
    scope: str,
    model: CTIBenchmark,
    solution: CTIRLexSolution,
    timing: dict,
) -> dict[str, object]:
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
        **timing,
        "runtime_seconds": timing["median_runtime_seconds"],
        "maximum_lp_residual": maximum_residual(solution),
    }


def operational_audit(
    model: CTIBenchmark,
    solution: CTIRLexSolution,
    raw: dict[str, object],
) -> dict[str, object]:
    sources = {row["source_id"]: row for row in raw["sources"]}
    scenarios = {row["scenario_id"]: row for row in raw["scenarios"]}
    roles_by_source: dict[str, list[str]] = {source: [] for source in model.source_ids}
    for row in raw.get("source_roles", []):
        roles_by_source[row["source_id"]].append(
            f'{row["claimant_id"]}:{row["operational_role"]}'
        )

    source_rows: list[dict[str, object]] = []
    scenario_rows: list[dict[str, object]] = []
    edge_rows: list[dict[str, object]] = []
    group_rows: list[dict[str, object]] = []

    for scenario in model.scenarios:
        total_injection = 0.0
        gross = 0.0
        beneficial = 0.0
        for source in model.source_ids:
            injection = sum(
                solution.source_injection[scenario, period, source]
                for period in model.periods
            )
            limit = model.source_seasonal_limit[scenario, source]
            total_injection += injection
            meta = sources[source]
            source_rows.append(
                {
                    "scenario_id": scenario,
                    "scenario_label": scenarios[scenario]["label"],
                    "source_id": source,
                    "source_name": meta["source_name"],
                    "source_class": meta["source_class"],
                    "operational_roles": roles_by_source[source],
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
                "scenario_label": scenarios[scenario]["label"],
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
        "most_utilized_edges": edge_rows[:15],
        "most_utilized_source_groups": group_rows[:15],
    }


def rigid_model(model: CTIBenchmark) -> CTIBenchmark:
    return scale_benchmark(
        model,
        demand_duty=2.0,
        conveyance_loss_multiplier=1.0,
        source_limit_scale=1.0,
        recourse_budget_scale=0.0,
    )


def read_sensitivity_cases(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def repeated_timed_solve(solver, model: CTIBenchmark, repeats: int) -> tuple[CTIRLexSolution, dict]:
    """Time one solve under the shared protocol of scripts/timing_protocol.py."""

    solution, timing = timed(lambda: solver(model), repeats)
    assert solution is not None
    return solution, timing


def run_sensitivity(
    model: CTIBenchmark, cases: list[dict[str, str]]
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for index, row in enumerate(cases, start=1):
        factors = {
            "demand_duty_af_per_acre": float(row["demand_duty_af_per_acre"]),
            "conveyance_loss_multiplier": float(row["conveyance_loss_multiplier"]),
            "source_limit_scale": float(row["source_limit_scale"]),
            "recourse_budget_scale": float(row["recourse_budget_scale"]),
        }
        scaled = scale_benchmark(
            model,
            demand_duty=factors["demand_duty_af_per_acre"],
            conveyance_loss_multiplier=factors["conveyance_loss_multiplier"],
            source_limit_scale=factors["source_limit_scale"],
            recourse_budget_scale=factors["recourse_budget_scale"],
        )
        solution, timing = timed(lambda: solve_cti_rlex(scaled))
        totals = scenario_delivery_totals(scaled, solution)
        records.append(
            {
                "case_id": row["case_id"],
                "is_base_case": row["is_base_case"].strip().lower() == "true",
                **factors,
                "guarantees": dict(solution.guarantees),
                "minimum_guarantee": min(solution.guarantees.values()),
                "nominal_beneficial_delivery_af": solution.nominal_beneficial_delivery,
                "worst_scenario_beneficial_delivery_af": min(totals.values()),
                "normalized_recourse_effort": solution.normalized_recourse_effort,
                **timing,
                "runtime_seconds": timing["median_runtime_seconds"],
                "maximum_lp_residual": maximum_residual(solution),
            }
        )
        if index == 1 or index % 10 == 0 or index == len(cases):
            print(f"sensitivity={index}/{len(cases)}", flush=True)
    return records


def run_scalability(model: CTIBenchmark, repeats: int = TIMING_REPEATS) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    counts = sorted({1, min(3, len(model.scenarios)), len(model.scenarios)})
    for count in counts:
        scenarios = (model.nominal_scenario,) + tuple(model.contingency_scenarios[: count - 1])
        reduced = subset_scenarios(model, scenarios)
        solution, timing = timed(lambda: solve_cti_rlex(reduced), repeats)
        assert solution is not None
        records.append(
            {
                "scenario_count": count,
                "scenarios": list(scenarios),
                **lp_dimensions(reduced),
                **timing,
                "minimum_guarantee": min(solution.guarantees.values()),
                "maximum_lp_residual": maximum_residual(solution),
            }
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Run journal-oriented CTI-RLex experiments.")
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("--sensitivity-cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    raw = json.loads(args.benchmark.read_text(encoding="utf-8"))
    model = load_cti_benchmark(args.benchmark)

    method_runs: list[tuple[str, str, CTIBenchmark, object]] = [
        # UTIL-BR is reported after the fairness-optimistic tie-break described in
        # Section 2.9: the delivery optimum is fixed first, and the plan with the
        # highest common floor among the delivery-optimal plans is selected, so the
        # reported guarantee is a property of the objective and not of the pivot rule.
        ("UTIL-BR", "five-scenario bounded recourse", model, solve_utilitarian_fair),
        ("PROP-BR", "five-scenario common robust floor", model, solve_robust_proportional),
        ("CTI-RLex rigid", "five-scenario zero recourse", rigid_model(model), solve_cti_rlex),
        ("CTI-RLex proposed", "five-scenario bounded recourse", model, solve_cti_rlex),
        (
            "CTI-RLex nominal only",
            "nominal scenario only",
            subset_scenarios(model, (model.nominal_scenario,)),
            solve_cti_rlex,
        ),
    ]
    methods: list[dict[str, object]] = []
    solutions: dict[str, CTIRLexSolution] = {}
    method_runtime_repeats = TIMING_REPEATS
    for method, scope, item_model, solver in method_runs:
        solution, timing = repeated_timed_solve(solver, item_model, method_runtime_repeats)
        solutions[method] = solution
        methods.append(method_summary(method, scope, item_model, solution, timing))
        print(f"method={method} runtime={timing['median_runtime_seconds']:.4f}s", flush=True)

    proposed = solutions["CTI-RLex proposed"]
    proposed_summary = next(row for row in methods if row["method"] == "CTI-RLex proposed")
    rigid_summary = next(row for row in methods if row["method"] == "CTI-RLex rigid")
    util_summary = next(row for row in methods if row["method"] == "UTIL-BR")

    ablation: list[dict[str, object]] = []
    for source in model.sources:
        ablated = disable_source(model, source.source_id)
        solution, timing = timed(lambda: solve_cti_rlex(ablated))
        totals = scenario_delivery_totals(ablated, solution)
        ablation.append(
            {
                "disabled_source_id": source.source_id,
                "disabled_source_class": source.source_class,
                "minimum_guarantee": min(solution.guarantees.values()),
                "change_in_minimum_guarantee": (
                    min(solution.guarantees.values()) - proposed_summary["minimum_guarantee"]
                ),
                "nominal_beneficial_delivery_af": solution.nominal_beneficial_delivery,
                "change_in_nominal_delivery_af": (
                    solution.nominal_beneficial_delivery
                    - proposed_summary["nominal_beneficial_delivery_af"]
                ),
                "worst_scenario_beneficial_delivery_af": min(totals.values()),
                **timing,
                "runtime_seconds": timing["median_runtime_seconds"],
                "maximum_lp_residual": maximum_residual(solution),
            }
        )
        print(f"ablation={source.source_id}", flush=True)

    sensitivity = run_sensitivity(model, read_sensitivity_cases(args.sensitivity_cases))
    payload = {
        "benchmark_id": model.benchmark_id,
        "experiment_design": {
            "methods": [row["method"] for row in methods],
            "sensitivity_case_count": len(sensitivity),
            "sensitivity_design": "3x3x3x5 full factorial",
            "method_runtime_repeats": method_runtime_repeats,
            "scalability_runtime_repeats": 3,
        },
        "method_comparison": methods,
        "derived_indicators": {
            "price_of_fairness_nominal_fraction": 1.0
            - proposed_summary["nominal_beneficial_delivery_af"]
            / util_summary["nominal_beneficial_delivery_af"],
            "value_of_recourse_minimum_guarantee_absolute": (
                proposed_summary["minimum_guarantee"] - rigid_summary["minimum_guarantee"]
            ),
            "value_of_recourse_minimum_guarantee_percent": 100.0
            * (
                proposed_summary["minimum_guarantee"]
                / rigid_summary["minimum_guarantee"]
                - 1.0
            ),
        },
        "operational_audit": operational_audit(model, proposed, raw),
        "source_ablation": ablation,
        "sensitivity": sensitivity,
        "scalability": run_scalability(model),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"results={args.output.resolve()}", flush=True)


if __name__ == "__main__":
    main()
