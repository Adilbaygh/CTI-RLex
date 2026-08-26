from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import numpy as np
from scipy.optimize import linprog

from .domain import Benchmark
from .stage1 import physical_matrices, solve_stage1_closed_form, solve_stage1_lp


@dataclass(frozen=True, slots=True)
class StageSolution:
    name: str
    ratios: dict[tuple[str, str], float]
    objective_value: float
    weighted_satisfaction: float
    minimum_ratio: float
    temporal_variation: float
    status: int
    message: str


@dataclass(frozen=True, slots=True)
class ThreeStageSolution:
    lambda_closed_form: Fraction
    lambda_lp: float
    stage1: StageSolution
    stage2: StageSolution
    stage3: StageSolution


def weighted_coefficients(
    model: Benchmark, records: tuple[tuple[str, str], ...]
) -> np.ndarray:
    weights = model.weight_by_user
    return np.asarray(
        [float(weights[user] * model.demand[period][user]) for period, user in records],
        dtype=float,
    )


def weighted_satisfaction(model: Benchmark, ratios: dict[tuple[str, str], float]) -> float:
    weights = model.weight_by_user
    numerator = 0.0
    denominator = 0.0
    for period, user in model.active_records:
        coeff = float(weights[user] * model.demand[period][user])
        numerator += coeff * ratios[(period, user)]
        denominator += coeff
    return numerator / denominator if denominator > 0 else 1.0


def temporal_pairs(model: Benchmark) -> tuple[tuple[tuple[str, str], tuple[str, str]], ...]:
    active = set(model.active_records)
    pairs: list[tuple[tuple[str, str], tuple[str, str]]] = []
    for user in model.user_ids:
        for prev, current in zip(model.periods[:-1], model.periods[1:]):
            left = (prev, user)
            right = (current, user)
            if left in active and right in active:
                pairs.append((left, right))
    return tuple(pairs)


def temporal_variation(model: Benchmark, ratios: dict[tuple[str, str], float]) -> float:
    return float(sum(abs(ratios[right] - ratios[left]) for left, right in temporal_pairs(model)))


def _make_solution(
    name: str,
    model: Benchmark,
    ratios: dict[tuple[str, str], float],
    objective_value: float,
    status: int,
    message: str,
) -> StageSolution:
    return StageSolution(
        name=name,
        ratios=ratios,
        objective_value=float(objective_value),
        weighted_satisfaction=weighted_satisfaction(model, ratios),
        minimum_ratio=min(ratios.values()) if ratios else 1.0,
        temporal_variation=temporal_variation(model, ratios),
        status=status,
        message=message,
    )


def solve_three_stage(
    model: Benchmark,
    feasibility_tolerance: float = 1e-9,
    preservation_tolerance: float = 1e-8,
) -> ThreeStageSolution:
    closed_form = solve_stage1_closed_form(model)
    stage1_lp = solve_stage1_lp(model, feasibility_tolerance=feasibility_tolerance)
    lambda_star = float(closed_form.lambda_star)
    records = model.active_records
    record_index = {record: idx for idx, record in enumerate(records)}
    physical_a, physical_b, _ = physical_matrices(model)
    weighted = weighted_coefficients(model, records)

    canonical_ratios = {record: lambda_star for record in records}
    stage1 = _make_solution(
        "Stage 1",
        model,
        canonical_ratios,
        lambda_star,
        stage1_lp.status,
        stage1_lp.message,
    )

    result2 = linprog(
        -weighted,
        A_ub=physical_a,
        b_ub=physical_b,
        bounds=[(lambda_star, 1.0)] * len(records),
        method="highs",
        options={
            "primal_feasibility_tolerance": feasibility_tolerance,
            "dual_feasibility_tolerance": feasibility_tolerance,
        },
    )
    if not result2.success:
        raise RuntimeError(f"Stage 2 failed: {result2.message}")
    ratios2 = {record: float(result2.x[idx]) for idx, record in enumerate(records)}
    weighted_objective = float(weighted @ result2.x)
    stage2 = _make_solution(
        "Stage 2",
        model,
        ratios2,
        weighted_objective,
        int(result2.status),
        str(result2.message),
    )

    pairs = temporal_pairs(model)
    n = len(records)
    p = len(pairs)
    objective3 = np.concatenate([np.zeros(n), np.ones(p)])
    rows: list[np.ndarray] = []
    rhs: list[float] = []

    for row, bound in zip(physical_a, physical_b):
        rows.append(np.concatenate([row, np.zeros(p)]))
        rhs.append(float(bound))

    # Stage-2 objective preservation, model Eq. (24): S(r) = theta*.
    # This MUST be an exact equality. The earlier one-sided relaxation
    # ``weighted @ r >= W* - eps`` let Stage 3 spend the eps slack to drop the
    # weighted delivery just below the true optimum and thereby report a
    # temporal variation *below* the true minimum (e.g. 0.39999997... instead
    # of exactly 0.40) and a Stage-3 satisfaction *below* Stage 2. Encoding it
    # as an A_eq row removes that leak so Stage 3 optimises strictly inside the
    # exact Stage-2 optimal face.
    eq_rows = [np.concatenate([weighted, np.zeros(p)])]
    eq_rhs = [weighted_objective]

    for pair_idx, (left, right) in enumerate(pairs):
        row_pos = np.zeros(n + p)
        row_pos[record_index[right]] = 1.0
        row_pos[record_index[left]] = -1.0
        row_pos[n + pair_idx] = -1.0
        rows.append(row_pos)
        rhs.append(0.0)

        row_neg = np.zeros(n + p)
        row_neg[record_index[left]] = 1.0
        row_neg[record_index[right]] = -1.0
        row_neg[n + pair_idx] = -1.0
        rows.append(row_neg)
        rhs.append(0.0)

    result3 = linprog(
        objective3,
        A_ub=np.vstack(rows),
        b_ub=np.asarray(rhs, dtype=float),
        A_eq=np.vstack(eq_rows),
        b_eq=np.asarray(eq_rhs, dtype=float),
        bounds=[(lambda_star, 1.0)] * n + [(0.0, None)] * p,
        method="highs",
        options={
            "primal_feasibility_tolerance": feasibility_tolerance,
            "dual_feasibility_tolerance": feasibility_tolerance,
        },
    )
    if not result3.success:
        raise RuntimeError(f"Stage 3 failed: {result3.message}")
    ratios3 = {record: float(result3.x[idx]) for idx, record in enumerate(records)}
    stage3 = _make_solution(
        "Stage 3",
        model,
        ratios3,
        float(result3.fun),
        int(result3.status),
        str(result3.message),
    )

    if abs(stage1_lp.lambda_star - lambda_star) > 5e-7:
        raise AssertionError("Closed-form and LP Stage-1 values disagree.")
    if stage3.minimum_ratio + 5e-7 < lambda_star:
        raise AssertionError("Stage 3 violates the Stage-1 floor.")
    if (
        abs(stage3.weighted_satisfaction - stage2.weighted_satisfaction)
        > preservation_tolerance
    ):
        raise AssertionError(
            "Stage 3 fails to preserve the Stage-2 optimum within the "
            "declared numerical tolerance."
        )
    if stage3.temporal_variation > stage2.temporal_variation + 5e-7:
        raise AssertionError("Stage 3 increases temporal variation.")

    return ThreeStageSolution(closed_form.lambda_star, stage1_lp.lambda_star, stage1, stage2, stage3)
