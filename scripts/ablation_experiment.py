"""Produce results/ablation_lbr.json and results/ablation_cv.json.

Two things are wrong with the source-removal evidence as it stands, and this script fixes
both.

First, neither result file had a producer in the published package. They were read by the
supplement generator and cited in the Data Availability Statement, but nothing regenerated
them, so a reader could not reproduce them and a change in the model could not invalidate
them. This is the same gap that results/revision_experiments.json had before
scripts/revision_experiments.py was written.

Second, and more consequential: a source was called "redundant at the optimum" whenever it
left the minimum guarantee unchanged. CTI-RLex does not stop at the minimum. Its objective
hierarchy fixes the complete sorted guarantee vector and only then maximizes nominal
delivery, so a source whose removal costs 2555.4 acre-ft of nominal delivery is not
redundant for that hierarchy, and a source that leaves the minimum alone may still lower a
higher lexicographic level. Each removal is therefore classified against the hierarchy the
method actually optimizes:

    connectivity-critical            at least one claimant loses every route to a source
    minimum-guarantee-critical       the global floor falls
    higher-level-fairness-critical   the floor holds but the sorted vector falls above it
    delivery-critical                the whole guarantee vector holds, delivery falls
    fully-redundant                  no level of the hierarchy changes

The thresholds are the ones the documents report with, so a label can never disagree with
the number printed beside it: guarantees at the lexicographic tolerance of 1e-7, deliveries
at 0.05 acre-ft, which is the precision the tables print.

Run:  python scripts/ablation_experiment.py
Writes: results/ablation_lbr.json, results/ablation_cv.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from timing_protocol import timed  # noqa: E402

from leximin.dag import (  # noqa: E402
    CTIBenchmark,
    CTIRLexSolution,
    disable_source,
    load_cti_benchmark,
    solve_cti_rlex,
)

INSTANCES = {
    "ablation_lbr": REPO / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json",
    "ablation_cv": REPO / "DATA" / "CacheValley_2025_Benchmark" / "benchmark.json",
}

GUARANTEE_TOLERANCE = 1e-7      # the blocking tolerance of Section 2.7
DELIVERY_TOLERANCE = 0.05       # the precision the ablation tables print

READING = {
    "connectivity_critical": "structural disconnection",
    "minimum_guarantee_critical": "minimum guarantee falls",
    "higher_level_fairness_critical": "higher guarantee levels fall",
    "delivery_critical": "guarantee vector held, nominal delivery falls",
    "fully_redundant": "redundant for the full objective hierarchy",
}


def scenario_delivery_totals(model: CTIBenchmark, solution: CTIRLexSolution) -> dict:
    return {
        scenario: sum(
            value
            for (item_scenario, _period, _terminal), value
            in solution.beneficial_delivery.items()
            if item_scenario == scenario
        )
        for scenario in model.scenarios
    }


def first_difference(base: list[float], other: list[float]) -> int | None:
    """The first sorted position at which the ablated vector falls below the base."""

    for position, (a, b) in enumerate(zip(base, other), start=1):
        if abs(a - b) > GUARANTEE_TOLERANCE:
            return position
    return None


def classify(
    disconnected: list[str],
    base_min: float,
    min_guarantee: float,
    differing_position: int | None,
    base_nominal: float,
    nominal: float,
    base_worst: float,
    worst: float,
) -> str:
    if disconnected:
        return "connectivity_critical"
    if min_guarantee < base_min - GUARANTEE_TOLERANCE:
        return "minimum_guarantee_critical"
    if differing_position is not None:
        return "higher_level_fairness_critical"
    if nominal < base_nominal - DELIVERY_TOLERANCE or worst < base_worst - DELIVERY_TOLERANCE:
        return "delivery_critical"
    return "fully_redundant"


def report(path: Path) -> dict:
    model = load_cti_benchmark(path)
    base, base_timing = timed(lambda: solve_cti_rlex(model))
    base_sorted = sorted(base.guarantees.values())
    base_min = min(base_sorted)
    base_nominal = base.nominal_beneficial_delivery
    base_worst = min(scenario_delivery_totals(model, base).values())

    rows = []
    for source in model.sources:
        ablated_model = disable_source(model, source.source_id)
        solution, timing = timed(lambda: solve_cti_rlex(ablated_model))
        guarantees = dict(solution.guarantees)
        sorted_rho = sorted(guarantees.values())
        totals = scenario_delivery_totals(ablated_model, solution)
        worst = min(totals.values())
        nominal = solution.nominal_beneficial_delivery

        # A claimant that cannot be served at all in some demand-positive period of some
        # scenario carries a zero guarantee; on these benchmarks the base guarantee of
        # every claimant is strictly positive, so a zero here means the removal took away
        # the claimant's last route.
        disconnected = sorted(
            claimant for claimant, value in guarantees.items()
            if value <= GUARANTEE_TOLERANCE
        )
        differing = first_difference(base_sorted, sorted_rho)
        classification = classify(
            disconnected, base_min, min(sorted_rho), differing,
            base_nominal, nominal, base_worst, worst,
        )

        rows.append(
            {
                # the keys the supplement generator already reads
                "source_id": source.source_id,
                "source_class": source.source_class,
                "disconnected_claimants": disconnected,
                "min_guarantee": min(sorted_rho),
                "delta_percentage_points": 100.0 * (min(sorted_rho) - base_min),
                "nominal_delivery_af": nominal,
                "delta_nominal_af": nominal - base_nominal,
                "explanation": classification,
                # what the review asks to be reported for every removal
                "guarantees": guarantees,
                "sorted_rho": sorted_rho,
                "first_differing_position": differing,
                "worst_scenario_delivery_af": worst,
                "delta_worst_af": worst - base_worst,
                "classification": classification,
                "reading": READING[classification],
                "max_lp_residual": max(solution.residuals.values(), default=0.0),
                **timing,
            }
        )
        print(f"  {source.source_id:>10}  {classification}", flush=True)

    return {
        "base_min_guarantee": base_min,
        "base_nominal_delivery_af": base_nominal,
        "base_worst_scenario_delivery_af": base_worst,
        "base_sorted_rho": base_sorted,
        "base_guarantees": dict(base.guarantees),
        "guarantee_tolerance": GUARANTEE_TOLERANCE,
        "delivery_tolerance_af": DELIVERY_TOLERANCE,
        "classification_meaning": READING,
        **{f"base_{key}": value for key, value in base_timing.items()},
        "rows": rows,
    }


def main() -> None:
    for name, path in INSTANCES.items():
        print(f"{name}:")
        payload = report(path)
        output = REPO / "results" / f"{name}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        counts: dict[str, int] = {}
        for row in payload["rows"]:
            counts[row["classification"]] = counts.get(row["classification"], 0) + 1
        print(f"  wrote {output}")
        for label in READING:
            if counts.get(label):
                print(f"    {counts[label]:>2}  {label}")


if __name__ == "__main__":
    main()
