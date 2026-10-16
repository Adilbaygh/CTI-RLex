"""The published nominal plan held fixed, and one scenario answered by recourse alone.

Shared by scripts/robust_vertex_check.py and scripts/historical_reliability.py (Reviewer 1,
point 1.2). Both ask what the plan CTI-RLex publishes can still deliver in a scenario the
optimization did not see -- a convex combination of its scenarios, or a historical year -- when
the nominal plan stays as published and only the bounded recourse may respond.

The scenario is set beside the nominal one in a two-scenario instance with the network,
efficiencies, demands and recourse controls of the published benchmark. Every nominal variable
(reach flows, source injections, terminal withdrawals and deliveries) is fixed by an equality
to its value in the published solution, so the recourse is measured from the published plan.

Service levels are ratios delivery / (weight * demand) taken over every period with positive
demand, capped at 1. With weight 1 they are service ratios; with the published guarantee as
weight they are the share of the promised guarantee the scenario delivers.

Not an experiment script: it writes nothing and is imported by the two above.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from leximin.dag import CTIBenchmark, OptimizationError, solve_cti_rlex  # noqa: E402
from leximin.dag.lp import build_lp, objective_value, run_lp, value  # noqa: E402

BLOCKING = 1e-7          # the solver's blocking tolerance
UNLIMITED_BUDGET = 1e9   # a budget no plan can exhaust, for the least effort a scenario forces


def published_plan(model: CTIBenchmark):
    """The published CTI-RLex solution and the rows that fix its nominal plan."""

    solution = solve_cti_rlex(model)
    nominal = model.nominal_scenario
    rows = []

    def fix(key: tuple, number: float, upper: float) -> None:
        rows.append(({key: 1.0}, min(max(number, 0.0), upper)))

    for period in model.periods:
        for edge in model.edge_ids:
            fix(("q", nominal, period, edge), solution.edge_flow[nominal, period, edge],
                model.edge_capacity[nominal, period, edge])
        for source in model.source_ids:
            fix(("g", nominal, period, source), solution.source_injection[nominal, period, source],
                model.source_limit[nominal, period, source])
        for terminal in model.terminals:
            demand = model.demand[period, terminal.claimant_id]
            alpha = model.application_efficiency[period, terminal.terminal_id]
            fix(("w", nominal, period, terminal.terminal_id),
                solution.gross_terminal_withdrawal[nominal, period, terminal.terminal_id],
                demand / alpha if alpha else 0.0)
            fix(("x", nominal, period, terminal.terminal_id),
                solution.beneficial_delivery[nominal, period, terminal.terminal_id], demand)
    return solution, tuple(rows)


def scenario_parameters(model: CTIBenchmark, scenario: str) -> dict:
    """Every right-hand side through which a scenario enters: capacities, limits, budget."""

    return {
        "edge_capacity": {(p, e): model.edge_capacity[scenario, p, e] for p in model.periods for e in model.edge_ids},
        "source_limit": {(p, s): model.source_limit[scenario, p, s] for p in model.periods for s in model.source_ids},
        "source_seasonal_limit": {s: model.source_seasonal_limit[scenario, s] for s in model.source_ids},
        "shared_source_limit": {(p, g): model.shared_source_limit[scenario, p, g]
                                for p in model.periods for g in model.source_groups},
        "recourse_budget": model.recourse_budget[scenario],
    }


def combine(parts: Sequence[tuple[float, dict]]) -> dict:
    """The convex combination sum(weight * parameters) of scenario parameter sets."""

    first = parts[0][1]
    combined: dict = {}
    for name, entry in first.items():
        if isinstance(entry, dict):
            combined[name] = {key: sum(weight * item[name][key] for weight, item in parts) for key in entry}
        else:
            combined[name] = sum(weight * item[name] for weight, item in parts)
    return combined


def two_scenario_model(model: CTIBenchmark, label: str, parameters: Mapping) -> CTIBenchmark:
    """The published nominal scenario and one more scenario, `label`, with the given parameters."""

    nominal = model.nominal_scenario
    scenarios = (nominal, label)

    def per_period(field: str, published: Mapping) -> dict:
        values = {key: number for key, number in published.items() if key[0] == nominal}
        values.update({(label, *key): number for key, number in parameters[field].items()})
        return values

    edge_efficiency = {key: number for key, number in model.edge_efficiency.items() if key[0] == nominal}
    edge_efficiency.update({(label, p, e): model.edge_efficiency[nominal, p, e]
                            for p in model.periods for e in model.edge_ids})
    seasonal = {key: number for key, number in model.source_seasonal_limit.items() if key[0] == nominal}
    seasonal.update({(label, s): number for s, number in parameters["source_seasonal_limit"].items()})
    return replace(
        model,
        benchmark_id=f"{model.benchmark_id}:{label}",
        scenarios=scenarios,
        edge_capacity=per_period("edge_capacity", model.edge_capacity),
        edge_efficiency=edge_efficiency,
        source_limit=per_period("source_limit", model.source_limit),
        source_seasonal_limit=seasonal,
        shared_source_limit=per_period("shared_source_limit", model.shared_source_limit),
        recourse_budget={nominal: 0.0, label: parameters["recourse_budget"]},
        scenario_weight={nominal: 0.0, label: 1.0},
    )


def least_effort(model: CTIBenchmark, label: str, plan_rows) -> float:
    """The least normalized recourse effort with which the scenario can be operated at all."""

    open_budget = replace(model, recourse_budget={**model.recourse_budget, label: UNLIMITED_BUDGET})
    objective = {("u", label, period, asset.asset_id): asset.effort_coefficient
                 for period in model.periods for asset in model.controls}
    problem = build_lp(open_budget, objective, maximize=False, extra_eq=plan_rows)
    return objective_value(problem, run_lp(problem))


def operate(model: CTIBenchmark, label: str, parameters: Mapping, plan_rows,
            overrun_tolerance: float = 1e-9) -> tuple[CTIBenchmark, float, float]:
    """The two-scenario instance, its least effort, and the effort beyond the budget.

    When the scenario forces the plan further from its nominal values than the budget allows,
    no recourse is feasible and nothing could be measured; the budget is then raised to the
    least effort that operates the plan, and the excess is returned for the caller to report.
    """

    instance = two_scenario_model(model, label, parameters)
    least = least_effort(instance, label, plan_rows)
    overrun = max(0.0, least - parameters["recourse_budget"])
    if overrun > overrun_tolerance:
        raised = dict(parameters, recourse_budget=least * (1 + 1e-9) + 1e-12)
        instance = two_scenario_model(model, label, raised)
    return instance, least, overrun


def _service_rows(model: CTIBenchmark, label: str, claimant: str, weight: float,
                  level: float | None) -> list:
    """delivery >= level * weight * demand in every period with demand; theta in place of level if None."""

    rows = []
    terminals = model.terminals_by_claimant[claimant]
    for period in model.periods:
        demand = model.demand[period, claimant]
        if demand <= 0:
            continue
        delivery = {("x", label, period, terminal.terminal_id): -1.0 for terminal in terminals}
        if level is None:
            rows.append(({**delivery, ("theta",): weight * demand}, 0.0))
        else:
            rows.append((delivery, -level * weight * demand))
    return rows


def _maximize_theta(model, label, plan_rows, rows) -> float:
    problem = build_lp(model, {("theta",): 1.0}, maximize=True, theta_active=(),
                       extra_ub=tuple(rows), extra_eq=plan_rows)
    return value(problem, run_lp(problem), ("theta",))


def common_level(model: CTIBenchmark, label: str, plan_rows, weights: Mapping[str, float]) -> float:
    """The largest level, at most 1, that every claimant in `weights` reaches together."""

    rows = []
    for claimant, weight in weights.items():
        rows += _service_rows(model, label, claimant, weight, None)
    return _maximize_theta(model, label, plan_rows, rows)


def leximin_levels(model: CTIBenchmark, label: str, plan_rows, weights: Mapping[str, float],
                   blocking: float = BLOCKING) -> tuple[dict[str, float], list[dict]]:
    """Progressive filling of the claimants' levels in the scenario, each capped at 1."""

    active = list(weights)
    fixed: dict[str, float] = {}
    record = []
    while active:
        floors = []
        for claimant, level in fixed.items():
            floors += _service_rows(model, label, claimant, weights[claimant], level)
        rows = list(floors)
        for claimant in active:
            rows += _service_rows(model, label, claimant, weights[claimant], None)
        theta = _maximize_theta(model, label, plan_rows, rows)
        maxima = {}
        for claimant in active:
            rows = list(floors)
            for other in active:
                if other != claimant:
                    rows += _service_rows(model, label, other, weights[other], theta)
            rows += _service_rows(model, label, claimant, weights[claimant], None)
            maxima[claimant] = _maximize_theta(model, label, plan_rows, rows)
        blocked = [claimant for claimant in active if maxima[claimant] <= theta + blocking]
        if not blocked:
            raise OptimizationError(f"no blocked claimant at level {theta:.12g}: {maxima}")
        for claimant in blocked:
            fixed[claimant] = theta
        record.append({"level": theta, "blocked": blocked})
        active = [claimant for claimant in active if claimant not in blocked]
    return fixed, record
