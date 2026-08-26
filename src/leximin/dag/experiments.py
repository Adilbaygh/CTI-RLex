from __future__ import annotations

from dataclasses import replace
from time import perf_counter
from typing import Iterable, Mapping

from .domain import CTIBenchmark
from .lp import LPData, VariableKey, build_lp, objective_value, run_lp, value
from .solver import CTIRLexSolution, LeximinLevel, _extract_solution


def nominal_delivery_objective(model: CTIBenchmark) -> dict[VariableKey, float]:
    return {
        ("x", model.nominal_scenario, period, terminal.terminal_id): 1.0
        for period in model.periods
        for terminal in model.terminals
    }


def contingency_delivery_objective(model: CTIBenchmark) -> dict[VariableKey, float]:
    return {
        ("x", scenario, period, terminal.terminal_id): model.scenario_weight[scenario]
        for scenario in model.contingency_scenarios
        for period in model.periods
        for terminal in model.terminals
    }


def recourse_objective(model: CTIBenchmark) -> dict[VariableKey, float]:
    return {
        ("u", scenario, period, asset.asset_id): asset.effort_coefficient
        for scenario in model.contingency_scenarios
        for period in model.periods
        for asset in model.controls
    }


def realized_guarantees(model: CTIBenchmark, problem: LPData, result) -> dict[str, float]:
    guarantees: dict[str, float] = {}
    for claimant, terminals in model.terminals_by_claimant.items():
        ratios: list[float] = []
        for scenario in model.scenarios:
            for period in model.periods:
                demand = model.demand[period, claimant]
                if demand <= 0:
                    continue
                delivery = sum(
                    value(problem, result, ("x", scenario, period, terminal.terminal_id))
                    for terminal in terminals
                )
                ratios.append(delivery / demand)
        guarantees[claimant] = min(ratios, default=1.0)
    return guarantees


def _preservation_row(
    objective: Mapping[VariableKey, float], optimum: float, tolerance: float
) -> tuple[dict[VariableKey, float], float]:
    floor = optimum - tolerance * max(1.0, abs(optimum))
    return ({key: -coefficient for key, coefficient in objective.items()}, -floor)


def _secondary_stages(
    model: CTIBenchmark,
    *,
    fixed_rho: Mapping[str, float] | None = None,
    preservation_tolerance: float = 1e-7,
) -> tuple[LPData, object, float, float]:
    nominal_objective = nominal_delivery_objective(model)
    nominal_problem = build_lp(
        model, nominal_objective, maximize=True, fixed_rho=fixed_rho
    )
    nominal_result = run_lp(nominal_problem)
    nominal_value = objective_value(nominal_problem, nominal_result)
    nominal_preservation = _preservation_row(
        nominal_objective, nominal_value, preservation_tolerance
    )

    contingency_objective = contingency_delivery_objective(model)
    contingency_problem = build_lp(
        model,
        contingency_objective,
        maximize=True,
        fixed_rho=fixed_rho,
        extra_ub=(nominal_preservation,),
    )
    contingency_result = run_lp(contingency_problem)
    contingency_value = objective_value(contingency_problem, contingency_result)
    contingency_preservation = _preservation_row(
        contingency_objective, contingency_value, preservation_tolerance
    )

    effort_problem = build_lp(
        model,
        recourse_objective(model),
        maximize=False,
        fixed_rho=fixed_rho,
        extra_ub=(nominal_preservation, contingency_preservation),
    )
    effort_result = run_lp(effort_problem)
    return effort_problem, effort_result, nominal_value, contingency_value


def solve_utilitarian(model: CTIBenchmark) -> CTIRLexSolution:
    """Maximize delivery with the CTI physical and bounded-recourse constraints."""

    problem, result, nominal_value, contingency_value = _secondary_stages(model)
    guarantees = realized_guarantees(model, problem, result)
    return _extract_solution(
        model,
        problem,
        result,
        guarantees,
        (),
        nominal_value,
        contingency_value,
    )


def solve_robust_proportional(model: CTIBenchmark) -> CTIRLexSolution:
    """Maximize one common robust service floor without lexicographic refinement."""

    theta_problem = build_lp(
        model,
        {("theta",): 1.0},
        maximize=True,
        theta_active=model.claimants,
    )
    theta_result = run_lp(theta_problem)
    theta_star = value(theta_problem, theta_result, ("theta",))
    fixed = {claimant: theta_star for claimant in model.claimants}
    problem, result, nominal_value, contingency_value = _secondary_stages(
        model, fixed_rho=fixed
    )
    guarantees = realized_guarantees(model, problem, result)
    return _extract_solution(
        model,
        problem,
        result,
        guarantees,
        (LeximinLevel(theta_star, tuple(model.claimants)),),
        nominal_value,
        contingency_value,
    )


def subset_scenarios(model: CTIBenchmark, scenarios: Iterable[str]) -> CTIBenchmark:
    selected = tuple(scenarios)
    if model.nominal_scenario not in selected:
        raise ValueError("The nominal scenario must be retained.")
    unknown = set(selected) - set(model.scenarios)
    if unknown:
        raise KeyError(f"Unknown scenarios: {sorted(unknown)}")
    scenario_set = set(selected)
    return replace(
        model,
        scenarios=selected,
        edge_capacity={key: item for key, item in model.edge_capacity.items() if key[0] in scenario_set},
        edge_efficiency={key: item for key, item in model.edge_efficiency.items() if key[0] in scenario_set},
        source_limit={key: item for key, item in model.source_limit.items() if key[0] in scenario_set},
        source_seasonal_limit={
            key: item for key, item in model.source_seasonal_limit.items() if key[0] in scenario_set
        },
        shared_source_limit={
            key: item for key, item in model.shared_source_limit.items() if key[0] in scenario_set
        },
        recourse_budget={key: model.recourse_budget[key] for key in selected},
        scenario_weight={key: model.scenario_weight[key] for key in selected},
    )


def scale_benchmark(
    model: CTIBenchmark,
    *,
    demand_duty: float,
    conveyance_loss_multiplier: float,
    source_limit_scale: float,
    recourse_budget_scale: float,
    base_duty: float = 2.0,
) -> CTIBenchmark:
    if min(demand_duty, conveyance_loss_multiplier, source_limit_scale) <= 0:
        raise ValueError("Duty, loss multiplier and source scale must be positive.")
    if recourse_budget_scale < 0:
        raise ValueError("Recourse scale must be nonnegative.")
    demand_scale = demand_duty / base_duty
    efficiency = {
        key: max(1e-6, 1.0 - conveyance_loss_multiplier * (1.0 - item))
        for key, item in model.edge_efficiency.items()
    }
    return replace(
        model,
        benchmark_id=(
            f"{model.benchmark_id}__d{demand_duty:g}_l{conveyance_loss_multiplier:g}"
            f"_s{source_limit_scale:g}_r{recourse_budget_scale:g}"
        ),
        demand={key: item * demand_scale for key, item in model.demand.items()},
        edge_efficiency=efficiency,
        source_limit={key: item * source_limit_scale for key, item in model.source_limit.items()},
        source_seasonal_limit={
            key: item * source_limit_scale for key, item in model.source_seasonal_limit.items()
        },
        shared_source_limit={
            key: item * source_limit_scale for key, item in model.shared_source_limit.items()
        },
        recourse_budget={
            key: item * recourse_budget_scale for key, item in model.recourse_budget.items()
        },
    )


def disable_source(model: CTIBenchmark, source_id: str) -> CTIBenchmark:
    if source_id not in model.source_ids:
        raise KeyError(source_id)
    return replace(
        model,
        source_limit={
            key: (0.0 if key[2] == source_id else item)
            for key, item in model.source_limit.items()
        },
        source_seasonal_limit={
            key: (0.0 if key[1] == source_id else item)
            for key, item in model.source_seasonal_limit.items()
        },
    )


def lp_dimensions(model: CTIBenchmark) -> dict[str, int]:
    problem = build_lp(
        model,
        {("theta",): 1.0},
        maximize=True,
        theta_active=model.claimants,
    )
    return {
        "variables": len(problem.keys),
        "equality_constraints": problem.a_eq.shape[0],
        "inequality_constraints": problem.a_ub.shape[0],
        "nonzeros": problem.a_eq.nnz + problem.a_ub.nnz,
    }


def timed_solve(solver, model: CTIBenchmark) -> tuple[CTIRLexSolution, float]:
    started = perf_counter()
    solution = solver(model)
    return solution, perf_counter() - started
