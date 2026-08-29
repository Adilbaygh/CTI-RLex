"""Produce results/revision_experiments.json: the lexicographic-discrimination evidence.

Reviewer item 3.4: the README mapped Table 3, Figure 4(b) and Supplementary Tables S6, S8
and S9 to ``results/discrimination/k1.py``, but that script only prints to the terminal and
writes nothing, so ``results/revision_experiments.json`` had no producer in the published
package. This script is that producer. It solves both benchmarks under CTI-RLex, PROP-BR
and the fairness-optimistic utilitarian comparator, records the program dimensions, the
progressive-filling level trace, the sorted guarantee vectors and the per-claimant values,
and writes them to one file.

Run:  python scripts/revision_experiments.py
Writes: results/revision_experiments.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from leximin.dag.experiments import (  # noqa: E402
    lp_dimensions,
    solve_robust_proportional,
    solve_utilitarian,
    solve_utilitarian_fair,
    timed_solve,
    utilitarian_fairness_range,
)
from leximin.dag.io import load_cti_benchmark  # noqa: E402
from leximin.dag.solver import solve_cti_rlex  # noqa: E402

OUTPUT = REPO / "results" / "revision_experiments.json"
INSTANCES = {
    "little_bear_v2": REPO / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json",
    "cache_valley_v3": REPO / "DATA" / "CacheValley_2025_Benchmark" / "benchmark.json",
}


def first_difference(left: list[float], right: list[float], tolerance: float = 1e-7):
    """The lexicographic comparison itself: the first position at which vectors differ."""

    for position, (a, b) in enumerate(zip(left, right), start=1):
        if abs(a - b) > tolerance:
            return position, ("CTI-RLex" if a > b else "PROP-BR")
    return None, None


def instance_report(path: Path) -> dict:
    model = load_cti_benchmark(path)
    rlex, rlex_seconds = timed_solve(solve_cti_rlex, model)
    prop, _ = timed_solve(solve_robust_proportional, model)
    utilitarian, _ = timed_solve(solve_utilitarian_fair, model)
    # The raw vertex the plain delivery maximization happens to return. Reported beside
    # the fairness-optimistic value so that the width of the optimal face stays visible.
    raw_utilitarian, _ = timed_solve(solve_utilitarian, model)
    span = utilitarian_fairness_range(model)

    rlex_sorted = sorted(rlex.guarantees.values())
    prop_sorted = sorted(prop.guarantees.values())
    position, higher = first_difference(rlex_sorted, prop_sorted)
    floor_rlex = sum(1 for v in rlex_sorted if abs(v - rlex_sorted[0]) <= 1e-7)
    floor_prop = sum(1 for v in prop_sorted if abs(v - prop_sorted[0]) <= 1e-7)

    return {
        "claimants": len(model.claimants),
        "lp_dimensions": lp_dimensions(model),
        "cti_rlex": {
            "levels": [
                {"theta": level.level, "blocked": list(level.blocked_claimants)}
                for level in rlex.leximin_levels
            ],
            "guarantees": dict(rlex.guarantees),
            "sorted_rho": rlex_sorted,
            "min": min(rlex_sorted),
            "nominal_af": rlex.nominal_beneficial_delivery,
            "runtime_s": rlex_seconds,
            "max_residual": max(rlex.residuals.values(), default=0.0),
        },
        "prop_br": {
            "guarantees": dict(prop.guarantees),
            "sorted_rho": prop_sorted,
            "min": min(prop_sorted),
            "nominal_af": prop.nominal_beneficial_delivery,
        },
        "utilitarian": {
            "reported_min": min(utilitarian.guarantees.values()),
            "raw_solver_vertex_min": min(raw_utilitarian.guarantees.values()),
            "nominal_delivery_optimum": span["nominal_delivery_optimum"],
            "max_common_floor_on_optimal_face": span["max_common_floor_on_optimal_face"],
            "fairness_optimistic_min": span["max_common_floor_on_optimal_face"],
            "degeneracy_span": (
                span["max_common_floor_on_optimal_face"]
                - min(raw_utilitarian.guarantees.values())
            ),
            "min_seasonal_ratio_by_claimant": span["min_seasonal_ratio_by_claimant"],
            "worst_claimant_seasonal_ratio": span["worst_claimant_seasonal_ratio"],
        },
        "lexicographic_comparison": {
            "first_differing_position": position,
            "higher_at_that_position": higher,
            "claimants_at_floor_rlex": floor_rlex,
            "claimants_at_floor_prop": floor_prop,
            "note": (
                "the sum of differences is NOT the leximin criterion; compare sorted "
                "vectors position by position"
            ),
        },
        "price_of_lexicographic_refinement_pct": (
            100.0
            * (prop.nominal_beneficial_delivery - rlex.nominal_beneficial_delivery)
            / prop.nominal_beneficial_delivery
        ),
    }


def main() -> None:
    report = {name: instance_report(path) for name, path in INSTANCES.items()}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    for name, entry in report.items():
        comparison = entry["lexicographic_comparison"]
        print(f"{name}: {entry['claimants']} claimants, "
              f"{len(entry['cti_rlex']['levels'])} levels, "
              f"first difference at position {comparison['first_differing_position']} "
              f"({comparison['higher_at_that_position']}), "
              f"floor holds {comparison['claimants_at_floor_rlex']} vs "
              f"{comparison['claimants_at_floor_prop']} claimants")
    print("wrote", OUTPUT)


if __name__ == "__main__":
    main()
