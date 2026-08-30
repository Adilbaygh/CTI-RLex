"""Does the reported result depend on how reconfiguration effort is normalized?

The recourse budget constrains a weighted sum of control deviations,
sum_i sum_k c_i * u_ki^omega <= B^omega, and the published weights are
c_i = 1 / ubar_i with ubar_i the seasonal gross demand reachable from control i. That
choice makes the budget dimensionless and comparable across controls, but it is one choice
among several defensible ones, and every number the paper reports about recourse -- the
value of recourse above all -- is measured under it. A reported gain that held only under
one weighting would be a property of the weighting.

Three weightings are compared, on both instances:

    reachable demand   c_i = 1 / seasonal gross demand reachable from the control (published)
    control capacity   c_i = 1 / the control's own seasonal capacity: the seasonal source
                       limit for a source, the summed nominal reach capacity for a gate
    uniform            every control carries the same weight

Scaling every c_i by a constant is the same as scaling B^omega, so a comparison of raw
weightings would measure the size of the allowance rather than its shape. Each variant is
therefore rescaled to the published total weight, sum_i c_i, and the scale factor is
reported so the two effects stay separable; the capacity weighting is also reported
unscaled, which is what a reader would get by adopting it naively.

The rigid comparator carries no budget, so its minimum guarantee is the same under every
weighting by construction. The value of recourse is measured against that same rigid
solution in every variant, which is what makes the variants comparable at all.

Run:  python scripts/normalization_sensitivity.py
Writes: results/normalization_sensitivity.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from timing_protocol import timed  # noqa: E402

from leximin.dag import (  # noqa: E402
    CTIBenchmark,
    load_cti_benchmark,
    solve_cti_rlex,
    solve_utilitarian_fair,
    subset_scenarios,
)

INSTANCES = {
    "little_bear_v2": REPO / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json",
    "cache_valley_v3": REPO / "DATA" / "CacheValley_2025_Benchmark" / "benchmark.json",
}
OUTPUT = REPO / "results" / "normalization_sensitivity.json"

TOLERANCE = 1e-7

# The declared budgets are past the point at which the fairness stage stops improving --
# the paper reports the gain as saturated by a scale of 0.50 -- so an invariance measured
# only there could be an artefact of a slack constraint rather than a property of the
# method. The frontier is therefore swept under every weighting, down to allowances small
# enough that the fairness stage certainly binds.
BUDGET_SCALES = (0.05, 0.10, 0.25, 0.50, 1.00)


def control_capacity(model: CTIBenchmark, asset) -> float:
    """The seasonal volume the control itself can move, in acre-feet.

    A source is bounded by its own seasonal limit; a gate is bounded by the reach behind
    it, whose seasonal capacity is the sum of its nominal monthly capacities. Both are
    volumes, so the two kinds of control stay on one scale, which is the whole point of a
    normalization.
    """

    nominal = model.nominal_scenario
    if asset.resource_type == "source":
        return float(model.source_seasonal_limit[(nominal, asset.resource_id)])
    return sum(
        float(model.edge_capacity[(nominal, period, asset.resource_id)])
        for period in model.periods
    )


def weighted(model: CTIBenchmark, coefficients: dict[str, float]) -> CTIBenchmark:
    return replace(
        model,
        controls=tuple(
            replace(asset, effort_coefficient=coefficients[asset.asset_id])
            for asset in model.controls
        ),
    )


def variants(model: CTIBenchmark) -> dict[str, dict[str, Any]]:
    published = {asset.asset_id: asset.effort_coefficient for asset in model.controls}
    total = sum(published.values())

    capacity_raw = {
        asset.asset_id: 1.0 / control_capacity(model, asset) for asset in model.controls
    }
    capacity_total = sum(capacity_raw.values())
    capacity = {
        key: value * total / capacity_total for key, value in capacity_raw.items()
    }
    uniform = {key: total / len(published) for key in published}

    return {
        "reachable_demand": {
            "coefficients": published,
            "description": "published: the inverse seasonal gross demand reachable from the control",
            "rescaled_to_the_published_total": False,
            "scale_factor": 1.0,
        },
        "control_capacity": {
            "coefficients": capacity,
            "description": "the inverse of the control's own seasonal capacity, rescaled to "
                           "the published total weight",
            "rescaled_to_the_published_total": True,
            "scale_factor": total / capacity_total,
        },
        "control_capacity_unscaled": {
            "coefficients": capacity_raw,
            "description": "the same weighting adopted naively, without matching the total "
                           "weight, so the allowance itself changes",
            "rescaled_to_the_published_total": False,
            "scale_factor": 1.0,
        },
        "uniform": {
            "coefficients": uniform,
            "description": "every control carries the same weight, at the published mean, "
                           "so the total weight is unchanged",
            "rescaled_to_the_published_total": True,
            "scale_factor": 1.0,
        },
    }


def evaluate(model: CTIBenchmark, rigid_min: float, nominal_only_af: float) -> dict[str, Any]:
    solution, timing = timed(lambda: solve_cti_rlex(model))
    utilitarian = solve_utilitarian_fair(model)
    sorted_rho = sorted(solution.guarantees.values())
    minimum = min(sorted_rho)
    delivery = solution.nominal_beneficial_delivery
    return {
        "sorted_rho": sorted_rho,
        "guarantees": dict(solution.guarantees),
        "min_guarantee": minimum,
        "nominal_delivery_af": delivery,
        "normalized_recourse_effort": solution.normalized_recourse_effort,
        "recourse_by_scenario": dict(solution.recourse_by_scenario),
        "value_of_recourse_pct": (
            100.0 * (minimum - rigid_min) / rigid_min if rigid_min > 0 else None
        ),
        "price_of_fairness_pct": 100.0
        * (utilitarian.nominal_beneficial_delivery - delivery)
        / utilitarian.nominal_beneficial_delivery,
        "price_of_robustness_pct": 100.0 * (nominal_only_af - delivery) / nominal_only_af,
        "max_lp_residual": max(solution.residuals.values(), default=0.0),
        **timing,
    }


def frontier(model: CTIBenchmark, coefficients: dict[str, float]) -> list[dict[str, Any]]:
    """The minimum guarantee under one weighting, as the allowance is tightened.

    Where the allowance binds, a weighting that spends it differently should reach a
    different floor; where it does not bind, every weighting reaches the same one. Only
    this sweep separates the two, so only it can say whether the invariance measured at the
    declared budgets is a property of the method or of a slack constraint.
    """

    weighted_model = weighted(model, coefficients)
    rows = []
    for scale in BUDGET_SCALES:
        scaled = replace(
            weighted_model,
            recourse_budget={
                scenario: budget * scale
                for scenario, budget in weighted_model.recourse_budget.items()
            },
        )
        solution = solve_cti_rlex(scaled)
        rows.append({
            "budget_scale": scale,
            "min_guarantee": min(solution.guarantees.values()),
            "sorted_rho": sorted(solution.guarantees.values()),
        })
    return rows


def report(path: Path) -> dict[str, Any]:
    model = load_cti_benchmark(path)

    # The rigid plan carries no budget, so the weights cannot reach it. It is solved once
    # and every variant is measured against it; that is what makes the variants comparable.
    rigid = solve_cti_rlex(
        replace(model, recourse_budget={scenario: 0.0 for scenario in model.scenarios})
    )
    rigid_min = min(rigid.guarantees.values())
    nominal_only = solve_cti_rlex(subset_scenarios(model, (model.nominal_scenario,)))
    nominal_only_af = nominal_only.nominal_beneficial_delivery

    rows = {}
    for name, variant in variants(model).items():
        result = evaluate(weighted(model, variant["coefficients"]), rigid_min, nominal_only_af)
        rows[name] = {
            "budget_frontier": frontier(model, variant["coefficients"]),
            "description": variant["description"],
            "rescaled_to_the_published_total": variant["rescaled_to_the_published_total"],
            "scale_factor": variant["scale_factor"],
            "effort_coefficients": variant["coefficients"],
            **result,
        }
        print(f"  {name:<26} min {result['min_guarantee']:.6f}   "
              f"VoR {result['value_of_recourse_pct']:.2f}%   "
              f"nominal {result['nominal_delivery_af']:.1f} af   "
              f"PoF {result['price_of_fairness_pct']:.2f}%")

    # Three questions have to be kept apart. Is the reported vector the same under every
    # weighting? Does the choice matter anywhere? And does anything else the paper reports
    # move? The first two are answered by the frontier, the third by the delivery figures,
    # and merging them would let an invariance in one hide a dependence in another.
    matched = [name for name, row in rows.items()
               if row["rescaled_to_the_published_total"] or name == "reachable_demand"]
    reference = rows["reachable_demand"]

    declared_invariant = all(
        len(rows[name]["sorted_rho"]) == len(reference["sorted_rho"])
        and all(abs(a - b) <= TOLERANCE
                for a, b in zip(rows[name]["sorted_rho"], reference["sorted_rho"]))
        for name in matched
    )
    deviation = max(
        abs(a - b)
        for name in matched
        for theirs, ours in zip(rows[name]["budget_frontier"], reference["budget_frontier"])
        for a, b in zip(theirs["sorted_rho"], ours["sorted_rho"])
    )
    saturated = reference["budget_frontier"][-1]["min_guarantee"]
    binding = [
        row["budget_scale"]
        for row in reference["budget_frontier"]
        if abs(row["min_guarantee"] - saturated) > TOLERANCE
    ]
    fairness = [rows[name]["price_of_fairness_pct"] for name in matched]
    delivery = [rows[name]["nominal_delivery_af"] for name in matched]

    print(f"  the fairness stage is still improving at budget scales {binding or 'none'}")
    print(f"  the guarantee vector is identical under every weighting at the declared "
          f"budgets: {declared_invariant}")
    print(f"  the largest guarantee difference anywhere on the frontier: {deviation:.6f}")
    print(f"  nominal delivery ranges {min(delivery):.1f} to {max(delivery):.1f} af, "
          f"price of fairness {min(fairness):.2f}% to {max(fairness):.2f}%")

    return {
        "benchmark_id": model.benchmark_id,
        "budget_scales": list(BUDGET_SCALES),
        "weightings_at_the_published_total_weight": matched,
        "budget_scales_at_which_the_fairness_stage_still_improves": binding,
        "guarantee_vector_invariant_at_the_declared_budgets": declared_invariant,
        "largest_guarantee_difference_across_the_frontier": deviation,
        "nominal_delivery_range_af": [min(delivery), max(delivery)],
        "price_of_fairness_range_pct": [min(fairness), max(fairness)],
        "controls": len(model.controls),
        "rigid_min_guarantee": rigid_min,
        "nominal_only_delivery_af": nominal_only_af,
        "declared_recourse_budget": dict(model.recourse_budget),
        "tolerance": TOLERANCE,
        "variants": rows,
    }


def main() -> None:
    payload = {}
    for name, path in INSTANCES.items():
        print(f"{name}:")
        payload[name] = report(path)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
