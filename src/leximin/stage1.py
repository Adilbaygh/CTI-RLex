from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import numpy as np
from scipy.optimize import linprog

from .domain import Benchmark
from .operators import build_operator_exact


@dataclass(frozen=True, slots=True)
class Stage1ClosedForm:
    lambda_star: Fraction
    source_loads: dict[str, Fraction]
    edge_loads: dict[tuple[str, str], Fraction]
    active_resources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Stage1LP:
    lambda_star: float
    ratios: dict[tuple[str, str], float]
    status: int
    message: str


def full_demand_loads(
    model: Benchmark,
) -> tuple[dict[str, Fraction], dict[tuple[str, str], Fraction]]:
    a, b = build_operator_exact(model)
    source_loads: dict[str, Fraction] = {}
    edge_loads: dict[tuple[str, str], Fraction] = {}
    for period in model.periods:
        source_loads[period] = sum(
            b[(period, user.user_id)] * model.demand[period][user.user_id]
            for user in model.users
        )
        for edge_id in model.edge_ids:
            edge_loads[(period, edge_id)] = sum(
                a[(period, edge_id, user.user_id)]
                * model.demand[period][user.user_id]
                for user in model.users
            )
    return source_loads, edge_loads


def solve_stage1_closed_form(model: Benchmark) -> Stage1ClosedForm:
    source_loads, edge_loads = full_demand_loads(model)
    candidates: list[tuple[Fraction, str]] = [(Fraction(1), "demand_upper_bound")]
    for period, load in source_loads.items():
        if load > 0:
            candidates.append((model.source_capacity[period] / load, f"source:{period}"))
    for (period, edge_id), load in edge_loads.items():
        if load > 0:
            candidates.append(
                (model.edge_capacity[period][edge_id] / load, f"edge:{period}:{edge_id}")
            )
    lambda_star = min(value for value, _ in candidates)
    if lambda_star < 0:
        raise ValueError("Closed-form Stage-1 value cannot be negative.")
    lambda_star = min(Fraction(1), lambda_star)
    active = tuple(label for value, label in candidates if value == lambda_star)
    return Stage1ClosedForm(lambda_star, source_loads, edge_loads, active)


def _physical_ub(model: Benchmark) -> tuple[np.ndarray, np.ndarray, tuple[tuple[str, str], ...]]:
    records = model.active_records
    index = {record: idx for idx, record in enumerate(records)}
    a_coeff, b_coeff = build_operator_exact(model)
    rows: list[np.ndarray] = []
    rhs: list[float] = []

    for period in model.periods:
        row = np.zeros(len(records), dtype=float)
        for user in model.users:
            record = (period, user.user_id)
            if record in index:
                row[index[record]] = float(
                    b_coeff[record] * model.demand[period][user.user_id]
                )
        rows.append(row)
        rhs.append(float(model.source_capacity[period]))

    for period in model.periods:
        for edge_id in model.edge_ids:
            row = np.zeros(len(records), dtype=float)
            for user in model.users:
                record = (period, user.user_id)
                if record in index:
                    row[index[record]] = float(
                        a_coeff[(period, edge_id, user.user_id)]
                        * model.demand[period][user.user_id]
                    )
            rows.append(row)
            rhs.append(float(model.edge_capacity[period][edge_id]))
    return np.vstack(rows), np.asarray(rhs, dtype=float), records


def solve_stage1_lp(model: Benchmark, feasibility_tolerance: float = 1e-9) -> Stage1LP:
    physical_a, physical_b, records = _physical_ub(model)
    n = len(records)
    a_ub = np.zeros((physical_a.shape[0] + n, n + 1), dtype=float)
    b_ub = np.zeros(physical_b.shape[0] + n, dtype=float)
    a_ub[: physical_a.shape[0], :n] = physical_a
    b_ub[: physical_b.shape[0]] = physical_b
    for idx in range(n):
        a_ub[physical_a.shape[0] + idx, idx] = -1.0
        a_ub[physical_a.shape[0] + idx, n] = 1.0

    objective = np.zeros(n + 1, dtype=float)
    objective[n] = -1.0
    result = linprog(
        objective,
        A_ub=a_ub,
        b_ub=b_ub,
        bounds=[(0.0, 1.0)] * n + [(0.0, 1.0)],
        method="highs",
        options={
            "primal_feasibility_tolerance": feasibility_tolerance,
            "dual_feasibility_tolerance": feasibility_tolerance,
        },
    )
    if not result.success:
        raise RuntimeError(f"Stage 1 failed: {result.message}")
    ratios = {record: float(result.x[idx]) for idx, record in enumerate(records)}
    return Stage1LP(float(result.x[n]), ratios, int(result.status), str(result.message))


def physical_matrices(model: Benchmark) -> tuple[np.ndarray, np.ndarray, tuple[tuple[str, str], ...]]:
    return _physical_ub(model)
