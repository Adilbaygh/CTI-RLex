from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from time import perf_counter
from typing import Any, Iterable, Mapping

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


def solve_utilitarian_fair(
    model: CTIBenchmark, *, preservation_tolerance: float = 1e-7
) -> CTIRLexSolution:
    """Utilitarian allocation with a fairness-optimistic tie-break.

    Maximizing delivery alone leaves many optima that move the same total volume but
    distribute it very differently, so the guarantee carried by one solver vertex is an
    artefact of the pivot rule. This first fixes the delivery optimum, then selects the
    plan with the highest common service floor among the plans that attain it. The
    comparison against CTI-RLex is then a property of the objective, not of the solver.
    """

    nominal_objective = nominal_delivery_objective(model)
    delivery_problem = build_lp(model, nominal_objective, maximize=True)
    delivery_result = run_lp(delivery_problem)
    optimum = objective_value(delivery_problem, delivery_result)
    preservation = _preservation_row(nominal_objective, optimum, preservation_tolerance)

    theta_problem = build_lp(
        model,
        {("theta",): 1.0},
        maximize=True,
        theta_active=model.claimants,
        extra_ub=(preservation,),
    )
    theta_result = run_lp(theta_problem)
    theta_star = value(theta_problem, theta_result, ("theta",))

    fixed = {claimant: theta_star for claimant in model.claimants}
    problem, result, nominal_value, contingency_value = _secondary_stages(
        model, fixed_rho=fixed, preservation_tolerance=preservation_tolerance
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


def utilitarian_fairness_range(
    model: CTIBenchmark, *, preservation_tolerance: float = 1e-7
) -> dict[str, Any]:
    """How far the minimum service can move without changing total delivery.

    Returns the delivery optimum, the highest common floor attainable on the
    delivery-optimal face, and, for every claimant, the lowest seasonal service ratio a
    delivery-maximizing plan can impose on it. A wide interval means a reported
    utilitarian guarantee is a solver artefact rather than a property of the objective.
    """

    nominal_objective = nominal_delivery_objective(model)
    delivery_problem = build_lp(model, nominal_objective, maximize=True)
    delivery_result = run_lp(delivery_problem)
    optimum = objective_value(delivery_problem, delivery_result)
    preservation = _preservation_row(nominal_objective, optimum, preservation_tolerance)

    theta_problem = build_lp(
        model,
        {("theta",): 1.0},
        maximize=True,
        theta_active=model.claimants,
        extra_ub=(preservation,),
    )
    theta_result = run_lp(theta_problem)
    theta_max = value(theta_problem, theta_result, ("theta",))

    nominal = model.nominal_scenario
    worst_ratio: dict[str, float] = {}
    for claimant, terminals in model.terminals_by_claimant.items():
        demand = sum(model.demand[period, claimant] for period in model.periods)
        if demand <= 0:
            continue
        objective = {
            ("x", nominal, period, terminal.terminal_id): 1.0
            for period in model.periods
            for terminal in terminals
        }
        floor_problem = build_lp(
            model, objective, maximize=False, extra_ub=(preservation,)
        )
        floor_result = run_lp(floor_problem)
        worst_ratio[claimant] = objective_value(floor_problem, floor_result) / demand

    return {
        "nominal_delivery_optimum": optimum,
        "max_common_floor_on_optimal_face": theta_max,
        "min_seasonal_ratio_by_claimant": worst_ratio,
        "worst_claimant_seasonal_ratio": min(worst_ratio.values()) if worst_ratio else None,
    }


def source_ablation_report(model: CTIBenchmark, *, tolerance: float = 1e-9) -> dict[str, Any]:
    """Separate structural disconnection from capacity scarcity in source ablation.

    Removing a source can drive the minimum guarantee to zero for two very different
    reasons: the claimant may lose every directed path to a remaining injection, or it
    may stay connected but be throttled by reach capacity, a seasonal volume or a shared
    envelope. The first is a property of the graph and no allocation rule can repair it;
    only the second is an optimization result. Each ablation is therefore reported with
    the set of claimants that becomes unreachable, so criticality claims stay precise.
    """

    from .solver import solve_cti_rlex

    base = solve_cti_rlex(model)
    base_minimum = min(base.guarantees.values())
    base_nominal = base.nominal_beneficial_delivery

    successors: dict[str, list[str]] = defaultdict(list)
    for edge in model.edges:
        successors[edge.tail].append(edge.head)

    rows: list[dict[str, Any]] = []
    for source in model.sources:
        remaining = [item for item in model.sources if item.source_id != source.source_id]
        reached = {item.node for item in remaining}
        stack = list(reached)
        while stack:
            node = stack.pop()
            for following in successors.get(node, ()):
                if following not in reached:
                    reached.add(following)
                    stack.append(following)
        disconnected = sorted(
            claimant
            for claimant, terminals in model.terminals_by_claimant.items()
            if not any(terminal.node in reached for terminal in terminals)
        )

        solution = solve_cti_rlex(disable_source(model, source.source_id))
        minimum = min(solution.guarantees.values())
        if disconnected:
            explanation = "structural_disconnection"
        elif minimum < base_minimum - tolerance:
            explanation = "binding_capacity_or_envelope"
        else:
            explanation = "redundant_at_the_optimum"
        rows.append(
            {
                "source_id": source.source_id,
                "source_class": source.source_class,
                "disconnected_claimants": disconnected,
                "min_guarantee": minimum,
                "delta_percentage_points": 100.0 * (minimum - base_minimum),
                "nominal_delivery_af": solution.nominal_beneficial_delivery,
                "delta_nominal_af": solution.nominal_beneficial_delivery - base_nominal,
                "explanation": explanation,
            }
        )

    return {
        "base_min_guarantee": base_minimum,
        "base_nominal_delivery_af": base_nominal,
        "rows": sorted(rows, key=lambda row: row["min_guarantee"]),
    }


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


def subset_claimants(model: CTIBenchmark, claimants: Iterable[str]) -> CTIBenchmark:
    """Restrict the fairness subjects while keeping the physical network intact.

    Scalability has to be measured against the number of guarantee levels the solver
    has to resolve, not only against the number of scenarios. Holding the reaches,
    sources and envelopes fixed and varying only the claimant set isolates that effect,
    which is what the progressive-filling sequence actually grows with.
    """

    selected = tuple(claimants)
    unknown = set(selected) - set(model.claimants)
    if unknown:
        raise ValueError(f"Unknown claimants: {sorted(unknown)}")
    if not selected:
        raise ValueError("At least one claimant must be retained.")
    keep = set(selected)
    terminals = tuple(item for item in model.terminals if item.claimant_id in keep)
    demand = {
        (period, claimant): value
        for (period, claimant), value in model.demand.items()
        if claimant in keep
    }
    return replace(
        model,
        claimants=selected,
        terminals=terminals,
        demand=demand,
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
