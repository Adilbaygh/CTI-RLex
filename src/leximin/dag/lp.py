from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import OptimizeResult, linprog
from scipy.sparse import coo_matrix, csr_matrix

from .domain import CTIBenchmark


VariableKey = tuple[Hashable, ...]
LinearRow = tuple[Mapping[VariableKey, float], float]


class OptimizationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LPData:
    keys: tuple[VariableKey, ...]
    index: Mapping[VariableKey, int]
    c: np.ndarray
    objective: np.ndarray
    maximize: bool
    bounds: tuple[tuple[float | None, float | None], ...]
    a_ub: csr_matrix
    b_ub: np.ndarray
    a_eq: csr_matrix
    b_eq: np.ndarray


def _matrix(rows: Sequence[Mapping[int, float]], columns: int) -> csr_matrix:
    data: list[float] = []
    row_index: list[int] = []
    column_index: list[int] = []
    for r, row in enumerate(rows):
        for c, value in row.items():
            if value:
                row_index.append(r)
                column_index.append(c)
                data.append(float(value))
    return coo_matrix((data, (row_index, column_index)), shape=(len(rows), columns)).tocsr()


def build_lp(
    model: CTIBenchmark,
    objective: Mapping[VariableKey, float],
    *,
    maximize: bool,
    fixed_rho: Mapping[str, float] | None = None,
    rho_floors: Mapping[str, float] | None = None,
    theta_active: Sequence[str] | None = None,
    extra_ub: Sequence[LinearRow] = (),
    extra_eq: Sequence[LinearRow] = (),
) -> LPData:
    keys: list[VariableKey] = []
    bounds: list[tuple[float | None, float | None]] = []

    def add(key: VariableKey, lower: float | None = 0.0, upper: float | None = None) -> None:
        keys.append(key)
        bounds.append((lower, upper))

    for scenario in model.scenarios:
        for period in model.periods:
            for edge in model.edge_ids:
                add(("q", scenario, period, edge), upper=model.edge_capacity[scenario, period, edge])
            for source in model.source_ids:
                add(("g", scenario, period, source), upper=model.source_limit[scenario, period, source])
            for terminal in model.terminals:
                demand = model.demand[period, terminal.claimant_id]
                alpha = model.application_efficiency[period, terminal.terminal_id]
                add(("w", scenario, period, terminal.terminal_id), upper=demand / alpha if alpha else 0.0)
                add(("x", scenario, period, terminal.terminal_id), upper=demand)
    for scenario in model.contingency_scenarios:
        for period in model.periods:
            for asset in model.controls:
                add(("u", scenario, period, asset.asset_id))
    for claimant in model.claimants:
        add(("rho", claimant), upper=1.0)
    if theta_active is not None:
        add(("theta",), upper=1.0)

    index = {key: idx for idx, key in enumerate(keys)}
    if len(index) != len(keys):
        raise ValueError("Internal error: duplicate LP variable key.")

    ub_rows: list[dict[int, float]] = []
    ub_rhs: list[float] = []
    eq_rows: list[dict[int, float]] = []
    eq_rhs: list[float] = []

    def convert(coefficients: Mapping[VariableKey, float]) -> dict[int, float]:
        row: dict[int, float] = defaultdict(float)
        for key, value in coefficients.items():
            if key not in index:
                raise KeyError(f"Unknown LP variable key {key!r}.")
            row[index[key]] += float(value)
        return dict(row)

    def add_ub(coefficients: Mapping[VariableKey, float], rhs: float) -> None:
        ub_rows.append(convert(coefficients))
        ub_rhs.append(float(rhs))

    def add_eq(coefficients: Mapping[VariableKey, float], rhs: float) -> None:
        eq_rows.append(convert(coefficients))
        eq_rhs.append(float(rhs))

    incoming = model.incoming_edges()
    outgoing = model.outgoing_edges()
    source_at_node: dict[str, tuple[str, ...]] = {
        node: tuple(source.source_id for source in model.sources if source.node == node)
        for node in model.nodes
    }
    terminal_at_node = model.terminals_by_node

    for scenario in model.scenarios:
        for period in model.periods:
            for node in model.nodes:
                coefficients: dict[VariableKey, float] = {}
                for edge in outgoing[node]:
                    coefficients[("q", scenario, period, edge.edge_id)] = 1.0
                for terminal in terminal_at_node[node]:
                    coefficients[("w", scenario, period, terminal.terminal_id)] = 1.0
                for edge in incoming[node]:
                    coefficients[("q", scenario, period, edge.edge_id)] = -model.edge_efficiency[
                        scenario, period, edge.edge_id
                    ]
                for source in source_at_node[node]:
                    coefficients[("g", scenario, period, source)] = -1.0
                add_eq(coefficients, 0.0)

            for terminal in model.terminals:
                add_eq(
                    {
                        ("x", scenario, period, terminal.terminal_id): 1.0,
                        ("w", scenario, period, terminal.terminal_id): -model.application_efficiency[
                            period, terminal.terminal_id
                        ],
                    },
                    0.0,
                )

            for claimant, terminals in model.terminals_by_claimant.items():
                demand = model.demand[period, claimant]
                delivery = {
                    ("x", scenario, period, terminal.terminal_id): 1.0
                    for terminal in terminals
                }
                add_ub(delivery, demand)
                if demand > 0:
                    guarantee = {key: -value for key, value in delivery.items()}
                    guarantee[("rho", claimant)] = demand
                    add_ub(guarantee, 0.0)

            for group in model.source_groups:
                add_ub(
                    {
                        ("g", scenario, period, source): beta
                        for source, beta in model.group_members[group]
                    },
                    model.shared_source_limit[scenario, period, group],
                )

        for source in model.source_ids:
            add_ub(
                {("g", scenario, period, source): 1.0 for period in model.periods},
                model.source_seasonal_limit[scenario, source],
            )

    nominal = model.nominal_scenario
    for scenario in model.contingency_scenarios:
        for period in model.periods:
            for asset in model.controls:
                contingency_key = (
                    "g" if asset.resource_type == "source" else "q",
                    scenario,
                    period,
                    asset.resource_id,
                )
                nominal_key = (
                    "g" if asset.resource_type == "source" else "q",
                    nominal,
                    period,
                    asset.resource_id,
                )
                u_key = ("u", scenario, period, asset.asset_id)
                add_ub({contingency_key: 1.0, nominal_key: -1.0, u_key: -1.0}, 0.0)
                add_ub({contingency_key: -1.0, nominal_key: 1.0, u_key: -1.0}, 0.0)
        add_ub(
            {
                ("u", scenario, period, asset.asset_id): asset.effort_coefficient
                for period in model.periods
                for asset in model.controls
            },
            model.recourse_budget[scenario],
        )

    for claimant, value in (fixed_rho or {}).items():
        add_eq({("rho", claimant): 1.0}, value)
    for claimant, value in (rho_floors or {}).items():
        add_ub({("rho", claimant): -1.0}, -value)
    if theta_active is not None:
        for claimant in theta_active:
            add_ub({("theta",): 1.0, ("rho", claimant): -1.0}, 0.0)
    for row, rhs in extra_ub:
        add_ub(row, rhs)
    for row, rhs in extra_eq:
        add_eq(row, rhs)

    objective_vector = np.zeros(len(keys), dtype=float)
    for key, coefficient in objective.items():
        objective_vector[index[key]] = float(coefficient)
    c = -objective_vector if maximize else objective_vector.copy()
    return LPData(
        keys=tuple(keys),
        index=index,
        c=c,
        objective=objective_vector,
        maximize=maximize,
        bounds=tuple(bounds),
        a_ub=_matrix(ub_rows, len(keys)),
        b_ub=np.asarray(ub_rhs, dtype=float),
        a_eq=_matrix(eq_rows, len(keys)),
        b_eq=np.asarray(eq_rhs, dtype=float),
    )


def run_lp(problem: LPData) -> OptimizeResult:
    result = linprog(
        c=problem.c,
        A_ub=problem.a_ub,
        b_ub=problem.b_ub,
        A_eq=problem.a_eq,
        b_eq=problem.b_eq,
        bounds=problem.bounds,
        method="highs",
    )
    if not result.success:
        raise OptimizationError(f"LP failed with status {result.status}: {result.message}")
    return result


def value(problem: LPData, result: OptimizeResult, key: VariableKey) -> float:
    return float(result.x[problem.index[key]])


def objective_value(problem: LPData, result: OptimizeResult) -> float:
    return float(problem.objective @ result.x)


def generic_residuals(problem: LPData, result: OptimizeResult) -> dict[str, float]:
    equality = problem.a_eq @ result.x - problem.b_eq
    inequality = problem.a_ub @ result.x - problem.b_ub
    lower = [
        max(0.0, float(bound[0]) - float(result.x[index])) if bound[0] is not None else 0.0
        for index, bound in enumerate(problem.bounds)
    ]
    upper = [
        max(0.0, float(result.x[index]) - float(bound[1])) if bound[1] is not None else 0.0
        for index, bound in enumerate(problem.bounds)
    ]
    return {
        "max_equality_residual": float(np.max(np.abs(equality))) if equality.size else 0.0,
        "max_inequality_violation": float(max(0.0, np.max(inequality))) if inequality.size else 0.0,
        "max_bound_violation": max(lower + upper, default=0.0),
    }
