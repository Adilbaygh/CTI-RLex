"""Numerical certificates for the progressive-filling sequence (Reviewer 3, point 1).

The manuscript said that, with a blocking tolerance of 1e-7, a level frozen at a round "can
differ from the exact one by at most that amount". The tolerance alone does not establish
that bound: each frozen level is the optimum of a linear program solved to a feasibility
tolerance, the blocking test compares two such optima, and every later round inherits the
levels frozen before it. This script replaces the claim with measurements, on both released
benchmarks.

1. Certificates. Every linear program the solver solves at the published settings is kept
   with its primal objective, the dual objective assembled from the HiGHS marginals, the
   primal-dual gap, the primal residuals, the dual (stationarity) residual and the largest
   sign violation of the dual variables.
2. Tolerance grid. The blocking tolerance, the HiGHS primal and dual feasibility tolerances
   (moved together) and the preservation tolerance of the secondary stages each take the
   values 1e-5 to 1e-9, in all 125 combinations; the guarantee vector, the level structure
   and the secondary objectives are compared with the published solution. A point at which
   HiGHS returns no optimum for some program is solved again with that program, and every
   later one, passed down the fallback sequence of scripts/flow_uniqueness.py (presolve off,
   then the interior-point method, then dual simplex under Dantzig pricing), and the result
   is reported beside the failure: it shows whether the failure hides a different vector or
   only a program HiGHS cannot finish at that tolerance with presolve on. A point at which
   progressive filling itself stops -- no claimant blocked -- is a property of the tolerance,
   not of one program, and is not retried.
3. Near-tied levels. The demand of the claimant on the second level is scaled so that its
   level lies a chosen distance above the lowest one, from 1e-3 down to 1e-9. The distance
   the solver actually faces is measured from its own first-round programs, and the run
   reports whether the two levels were separated or merged.
4. The distance between the closest distinct levels of each published solution, which is
   what the blocking tolerance has to resolve in practice.

Run:  python scripts/numerical_certificates.py
Writes: results/numerical_certificates.json
"""

from __future__ import annotations

import itertools
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from leximin.dag import OptimizationError, load_cti_benchmark, solve_cti_rlex  # noqa: E402
from leximin.dag import lp as lp_module  # noqa: E402
from leximin.dag import solver as solver_module  # noqa: E402
from leximin.dag.lp import generic_residuals  # noqa: E402
from flow_uniqueness import robust_linprog  # noqa: E402

OUTPUT = REPO / "results" / "numerical_certificates.json"
INSTANCES = {
    "little_bear_v2": REPO / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json",
    "cache_valley_v4": REPO / "DATA" / "CacheValley_2025_Benchmark" / "benchmark.json",
}
GRID = (1e-5, 1e-6, 1e-7, 1e-8, 1e-9)
PUBLISHED = 1e-7
NEAR_TIE_DISTANCES = (1e-3, 1e-4, 1e-5, 1e-6, 1e-7, 1e-8, 1e-9)


class Recorder:
    """Keep every linear program the solver solves, with its result, while active."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, object]] = []
        self._original = solver_module.run_lp

    def __enter__(self) -> "Recorder":
        def recording(problem):
            result = self._original(problem)
            self.calls.append((problem, result))
            return result

        solver_module.run_lp = recording
        return self

    def __exit__(self, *_exc) -> bool:
        solver_module.run_lp = self._original
        return False


def stage_of(model, problem) -> tuple[str, str | None]:
    """Which step of the sequence a program is, read from its objective."""

    keys = [problem.keys[index] for index in np.flatnonzero(problem.objective)]
    families = {key[0] for key in keys}
    if families == {"theta"}:
        return "level", None
    if families == {"rho"}:
        return "blocking_test", keys[0][1]
    if families == {"x"}:
        scenarios = {key[1] for key in keys}
        return ("nominal_delivery" if scenarios == {model.nominal_scenario} else "contingency_delivery"), None
    if families == {"u"}:
        return "recourse_effort", None
    return "other", None


def certificate(problem, result) -> dict:
    """Primal and dual objective of one solved program, in the minimization form HiGHS saw."""

    x = result.x
    primal = float(problem.c @ x)
    y_ub = np.asarray(result.ineqlin.marginals) if problem.b_ub.size else np.zeros(0)
    y_eq = np.asarray(result.eqlin.marginals) if problem.b_eq.size else np.zeros(0)
    lower = np.array([np.nan if bound[0] is None else float(bound[0]) for bound in problem.bounds])
    upper = np.array([np.nan if bound[1] is None else float(bound[1]) for bound in problem.bounds])
    m_lower = np.asarray(result.lower.marginals)
    m_upper = np.asarray(result.upper.marginals)
    dual = float(
        problem.b_ub @ y_ub
        + problem.b_eq @ y_eq
        + np.nan_to_num(lower) @ m_lower
        + np.nan_to_num(upper) @ m_upper
    )
    stationarity = problem.c - (problem.a_ub.T @ y_ub + problem.a_eq.T @ y_eq + m_lower + m_upper)
    sign_violation = max(
        0.0,
        float(np.max(y_ub, initial=0.0)),       # inequality rows are <=, so their marginals are <= 0
        float(-np.min(m_lower, initial=0.0)),   # lower-bound marginals are >= 0
        float(np.max(m_upper, initial=0.0)),    # upper-bound marginals are <= 0
    )
    gap = abs(primal - dual)
    residuals = generic_residuals(problem, result)
    return {
        "primal_objective": primal,
        "dual_objective": dual,
        "absolute_gap": gap,
        "relative_gap": gap / max(1.0, abs(primal)),
        "max_primal_residual": max(residuals.values(), default=0.0),
        "max_dual_residual": float(np.max(np.abs(stationarity), initial=0.0)),
        "max_dual_sign_violation": sign_violation,
        "iterations": int(getattr(result, "nit", -1)),
    }


def certificates(model) -> dict:
    with Recorder() as recorder:
        solution = solve_cti_rlex(model)
    rows = []
    level_round = 0
    for problem, result in recorder.calls:
        stage, claimant = stage_of(model, problem)
        if stage == "level":
            level_round += 1
        rows.append({"stage": stage, "round": level_round, "claimant": claimant, **certificate(problem, result)})
    return {
        "linear_programs": len(rows),
        "max_absolute_gap": max(row["absolute_gap"] for row in rows),
        "max_relative_gap": max(row["relative_gap"] for row in rows),
        "max_primal_residual": max(row["max_primal_residual"] for row in rows),
        "max_dual_residual": max(row["max_dual_residual"] for row in rows),
        "max_dual_sign_violation": max(row["max_dual_sign_violation"] for row in rows),
        "rows": rows,
    }, solution


def solve_with(model, blocking: float, feasibility: float, preservation: float):
    saved = dict(lp_module.HIGHS_OPTIONS)
    lp_module.HIGHS_OPTIONS["primal_feasibility_tolerance"] = feasibility
    lp_module.HIGHS_OPTIONS["dual_feasibility_tolerance"] = feasibility
    try:
        return solve_cti_rlex(model, blocking_tolerance=blocking, preservation_tolerance=preservation)
    finally:
        lp_module.HIGHS_OPTIONS.clear()
        lp_module.HIGHS_OPTIONS.update(saved)


def structure(solution) -> list[list[str]]:
    return [sorted(level.blocked_claimants) for level in solution.leximin_levels]


def retry_with_fallbacks(model, published, blocking: float, feasibility: float, preservation: float) -> dict:
    """Solve a failed grid point again, every program passed down the fallback sequence."""

    original = solver_module.run_lp
    fallbacks: dict[str, int] = {}

    def robust(problem):
        return robust_linprog(fallbacks, c=problem.c, A_ub=problem.a_ub, b_ub=problem.b_ub,
                              A_eq=problem.a_eq, b_eq=problem.b_eq, bounds=problem.bounds)

    solver_module.run_lp = robust
    try:
        solution = solve_with(model, blocking, feasibility, preservation)
    except (OptimizationError, ValueError) as error:
        return {"completed": False, "failed": f"{type(error).__name__}: {error}", "fallbacks": fallbacks}
    finally:
        solver_module.run_lp = original
    return {
        "completed": True,
        "fallbacks": fallbacks,
        "max_guarantee_shift": max(abs(solution.guarantees[c] - published.guarantees[c]) for c in model.claimants),
        "same_level_structure": structure(solution) == structure(published),
        "same_at_four_decimals": all(
            f"{solution.guarantees[c]:.4f}" == f"{published.guarantees[c]:.4f}" for c in model.claimants
        ),
    }


def tolerance_grid(model, published) -> dict:
    rows = []
    for blocking, feasibility, preservation in itertools.product(GRID, GRID, GRID):
        row = {"blocking_tolerance": blocking, "lp_feasibility_tolerance": feasibility,
               "preservation_tolerance": preservation}
        try:
            solution = solve_with(model, blocking, feasibility, preservation)
        except (OptimizationError, ValueError) as error:
            failed = {**row, "failed": f"{type(error).__name__}: {error}"}
            if "no blocked claimant" not in str(error):
                failed["retried_with_fallbacks"] = retry_with_fallbacks(
                    model, published, blocking, feasibility, preservation
                )
            rows.append(failed)
            continue
        shift = max(abs(solution.guarantees[c] - published.guarantees[c]) for c in model.claimants)
        rows.append({
            **row,
            "guarantees": dict(solution.guarantees),
            "levels": len(solution.leximin_levels),
            "max_guarantee_shift": shift,
            "same_level_structure": structure(solution) == structure(published),
            "same_at_four_decimals": all(
                f"{solution.guarantees[c]:.4f}" == f"{published.guarantees[c]:.4f}" for c in model.claimants
            ),
            "nominal_delivery_shift_af": solution.nominal_beneficial_delivery - published.nominal_beneficial_delivery,
            "contingency_delivery_shift_af": (
                solution.weighted_contingency_beneficial_delivery
                - published.weighted_contingency_beneficial_delivery
            ),
            "recourse_effort_shift": solution.normalized_recourse_effort - published.normalized_recourse_effort,
        })
    solved = [row for row in rows if "failed" not in row]
    tight = [row for row in solved if max(row["blocking_tolerance"], row["lp_feasibility_tolerance"],
                                          row["preservation_tolerance"]) <= 1e-6]
    failed = [row for row in rows if "failed" in row]
    retried = [row["retried_with_fallbacks"] for row in failed if "retried_with_fallbacks" in row]
    completed = [item for item in retried if item["completed"]]
    return {
        "points": len(rows),
        "failed": failed,
        "failed_because_no_claimant_was_blocked": sum("no blocked claimant" in row["failed"] for row in failed),
        "failed_because_a_program_returned_no_optimum": len(retried),
        "of_those_completed_with_fallbacks": len(completed),
        "max_guarantee_shift_of_points_completed_with_fallbacks": max(
            (item["max_guarantee_shift"] for item in completed), default=None
        ),
        "points_completed_with_fallbacks_agree_at_four_decimals": all(
            item["same_at_four_decimals"] and item["same_level_structure"] for item in completed
        ),
        "max_guarantee_shift": max(row["max_guarantee_shift"] for row in solved),
        "max_guarantee_shift_with_every_tolerance_at_most_1e-6": max(row["max_guarantee_shift"] for row in tight),
        "every_point_has_the_published_level_structure": all(row["same_level_structure"] for row in solved),
        "every_point_agrees_at_four_decimals": all(row["same_at_four_decimals"] for row in solved),
        "max_abs_nominal_delivery_shift_af": max(abs(row["nominal_delivery_shift_af"]) for row in solved),
        "rows": rows,
    }


def near_tie(model, published) -> dict:
    """Put the second level a chosen distance above the first and watch the solver resolve it."""

    lowest, second = published.leximin_levels[0], published.leximin_levels[1]
    target = sorted(second.blocked_claimants)[0]
    rows = []
    for distance in NEAR_TIE_DISTANCES:
        scale = published.guarantees[target] / (lowest.level + distance)
        scaled = replace(
            model,
            demand={key: (value * scale if key[1] == target else value) for key, value in model.demand.items()},
        )
        with Recorder() as recorder:
            solution = solve_cti_rlex(scaled)
        # The distance the solver actually faces: the target's best ratio with every claimant
        # held at the first-round level, minus that level, both from the first round's programs.
        first_level = solution.leximin_levels[0].level
        test = next(
            (problem, result)
            for problem, result in recorder.calls
            if stage_of(scaled, problem) == ("blocking_test", target)
        )
        attainable = float(test[1].x[test[0].index[("rho", target)]])
        merged = target in solution.leximin_levels[0].blocked_claimants
        rows.append({
            "constructed_distance": distance,
            "measured_distance": attainable - first_level,
            "merged_with_the_lowest_level": merged,
            "levels": len(solution.leximin_levels),
            "reported_target_guarantee": solution.guarantees[target],
            "attainable_target_guarantee": attainable,
            "reporting_error": solution.guarantees[target] - attainable,
        })
    return {
        "target_claimant": target,
        "lowest_level_claimants": sorted(lowest.blocked_claimants),
        "demand_scaled_so_that_the_target_level_sits_above_the_lowest_by_the_distance": True,
        "separated_whenever_the_measured_distance_exceeds_ten_times_the_tolerance": all(
            not row["merged_with_the_lowest_level"]
            for row in rows if row["measured_distance"] > 10 * PUBLISHED
        ),
        "merged_whenever_the_measured_distance_is_at_most_the_tolerance": all(
            row["merged_with_the_lowest_level"]
            for row in rows if row["measured_distance"] <= PUBLISHED
        ),
        "largest_reporting_error_when_merged": max(
            (abs(row["reporting_error"]) for row in rows if row["merged_with_the_lowest_level"]), default=0.0
        ),
        "rows": rows,
    }


def closest_levels(published) -> dict:
    values = [level.level for level in published.leximin_levels]
    gaps = [(values[i + 1] - values[i], i) for i in range(len(values) - 1)]
    if not gaps:
        return {"levels": len(values), "closest_distance": None}
    distance, index = min(gaps)
    return {
        "levels": len(values),
        "closest_distance": distance,
        "between": [values[index], values[index + 1]],
        "ratio_to_the_blocking_tolerance": distance / PUBLISHED,
    }


def main() -> None:
    report = {"tolerance_grid": list(GRID), "published_tolerance": PUBLISHED, "instances": {}}
    for name, path in INSTANCES.items():
        model = load_cti_benchmark(path)
        certified, published = certificates(model)
        grid = tolerance_grid(model, published)
        tie = near_tie(model, published)
        report["instances"][name] = {
            "published_guarantees": dict(published.guarantees),
            "published_levels": [
                {"level": level.level, "blocked": sorted(level.blocked_claimants)}
                for level in published.leximin_levels
            ],
            "certificates": certified,
            "grid": grid,
            "near_tie": tie,
            "closest_distinct_levels": closest_levels(published),
        }
        print(f"{name}: {certified['linear_programs']} programs, largest relative gap "
              f"{certified['max_relative_gap']:.2e}, primal residual {certified['max_primal_residual']:.2e}, "
              f"dual residual {certified['max_dual_residual']:.2e}")
        print(f"  grid of {grid['points']} points, {len(grid['failed'])} failed "
              f"({grid['failed_because_no_claimant_was_blocked']} with no claimant blocked, "
              f"{grid['failed_because_a_program_returned_no_optimum']} with a program returning no optimum, of which "
              f"{grid['of_those_completed_with_fallbacks']} complete with fallbacks, largest shift "
              f"{grid['max_guarantee_shift_of_points_completed_with_fallbacks']})")
        print(f"  largest guarantee shift "
              f"{grid['max_guarantee_shift']:.2e} (with every tolerance <= 1e-6: "
              f"{grid['max_guarantee_shift_with_every_tolerance_at_most_1e-6']:.2e}); "
              f"same level structure everywhere: {grid['every_point_has_the_published_level_structure']}; "
              f"same four decimals everywhere: {grid['every_point_agrees_at_four_decimals']}")
        print(f"  near tie on {tie['target_claimant']}: separated above 10 x tolerance: "
              f"{tie['separated_whenever_the_measured_distance_exceeds_ten_times_the_tolerance']}; merged at or "
              f"below the tolerance: {tie['merged_whenever_the_measured_distance_is_at_most_the_tolerance']}; "
              f"largest error when merged {tie['largest_reporting_error_when_merged']:.2e}")
        for row in tie["rows"]:
            print(f"    distance {row['constructed_distance']:.0e}: measured {row['measured_distance']:.3e}, "
                  f"{'merged' if row['merged_with_the_lowest_level'] else 'separate'}, "
                  f"{row['levels']} levels, error {row['reporting_error']:.2e}")
        closest = report["instances"][name]["closest_distinct_levels"]
        print(f"  closest distinct levels: {closest['closest_distance']}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
