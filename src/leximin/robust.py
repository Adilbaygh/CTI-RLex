"""Solver-independent (invariant) diagnostics for the lexicographic model.

The single-vertex Stage-2 temporal variation reported by :mod:`lexicographic`
is *not* an invariant of the problem: Stage 2 is degenerate, so its optimal
face contains many extreme points and different LP solvers (or the same solver
after a version bump) return different ones with different temporal variation
Omega. Reporting one such value -- and a "reduction" computed from it -- is not
reproducible.

This module computes quantities that depend only on the model, not on solver
pivoting:

* ``stage2_variation_bounds`` -- the range ``[Omega_min, Omega_max]`` of the
  temporal variation over the *entire* Stage-2 optimal face. ``Omega_min`` is
  the value Stage 3 attains; ``Omega_max`` is the largest variation on that
  face.  The ratio ``(Omega_max - Omega_min) / Omega_max`` is a worst-to-best
  range reduction, not a guaranteed reduction from an arbitrary Stage-2 point.
* ``price_of_fairness`` -- how much total net delivery the Stage-1 max-min
  guarantee costs relative to the pure-efficiency optimum.
* ``solve_leximin`` -- the full lexicographic max-min (leximin) allocation by
  exact progressive filling; unlike Stage 1 it is a single,
  solver-independent vector on the model's convex packing set.

Every routine here uses only physical capacities, demands, efficiencies and the
exact Stage-1 floor, so its output is reproducible across solvers.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from fractions import Fraction

import numpy as np
from scipy.optimize import linprog

from .domain import Benchmark
from .lexicographic import temporal_pairs, weighted_coefficients
from .stage1 import physical_matrices, solve_stage1_closed_form

_HIGHS = {"primal_feasibility_tolerance": 1e-9, "dual_feasibility_tolerance": 1e-9}


def _rationalize(value: float, max_den: int = 10**6, tol: float = 1e-7) -> Fraction | None:
    """Return the simplest rational within ``tol`` of ``value`` (or ``None``)."""
    candidate = Fraction(value).limit_denominator(max_den)
    return candidate if abs(float(candidate) - value) <= tol else None


@dataclass(frozen=True, slots=True)
class VariationBounds:
    omega_min: float
    omega_max: float
    worst_to_best_reduction_fraction: float
    omega_min_exact: Fraction | None
    omega_max_exact: Fraction | None
    enumerated_pairs: int

    @property
    def reduction_fraction(self) -> float:
        """Backward-compatible alias for the old, misleading field name."""
        return self.worst_to_best_reduction_fraction


def stage2_optimum(model: Benchmark) -> tuple[float, np.ndarray, np.ndarray, tuple]:
    """Return the Stage-2 optimal weighted-delivery value W* and matrices."""
    physical_a, physical_b, records = physical_matrices(model)
    weighted = weighted_coefficients(model, records)
    lam = float(solve_stage1_closed_form(model).lambda_star)
    res = linprog(
        -weighted, A_ub=physical_a, b_ub=physical_b,
        bounds=[(lam, 1.0)] * len(records), method="highs", options=_HIGHS,
    )
    if not res.success:
        raise RuntimeError(f"Stage-2 optimum failed: {res.message}")
    return float(weighted @ res.x), physical_a, physical_b, records


def stage2_variation_bounds(
    model: Benchmark, max_pairs: int = 14
) -> VariationBounds | None:
    """Extremes of temporal variation over the exact Stage-2 optimal face.

    ``Omega = sum |r_right - r_left|`` is convex. Its maximum over the compact
    Stage-2 polytope is attained at at least one vertex; its minimum need not be
    a vertex in the original ratio space. We obtain ``Omega_max`` by maximising
    every signed linearisation ``sum s_i (r_right - r_left)``
    (``s in {+1,-1}^p``) and taking the best; ``Omega_min`` by the standard
    z-linearisation. Returns ``None``
    (with no silent guess) when the number of consecutive-active pairs ``p``
    exceeds ``max_pairs`` and the 2**p enumeration would be too large.
    """
    pairs = temporal_pairs(model)
    p = len(pairs)
    if p == 0:
        return VariationBounds(0.0, 0.0, 0.0, Fraction(0), Fraction(0), 0)
    if p > max_pairs:
        return None

    wstar, physical_a, physical_b, records = stage2_optimum(model)
    n = len(records)
    lam = float(solve_stage1_closed_form(model).lambda_star)
    index = {rec: i for i, rec in enumerate(records)}
    weighted = weighted_coefficients(model, records)
    bounds = [(lam, 1.0)] * n

    def omega(x: np.ndarray) -> float:
        return float(sum(abs(x[index[r]] - x[index[l]]) for l, r in pairs))

    # Omega_min: minimise sum z, z >= |r_r - r_l|, on the exact face.
    obj = np.concatenate([np.zeros(n), np.ones(p)])
    rows, rhs = [], []
    for row, bound in zip(physical_a, physical_b):
        rows.append(np.concatenate([row, np.zeros(p)]))
        rhs.append(float(bound))
    for i, (left, right) in enumerate(pairs):
        z = np.zeros(n + p); z[index[right]] = 1.0; z[index[left]] = -1.0; z[n + i] = -1.0
        rows.append(z); rhs.append(0.0)
        z = np.zeros(n + p); z[index[left]] = 1.0; z[index[right]] = -1.0; z[n + i] = -1.0
        rows.append(z); rhs.append(0.0)
    eq = np.concatenate([weighted, np.zeros(p)])
    res_min = linprog(
        obj, A_ub=np.vstack(rows), b_ub=np.asarray(rhs, float),
        A_eq=[eq], b_eq=[wstar], bounds=bounds + [(0.0, None)] * p,
        method="highs", options=_HIGHS,
    )
    if not res_min.success:
        raise RuntimeError(f"Omega_min failed: {res_min.message}")
    omega_min = float(res_min.fun)

    # Omega_max: best signed linearisation over the same face.
    omega_max = 0.0
    for signs in itertools.product((1.0, -1.0), repeat=p):
        c = np.zeros(n)
        for (left, right), s in zip(pairs, signs):
            c[index[right]] -= s
            c[index[left]] += s
        res = linprog(
            c, A_ub=physical_a, b_ub=physical_b, A_eq=[weighted], b_eq=[wstar],
            bounds=bounds, method="highs", options=_HIGHS,
        )
        if res.success:
            omega_max = max(omega_max, omega(res.x))

    reduction = (omega_max - omega_min) / omega_max if omega_max > 0 else 0.0
    return VariationBounds(
        omega_min, omega_max, reduction,
        _rationalize(omega_min), _rationalize(omega_max), p,
    )


@dataclass(frozen=True, slots=True)
class PriceOfFairness:
    efficiency_optimum: float          # Z_eff^w: max weighted delivery, no floor
    fair_delivery: float               # Z_fair^w: weighted delivery under the floor
    price_of_fairness: float           # 1 - Z_fair / Z_eff


def price_of_fairness(model: Benchmark) -> PriceOfFairness:
    """Weighted-delivery cost of the Stage-1 max-min guarantee.

    ``Z_eff^w`` maximises ``sum w_f d_kf r_kf`` with the physical capacities but
    *no* fairness floor (``r in [0, 1]``); ``Z_fair^w`` maximises the same
    objective under the Stage-1 floor.  Using the same weights in both problems
    is essential: otherwise the quotient compares different objectives.
    """
    physical_a, physical_b, records = physical_matrices(model)
    weighted = weighted_coefficients(model, records)
    lam = float(solve_stage1_closed_form(model).lambda_star)

    res_eff = linprog(
        -weighted, A_ub=physical_a, b_ub=physical_b,
        bounds=[(0.0, 1.0)] * len(records), method="highs", options=_HIGHS,
    )
    res_fair = linprog(
        -weighted, A_ub=physical_a, b_ub=physical_b,
        bounds=[(lam, 1.0)] * len(records), method="highs", options=_HIGHS,
    )
    if not (res_eff.success and res_fair.success):
        raise RuntimeError("Price-of-fairness LP failed.")
    z_eff = float(weighted @ res_eff.x)
    z_fair = float(weighted @ res_fair.x)
    pof = 1.0 - z_fair / z_eff if z_eff > 0 else 0.0
    return PriceOfFairness(z_eff, z_fair, pof)


@dataclass(frozen=True, slots=True)
class LeximinSolution:
    ratios: dict[tuple[str, str], float]
    levels: tuple[float, ...]              # distinct max-min levels, in freeze order
    minimum_ratio: float
    weighted_satisfaction: float
    temporal_variation: float


def solve_leximin(
    model: Benchmark,
    max_records: int | None = 64,
) -> LeximinSolution:
    """Return the exact progressive-filling leximin allocation.

    The physical feasible set is a downward-closed packing polytope ``H r <= c``
    with ``H >= 0``.  At every round all unfrozen coordinates can therefore be
    raised to the common exact level

    ``min_j (c_j - sum_fixed h_ji r_i) / sum_free h_ji``.

    Every free coordinate using a resource that attains this minimum is blocked
    and is frozen at that level.  The calculation uses :class:`Fraction`
    throughout, so it needs neither repeated LP freeze tests nor numerical
    slack.  Convexity of the packing set makes the resulting leximin vector
    unique. ``max_records`` remains only as an optional caller-controlled guard.
    """
    from .operators import build_operator_exact

    records = model.active_records
    n = len(records)
    if max_records is not None and n > max_records:
        raise ValueError(
            f"Leximin refused: {n} active records exceeds max_records={max_records}. "
            "Raise max_records explicitly to compute it."
        )
    index = {record: idx for idx, record in enumerate(records)}
    a_coeff, b_coeff = build_operator_exact(model)
    rows: list[tuple[Fraction, dict[int, Fraction]]] = []
    for period in model.periods:
        source_row = {
            index[(period, user.user_id)]: (
                b_coeff[(period, user.user_id)]
                * model.demand[period][user.user_id]
            )
            for user in model.users
            if (period, user.user_id) in index
        }
        rows.append((model.source_capacity[period], source_row))
        for edge_id in model.edge_ids:
            edge_row = {
                index[(period, user.user_id)]: (
                    a_coeff[(period, edge_id, user.user_id)]
                    * model.demand[period][user.user_id]
                )
                for user in model.users
                if (period, user.user_id) in index
                and a_coeff[(period, edge_id, user.user_id)] > 0
            }
            rows.append((model.edge_capacity[period][edge_id], edge_row))

    fixed: dict[int, Fraction] = {}
    free = set(range(n))
    levels_exact: list[Fraction] = []
    while free:
        candidates: list[tuple[Fraction, dict[int, Fraction]]] = []
        for capacity, coefficients in rows:
            denominator = sum(
                (coefficients.get(idx, Fraction(0)) for idx in free),
                Fraction(0),
            )
            if denominator <= 0:
                continue
            used_by_fixed = sum(
                (
                    coefficients.get(idx, Fraction(0)) * value
                    for idx, value in fixed.items()
                ),
                Fraction(0),
            )
            candidates.append(((capacity - used_by_fixed) / denominator, coefficients))

        level = min(
            [Fraction(1)] + [candidate for candidate, _ in candidates]
        )
        if levels_exact and level < levels_exact[-1]:
            raise RuntimeError("Leximin level decreased; the packing model is inconsistent.")
        if not (Fraction(0) <= level <= Fraction(1)):
            raise RuntimeError("Leximin level lies outside [0, 1].")
        levels_exact.append(level)

        if level == 1:
            newly_frozen = set(free)
        else:
            binding_rows = [
                coefficients
                for candidate, coefficients in candidates
                if candidate == level
            ]
            newly_frozen = {
                idx
                for idx in free
                if any(coefficients.get(idx, Fraction(0)) > 0 for coefficients in binding_rows)
            }
        if not newly_frozen:
            raise RuntimeError("Leximin progressive filling found no blocked record.")
        for idx in newly_frozen:
            fixed[idx] = level
        free.difference_update(newly_frozen)

    ratios = {rec: float(fixed[index[rec]]) for rec in records}
    levels = [float(value) for value in levels_exact]

    weights = model.weight_by_user
    num = den = 0.0
    for (k, f) in records:
        c = float(weights[f] * model.demand[k][f])
        num += c * ratios[(k, f)]; den += c
    weighted_sat = num / den if den > 0 else 1.0
    variation = float(
        sum(abs(ratios[r] - ratios[l]) for l, r in temporal_pairs(model))
    )
    return LeximinSolution(
        ratios=ratios,
        levels=tuple(levels),
        minimum_ratio=min(ratios.values()) if ratios else 1.0,
        weighted_satisfaction=weighted_sat,
        temporal_variation=variation,
    )
