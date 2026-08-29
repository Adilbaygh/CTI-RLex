"""Find the capacity level at which a declared restriction scenario becomes binding.

Reviewer item K3: in the published benchmark the Hyrum canal restriction scenario leaves
the Hyrum guarantee exactly where the nominal scenario leaves it, so a reader cannot tell
whether the five scenarios really exercise the model. This script sweeps the severity of
that restriction and reports the retained-capacity fraction at which the guarantee vector
first changes, which turns the observation into a stated threshold.

The severity is the fraction ``r`` of the nominal value retained by the three quantities
the scenario derates: the Hyrum canal head reach and the two sources feeding it. The
published scenario corresponds to r = 0.35 on the reach and r = 0.30 on the reservoir.

Run:  python scripts/restriction_threshold_experiment.py
Writes: results/restriction_threshold.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from leximin.dag.io import load_cti_benchmark  # noqa: E402
from leximin.dag.solver import solve_cti_rlex  # noqa: E402

BENCHMARK = REPO / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json"
OUTPUT = REPO / "results" / "restriction_threshold.json"

SCENARIO = "hyrum_canal_restriction_under_shortage"
RESTRICTED_EDGES = ("e_11819",)
RESTRICTED_SOURCES = ("s_15269", "s_15957")
FRACTIONS = (
    1.0, 0.5, 0.35, 0.25, 0.20, 0.15, 0.12, 0.10, 0.08, 0.06,
    0.05, 0.046, 0.044, 0.042, 0.04, 0.035, 0.03, 0.02,
)
TOLERANCE = 1e-7


def restrict(model, fraction: float):
    """Retain ``fraction`` of the nominal capacity on the restricted assets."""

    nominal = model.nominal_scenario
    capacity = dict(model.edge_capacity)
    for (scenario, period, edge) in list(capacity):
        if scenario == SCENARIO and edge in RESTRICTED_EDGES:
            capacity[(scenario, period, edge)] = (
                model.edge_capacity[(nominal, period, edge)] * fraction
            )
    limit = dict(model.source_limit)
    for (scenario, period, source) in list(limit):
        if scenario == SCENARIO and source in RESTRICTED_SOURCES:
            limit[(scenario, period, source)] = (
                model.source_limit[(nominal, period, source)] * fraction
            )
    seasonal = dict(model.source_seasonal_limit)
    for (scenario, source) in list(seasonal):
        if scenario == SCENARIO and source in RESTRICTED_SOURCES:
            seasonal[(scenario, source)] = (
                model.source_seasonal_limit[(nominal, source)] * fraction
            )
    return replace(
        model,
        benchmark_id=f"{model.benchmark_id}__hyrum_r{fraction:g}",
        edge_capacity=capacity,
        source_limit=limit,
        source_seasonal_limit=seasonal,
    )


def binding_scenarios(solution, model) -> dict[str, list[str]]:
    """Scenarios in which a claimant sits on its own guarantee."""

    out: dict[str, list[str]] = {claimant: [] for claimant in model.claimants}
    for (scenario, period, claimant), ratio in solution.period_service_ratio.items():
        target = solution.guarantees[claimant]
        if abs(ratio - target) <= 1e-6 and scenario not in out[claimant]:
            out[claimant].append(scenario)
    return {key: sorted(value) for key, value in out.items()}


def main() -> None:
    model = load_cti_benchmark(BENCHMARK)
    baseline = solve_cti_rlex(model)
    reference = dict(baseline.guarantees)

    rows = []
    threshold = None
    for fraction in FRACTIONS:
        solution = solve_cti_rlex(restrict(model, fraction))
        guarantees = dict(solution.guarantees)
        changed = sorted(
            claimant
            for claimant in guarantees
            if guarantees[claimant] < reference[claimant] - TOLERANCE
        )
        rows.append(
            {
                "retained_fraction": fraction,
                "guarantees": guarantees,
                "min_guarantee": min(guarantees.values()),
                "claimants_reduced": changed,
                "binding_scenarios": binding_scenarios(solution, model),
                "nominal_af": solution.nominal_beneficial_delivery,
            }
        )
        if changed and threshold is None:
            threshold = fraction

    report = {
        "scenario": SCENARIO,
        "restricted_edges": list(RESTRICTED_EDGES),
        "restricted_sources": list(RESTRICTED_SOURCES),
        "published_retained_fraction": {"reach": 0.35, "reservoir": 0.30},
        "reference_guarantees": reference,
        "first_binding_fraction": threshold,
        "rows": rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"reference guarantees: { {k: round(v, 6) for k, v in reference.items()} }")
    print(f"{'r':>6} {'min rho':>9}  {'reduced claimants':<34} nominal af")
    for row in rows:
        print(
            f"{row['retained_fraction']:>6.2f} {row['min_guarantee']:>9.6f}  "
            f"{','.join(row['claimants_reduced']) or '-':<34} {row['nominal_af']:.1f}"
        )
    print("first binding retained fraction:", threshold)
    print("wrote", OUTPUT)


if __name__ == "__main__":
    main()
