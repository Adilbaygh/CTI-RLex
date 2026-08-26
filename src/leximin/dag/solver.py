from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .domain import CTIBenchmark
from .lp import (
    LPData,
    OptimizationError,
    VariableKey,
    build_lp,
    generic_residuals,
    objective_value,
    run_lp,
    value,
)


@dataclass(frozen=True, slots=True)
class LeximinLevel:
    level: float
    blocked_claimants: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CTIRLexSolution:
    benchmark_id: str
    guarantees: Mapping[str, float]
    leximin_levels: tuple[LeximinLevel, ...]
    nominal_beneficial_delivery: float
    weighted_contingency_beneficial_delivery: float
    normalized_recourse_effort: float
    edge_flow: Mapping[tuple[str, str, str], float]
    source_injection: Mapping[tuple[str, str, str], float]
    gross_terminal_withdrawal: Mapping[tuple[str, str, str], float]
    beneficial_delivery: Mapping[tuple[str, str, str], float]
    period_service_ratio: Mapping[tuple[str, str, str], float]
    seasonal_service_ratio: Mapping[tuple[str, str], float]
    recourse_by_scenario: Mapping[str, float]
    residuals: Mapping[str, float]

    @property
    def first_leximin_level(self) -> float:
        return min(self.guarantees.values())

    def to_dict(self) -> dict[str, object]:
        def encoded(mapping: Mapping[tuple[str, ...], float]) -> dict[str, float]:
            return {"|".join(key): value for key, value in sorted(mapping.items())}

        return {
            "benchmark_id": self.benchmark_id,
            "guarantees": dict(self.guarantees),
            "leximin_levels": [
                {"level": item.level, "blocked_claimants": list(item.blocked_claimants)}
                for item in self.leximin_levels
            ],
            "objectives": {
                "nominal_beneficial_delivery_af": self.nominal_beneficial_delivery,
                "weighted_contingency_beneficial_delivery_af": self.weighted_contingency_beneficial_delivery,
                "normalized_recourse_effort": self.normalized_recourse_effort,
            },
            "period_service_ratio": encoded(self.period_service_ratio),
            "seasonal_service_ratio": encoded(self.seasonal_service_ratio),
            "recourse_by_scenario": dict(self.recourse_by_scenario),
            "edge_flow_af": encoded(self.edge_flow),
            "source_injection_af": encoded(self.source_injection),
            "gross_terminal_withdrawal_af": encoded(self.gross_terminal_withdrawal),
            "beneficial_delivery_af": encoded(self.beneficial_delivery),
            "residuals": dict(self.residuals),
        }


def _freeze(mapping: dict) -> Mapping:
    return MappingProxyType(mapping)


def _nominal_delivery_objective(model: CTIBenchmark) -> dict[VariableKey, float]:
    return {
        ("x", model.nominal_scenario, period, terminal.terminal_id): 1.0
        for period in model.periods
        for terminal in model.terminals
    }


def _contingency_delivery_objective(model: CTIBenchmark) -> dict[VariableKey, float]:
    return {
        ("x", scenario, period, terminal.terminal_id): model.scenario_weight[scenario]
        for scenario in model.contingency_scenarios
        for period in model.periods
        for terminal in model.terminals
    }


def _recourse_objective(model: CTIBenchmark) -> dict[VariableKey, float]:
    return {
        ("u", scenario, period, asset.asset_id): asset.effort_coefficient
        for scenario in model.contingency_scenarios
        for period in model.periods
        for asset in model.controls
    }


def _extract_solution(
    model: CTIBenchmark,
    problem: LPData,
    result,
    guarantees: Mapping[str, float],
    levels: tuple[LeximinLevel, ...],
    nominal_value: float,
    contingency_value: float,
) -> CTIRLexSolution:
    edge_flow = {
        (scenario, period, edge): value(problem, result, ("q", scenario, period, edge))
        for scenario in model.scenarios
        for period in model.periods
        for edge in model.edge_ids
    }
    source_injection = {
        (scenario, period, source): value(problem, result, ("g", scenario, period, source))
        for scenario in model.scenarios
        for period in model.periods
        for source in model.source_ids
    }
    gross_withdrawal = {
        (scenario, period, terminal.terminal_id): value(
            problem, result, ("w", scenario, period, terminal.terminal_id)
        )
        for scenario in model.scenarios
        for period in model.periods
        for terminal in model.terminals
    }
    beneficial = {
        (scenario, period, terminal.terminal_id): value(
            problem, result, ("x", scenario, period, terminal.terminal_id)
        )
        for scenario in model.scenarios
        for period in model.periods
        for terminal in model.terminals
    }

    period_ratio: dict[tuple[str, str, str], float] = {}
    seasonal_ratio: dict[tuple[str, str], float] = {}
    for scenario in model.scenarios:
        for claimant, terminals in model.terminals_by_claimant.items():
            seasonal_delivery = 0.0
            seasonal_demand = 0.0
            for period in model.periods:
                delivery = sum(
                    beneficial[scenario, period, terminal.terminal_id] for terminal in terminals
                )
                demand = model.demand[period, claimant]
                period_ratio[scenario, period, claimant] = delivery / demand if demand > 0 else 1.0
                seasonal_delivery += delivery
                seasonal_demand += demand
            seasonal_ratio[scenario, claimant] = seasonal_delivery / seasonal_demand

    recourse_by_scenario: dict[str, float] = {}
    for scenario in model.contingency_scenarios:
        recourse_by_scenario[scenario] = sum(
            asset.effort_coefficient
            * value(problem, result, ("u", scenario, period, asset.asset_id))
            for period in model.periods
            for asset in model.controls
        )
    total_recourse = sum(recourse_by_scenario.values())

    return CTIRLexSolution(
        benchmark_id=model.benchmark_id,
        guarantees=_freeze(dict(guarantees)),
        leximin_levels=levels,
        nominal_beneficial_delivery=nominal_value,
        weighted_contingency_beneficial_delivery=contingency_value,
        normalized_recourse_effort=total_recourse,
        edge_flow=_freeze(edge_flow),
        source_injection=_freeze(source_injection),
        gross_terminal_withdrawal=_freeze(gross_withdrawal),
        beneficial_delivery=_freeze(beneficial),
        period_service_ratio=_freeze(period_ratio),
        seasonal_service_ratio=_freeze(seasonal_ratio),
        recourse_by_scenario=_freeze(recourse_by_scenario),
        residuals=_freeze(generic_residuals(problem, result)),
    )


def solve_cti_rlex(
    model: CTIBenchmark,
    *,
    blocking_tolerance: float = 1e-7,
    preservation_tolerance: float = 1e-7,
) -> CTIRLexSolution:
    """Solve the complete CTI-RLex vector and deterministic secondary stages."""

    active = list(model.claimants)
    fixed: dict[str, float] = {}
    levels: list[LeximinLevel] = []

    while active:
        theta_problem = build_lp(
            model,
            {("theta",): 1.0},
            maximize=True,
            fixed_rho=fixed,
            theta_active=active,
        )
        theta_result = run_lp(theta_problem)
        theta_star = value(theta_problem, theta_result, ("theta",))

        maxima: dict[str, float] = {}
        floors = {claimant: theta_star for claimant in active}
        for claimant in active:
            test_problem = build_lp(
                model,
                {("rho", claimant): 1.0},
                maximize=True,
                fixed_rho=fixed,
                rho_floors=floors,
            )
            test_result = run_lp(test_problem)
            maxima[claimant] = value(test_problem, test_result, ("rho", claimant))

        blocked = tuple(
            claimant
            for claimant in active
            if maxima[claimant] <= theta_star + blocking_tolerance
        )
        if not blocked:
            details = ", ".join(f"{claimant}={maximum:.12g}" for claimant, maximum in maxima.items())
            raise OptimizationError(
                f"Progressive filling found no blocked claimant at theta={theta_star:.12g}; {details}"
            )
        for claimant in blocked:
            fixed[claimant] = theta_star
        levels.append(LeximinLevel(theta_star, blocked))
        active = [claimant for claimant in active if claimant not in blocked]

    nominal_objective = _nominal_delivery_objective(model)
    nominal_problem = build_lp(model, nominal_objective, maximize=True, fixed_rho=fixed)
    nominal_result = run_lp(nominal_problem)
    nominal_value = objective_value(nominal_problem, nominal_result)
    nominal_floor = nominal_value - preservation_tolerance * max(1.0, abs(nominal_value))
    nominal_preservation = ({key: -coefficient for key, coefficient in nominal_objective.items()}, -nominal_floor)

    contingency_objective = _contingency_delivery_objective(model)
    contingency_problem = build_lp(
        model,
        contingency_objective,
        maximize=True,
        fixed_rho=fixed,
        extra_ub=(nominal_preservation,),
    )
    contingency_result = run_lp(contingency_problem)
    contingency_value = objective_value(contingency_problem, contingency_result)
    contingency_floor = contingency_value - preservation_tolerance * max(1.0, abs(contingency_value))
    contingency_preservation = (
        {key: -coefficient for key, coefficient in contingency_objective.items()},
        -contingency_floor,
    )

    effort_problem = build_lp(
        model,
        _recourse_objective(model),
        maximize=False,
        fixed_rho=fixed,
        extra_ub=(nominal_preservation, contingency_preservation),
    )
    effort_result = run_lp(effort_problem)
    return _extract_solution(
        model,
        effort_problem,
        effort_result,
        fixed,
        tuple(levels),
        nominal_value,
        contingency_value,
    )
