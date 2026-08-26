from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from .domain import Benchmark
from .operators import (
    exact_node_residuals,
    flows_from_node_balance_exact,
    flows_from_operator_exact,
)


@dataclass(frozen=True, slots=True)
class OperatorVerification:
    maximum_absolute_difference: Fraction
    maximum_node_residual: Fraction
    edge_count: int
    period_count: int


def verify_operator_exact(
    model: Benchmark,
    ratios: Mapping[tuple[str, str], Fraction],
) -> OperatorVerification:
    operator_flows, _ = flows_from_operator_exact(model, ratios)
    balance_flows, _ = flows_from_node_balance_exact(model, ratios)
    differences = [abs(operator_flows[key] - balance_flows[key]) for key in operator_flows]
    residuals = exact_node_residuals(model, ratios, operator_flows)
    return OperatorVerification(
        maximum_absolute_difference=max(differences, default=Fraction(0)),
        maximum_node_residual=max((abs(value) for value in residuals.values()), default=Fraction(0)),
        edge_count=len(model.edges),
        period_count=len(model.periods),
    )


def maximum_physical_violation(
    model: Benchmark,
    ratios: Mapping[tuple[str, str], float],
    a_coeff: Mapping[tuple[str, str, str], Fraction],
    b_coeff: Mapping[tuple[str, str], Fraction],
) -> float:
    violations: list[float] = []
    for period in model.periods:
        source_load = sum(
            float(b_coeff[(period, user.user_id)] * model.demand[period][user.user_id])
            * ratios.get((period, user.user_id), 0.0)
            for user in model.users
        )
        violations.append(max(0.0, source_load - float(model.source_capacity[period])))
        for edge_id in model.edge_ids:
            edge_load = sum(
                float(
                    a_coeff[(period, edge_id, user.user_id)]
                    * model.demand[period][user.user_id]
                )
                * ratios.get((period, user.user_id), 0.0)
                for user in model.users
            )
            violations.append(
                max(0.0, edge_load - float(model.edge_capacity[period][edge_id]))
            )
    return float(np.max(violations)) if violations else 0.0
