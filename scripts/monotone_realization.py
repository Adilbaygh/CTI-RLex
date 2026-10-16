"""Can the reported deliveries be made monotone in scenario availability? (Reviewer 3, point 3)

The manuscript reported that in a few cells a contingency scenario delivers more than the
nominal one, and said that "a further deterministic tie-break would remove that behavior
without touching the guarantee vector". A reviewer rightly answered that this was not shown,
and that non-nested scenarios need not admit an availability ordering at all. This script
defines the ordering, finds the scenario pairs it applies to, and tests the claim instead of
asserting it.

Availability ordering. Scenario s is nested in scenario t (s <= t) when, in every period,
every reach capacity and efficiency, every source limit and every shared envelope of s is no
larger than in t, and every seasonal source limit of s is no larger than in t. Demand does
not depend on the scenario. Recourse budgets are not part of the ordering: they bound how far
a contingency plan may move away from the nominal one, not how much water there is, and they
are reported beside each pair.

Monotone realization. For every nested pair s <= t, every claimant terminal and every period,
the beneficial delivery in s does not exceed that in t.

Three questions, in order, each asked only when the one before is answered no:
  (a) Does the published optimal face -- the guarantee vector fixed, both delivery optima and
      the recourse effort preserved within the solver's tolerance -- contain a monotone
      realization? The total violation is minimized over the face; zero means a selection
      rule exists that changes nothing reported except the per-cell schedule.
  (b) If not, is the published guarantee vector compatible with monotonicity at all? The
      delivery stages are re-solved with the monotonicity constraints imposed and the
      guarantee vector fixed, and the price is reported in acre-feet of nominal and weighted
      contingency delivery.
  (c) If not even that, what does the lexicographic vector become when monotonicity is
      imposed in every program of the sequence?

Run:  python scripts/monotone_realization.py
Writes: results/monotone_realization.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import csr_matrix, hstack, identity, vstack

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from leximin.dag import OptimizationError, load_cti_benchmark, solve_cti_rlex  # noqa: E402
from leximin.dag import solver as solver_module  # noqa: E402
from leximin.dag.experiments import (  # noqa: E402
    contingency_delivery_objective,
    nominal_delivery_objective,
    recourse_objective,
)
from leximin.dag.lp import HIGHS_OPTIONS, build_lp, objective_value, run_lp  # noqa: E402

OUTPUT = REPO / "results" / "monotone_realization.json"
INSTANCES = {
    "little_bear_v2": REPO / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json",
    "cache_valley_v4": REPO / "DATA" / "CacheValley_2025_Benchmark" / "benchmark.json",
}
PRESERVATION = 1e-7
ORDER_TOLERANCE = 1e-9
VIOLATION_TOLERANCE = 1e-6   # acre-feet per cell, relative to max(1, delivery)


def nested(model, smaller: str, larger: str) -> bool:
    def no_larger(table, index_of_scenario=0) -> bool:
        for key, value in table.items():
            if key[index_of_scenario] != smaller:
                continue
            other = (larger,) + tuple(key[1:])
            if value > table[other] + ORDER_TOLERANCE * max(1.0, abs(table[other])):
                return False
        return True

    return all(
        no_larger(table)
        for table in (model.edge_capacity, model.edge_efficiency, model.source_limit,
                      model.source_seasonal_limit, model.shared_source_limit)
    )


def ordered_pairs(model) -> list[tuple[str, str]]:
    return [
        (smaller, larger)
        for smaller in model.scenarios
        for larger in model.scenarios
        if smaller != larger and nested(model, smaller, larger)
    ]


def monotonicity_rows(model, pairs) -> list[tuple[dict, float]]:
    return [
        ({("x", smaller, period, terminal.terminal_id): 1.0, ("x", larger, period, terminal.terminal_id): -1.0}, 0.0)
        for smaller, larger in pairs
        for period in model.periods
        for terminal in model.terminals
    ]


def published_violations(model, solution, pairs) -> list[dict]:
    rows = []
    for smaller, larger in pairs:
        excess = []
        for period in model.periods:
            for terminal in model.terminals:
                a = solution.beneficial_delivery[smaller, period, terminal.terminal_id]
                b = solution.beneficial_delivery[larger, period, terminal.terminal_id]
                if a - b > VIOLATION_TOLERANCE * max(1.0, abs(b)):
                    excess.append(a - b)
        rows.append({
            "smaller": smaller, "larger": larger,
            "budget_smaller": model.recourse_budget[smaller], "budget_larger": model.recourse_budget[larger],
            "cells_violating": len(excess),
            "total_excess_af": sum(excess),
            "largest_excess_af": max(excess, default=0.0),
        })
    return rows


def preservation_rows(model, solution) -> tuple:
    def floor(value: float) -> float:
        return value - PRESERVATION * max(1.0, abs(value))

    nominal = nominal_delivery_objective(model)
    contingency = contingency_delivery_objective(model)
    return (
        ({key: -c for key, c in nominal.items()}, -floor(solution.nominal_beneficial_delivery)),
        ({key: -c for key, c in contingency.items()}, -floor(solution.weighted_contingency_beneficial_delivery)),
        (recourse_objective(model),
         solution.normalized_recourse_effort + PRESERVATION * max(1.0, abs(solution.normalized_recourse_effort))),
    )


def least_violation_on_face(model, solution, pairs) -> float:
    """Minimize the total monotonicity violation over the published optimal face."""

    face = build_lp(model, {}, maximize=False, fixed_rho=dict(solution.guarantees),
                    extra_ub=preservation_rows(model, solution))
    rows = monotonicity_rows(model, pairs)
    if not rows:
        return 0.0
    columns = len(face.keys)
    data, row_index, column_index = [], [], []
    for r, (coefficients, _rhs) in enumerate(rows):
        for key, value in coefficients.items():
            row_index.append(r)
            column_index.append(face.index[key])
            data.append(value)
    difference = csr_matrix((data, (row_index, column_index)), shape=(len(rows), columns))
    slack = len(rows)
    a_ub = vstack([hstack([face.a_ub, csr_matrix((face.a_ub.shape[0], slack))]),
                   hstack([difference, -identity(slack, format="csr")])]).tocsr()
    b_ub = np.concatenate([face.b_ub, np.zeros(slack)])
    a_eq = hstack([face.a_eq, csr_matrix((face.a_eq.shape[0], slack))]).tocsr()
    c = np.concatenate([np.zeros(columns), np.ones(slack)])
    result = linprog(c=c, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=face.b_eq,
                     bounds=list(face.bounds) + [(0.0, None)] * slack, method="highs",
                     options=dict(HIGHS_OPTIONS))
    if not result.success:
        raise OptimizationError(f"least-violation LP failed: {result.message}")
    return float(result.fun)


def delivery_stages_with(model, guarantees, rows):
    """The solver's three secondary stages with extra rows, the guarantee vector fixed."""

    nominal = nominal_delivery_objective(model)
    problem = build_lp(model, nominal, maximize=True, fixed_rho=dict(guarantees), extra_ub=rows)
    nominal_value = objective_value(problem, run_lp(problem))
    keep_nominal = ({key: -c for key, c in nominal.items()},
                    -(nominal_value - PRESERVATION * max(1.0, abs(nominal_value))))
    contingency = contingency_delivery_objective(model)
    problem = build_lp(model, contingency, maximize=True, fixed_rho=dict(guarantees),
                       extra_ub=tuple(rows) + (keep_nominal,))
    contingency_value = objective_value(problem, run_lp(problem))
    keep_contingency = ({key: -c for key, c in contingency.items()},
                        -(contingency_value - PRESERVATION * max(1.0, abs(contingency_value))))
    problem = build_lp(model, recourse_objective(model), maximize=False, fixed_rho=dict(guarantees),
                       extra_ub=tuple(rows) + (keep_nominal, keep_contingency))
    effort_value = objective_value(problem, run_lp(problem))
    return nominal_value, contingency_value, effort_value


def lexicographic_vector_with(model, rows):
    original = solver_module.build_lp

    def with_rows(*args, extra_ub=(), **kwargs):
        return original(*args, extra_ub=tuple(extra_ub) + tuple(rows), **kwargs)

    solver_module.build_lp = with_rows
    try:
        return solve_cti_rlex(model)
    finally:
        solver_module.build_lp = original


def main() -> None:
    report = {"preservation_tolerance": PRESERVATION, "violation_tolerance": VIOLATION_TOLERANCE, "instances": {}}
    for name, path in INSTANCES.items():
        model = load_cti_benchmark(path)
        solution = solve_cti_rlex(model)
        pairs = ordered_pairs(model)
        unordered = [
            [a, b] for i, a in enumerate(model.scenarios) for b in model.scenarios[i + 1:]
            if (a, b) not in pairs and (b, a) not in pairs
        ]
        entry = {
            "scenarios": list(model.scenarios),
            "recourse_budgets": dict(model.recourse_budget),
            "nested_pairs": [list(pair) for pair in pairs],
            "pairs_with_no_availability_order": unordered,
            "published_violations": published_violations(model, solution, pairs),
        }
        entry["published_cells_violating"] = sum(row["cells_violating"] for row in entry["published_violations"])
        least = least_violation_on_face(model, solution, pairs)
        entry["least_total_violation_on_the_published_face_af"] = least
        entry["a_monotone_realization_exists_on_the_published_face"] = least <= VIOLATION_TOLERANCE * max(
            1.0, solution.nominal_beneficial_delivery)
        if not entry["a_monotone_realization_exists_on_the_published_face"]:
            rows = monotonicity_rows(model, pairs)
            try:
                nominal_value, contingency_value, effort_value = delivery_stages_with(model, solution.guarantees, rows)
                entry["with_the_published_guarantee_vector"] = {
                    "feasible": True,
                    "nominal_delivery_af": nominal_value,
                    "nominal_delivery_cost_af": solution.nominal_beneficial_delivery - nominal_value,
                    "nominal_delivery_cost_pct": 100.0 * (solution.nominal_beneficial_delivery - nominal_value)
                    / solution.nominal_beneficial_delivery,
                    "weighted_contingency_delivery_af": contingency_value,
                    "weighted_contingency_delivery_cost_af":
                        solution.weighted_contingency_beneficial_delivery - contingency_value,
                    "recourse_effort": effort_value,
                }
            except OptimizationError as error:
                entry["with_the_published_guarantee_vector"] = {"feasible": False, "reason": str(error)}
                monotone = lexicographic_vector_with(model, rows)
                published_sorted = sorted(solution.guarantees.values())
                monotone_sorted = sorted(monotone.guarantees.values())
                first = next((i + 1 for i, (a, b) in enumerate(zip(published_sorted, monotone_sorted))
                              if abs(a - b) > 1e-7), None)
                entry["lexicographic_vector_under_monotonicity"] = {
                    "guarantees": dict(monotone.guarantees),
                    "sorted": monotone_sorted,
                    "first_position_that_differs_from_the_published_vector": first,
                    "nominal_delivery_af": monotone.nominal_beneficial_delivery,
                }
        report["instances"][name] = entry
        print(f"{name}: {len(pairs)} nested pairs {pairs}; no order between {unordered}")
        print(f"  published solution: {entry['published_cells_violating']} cells violate monotonicity")
        print(f"  least total violation on the published face: {least:.6g} af -> monotone realization exists: "
              f"{entry['a_monotone_realization_exists_on_the_published_face']}")
        if "with_the_published_guarantee_vector" in entry:
            print(f"  with the guarantee vector fixed: {entry['with_the_published_guarantee_vector']}")
        if "lexicographic_vector_under_monotonicity" in entry:
            print(f"  lexicographic vector under monotonicity: {entry['lexicographic_vector_under_monotonicity']['sorted']}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
