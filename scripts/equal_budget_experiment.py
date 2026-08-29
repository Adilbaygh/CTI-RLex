"""Test whether the CTI-RLex result depends on the per-scenario recourse budgets.

Reviewer item K2: in the published Little Bear benchmark each contingency scenario
carries its own recourse budget (0.25, 0.40, 0.35, 0.25), so a scenario-wise delivery
panel mixes stress severity with operating freedom. This script re-solves the whole
comparator set under a single budget shared by every contingency and reports what
changes and what does not, including whether any contingency cell still receives a
larger service ratio than the corresponding nominal cell.

Run:  python scripts/equal_budget_experiment.py
Writes: results/equal_budget_experiment.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from leximin.dag.io import load_cti_benchmark  # noqa: E402
from leximin.dag.experiments import (  # noqa: E402
    solve_robust_proportional,
    solve_utilitarian,
    subset_scenarios,
)
from leximin.dag.solver import solve_cti_rlex  # noqa: E402

BENCHMARK = REPO / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json"
OUTPUT = REPO / "results" / "equal_budget_experiment.json"
COMMON_BUDGETS = (0.25, 0.40)
TOLERANCE = 1e-9


def with_common_budget(model, budget: float):
    """One budget for every contingency; the nominal scenario keeps zero by definition."""

    return replace(
        model,
        benchmark_id=f"{model.benchmark_id}__equal_b{budget:g}",
        recourse_budget={
            scenario: (0.0 if scenario == model.nominal_scenario else budget)
            for scenario in model.scenarios
        },
    )


def cells_above_nominal(solution, model) -> list[dict]:
    """Contingency cells that receive a larger service ratio than the nominal cell.

    The service-ratio key is (scenario, period, claimant).
    """

    nominal = model.nominal_scenario
    found = []
    for (scenario, period, claimant), ratio in solution.period_service_ratio.items():
        if scenario == nominal:
            continue
        base = solution.period_service_ratio.get((nominal, period, claimant))
        if base is None or ratio <= base + TOLERANCE:
            continue
        found.append(
            {
                "scenario": scenario,
                "period": period,
                "claimant": claimant,
                "nominal_ratio": base,
                "contingency_ratio": ratio,
                "excess": ratio - base,
            }
        )
    return sorted(found, key=lambda item: -item["excess"])


def evaluate(label: str, model, rigid_min: float, nominal_only_af: float) -> dict:
    solution = solve_cti_rlex(model)
    utilitarian = solve_utilitarian(model)
    proportional = solve_robust_proportional(model)
    sorted_rho = sorted(solution.guarantees.values())
    minimum = min(sorted_rho)
    delivery = solution.nominal_beneficial_delivery
    return {
        "label": label,
        "recourse_budget": dict(model.recourse_budget),
        "sorted_rho": sorted_rho,
        "min_guarantee": minimum,
        "levels": [
            {"theta": level.level, "blocked": list(level.blocked_claimants)}
            for level in solution.leximin_levels
        ],
        "nominal_af": delivery,
        "utilitarian_nominal_af": utilitarian.nominal_beneficial_delivery,
        "utilitarian_min": min(utilitarian.guarantees.values()),
        "proportional_nominal_af": proportional.nominal_beneficial_delivery,
        "proportional_min": min(proportional.guarantees.values()),
        "price_of_fairness_pct": 100
        * (utilitarian.nominal_beneficial_delivery - delivery)
        / utilitarian.nominal_beneficial_delivery,
        "value_of_recourse_pct": 100 * (minimum - rigid_min) / rigid_min,
        "price_of_robustness_pct": 100 * (nominal_only_af - delivery) / nominal_only_af,
        "cells_above_nominal": cells_above_nominal(solution, model),
        "max_residual": max(solution.residuals.values()),
    }


def main() -> None:
    model = load_cti_benchmark(BENCHMARK)
    rigid = solve_cti_rlex(with_common_budget(model, 0.0))
    rigid_min = min(rigid.guarantees.values())
    nominal_only = solve_cti_rlex(subset_scenarios(model, (model.nominal_scenario,)))
    nominal_only_af = nominal_only.nominal_beneficial_delivery

    cases = [evaluate("published per-scenario budgets", model, rigid_min, nominal_only_af)]
    for budget in COMMON_BUDGETS:
        cases.append(
            evaluate(
                f"one common contingency budget b={budget:g}",
                with_common_budget(model, budget),
                rigid_min,
                nominal_only_af,
            )
        )

    reference = cases[0]["sorted_rho"]
    invariant = all(
        len(case["sorted_rho"]) == len(reference)
        and all(abs(a - b) <= TOLERANCE for a, b in zip(case["sorted_rho"], reference))
        for case in cases
    )

    report = {
        "benchmark": model.benchmark_id,
        "rigid_min_guarantee": rigid_min,
        "nominal_only_af": nominal_only_af,
        "guarantee_vector_invariant_to_budget_regime": invariant,
        "cases": cases,
        "mechanism_check": {
            "note": (
                "Without contingency scenarios the same claimant is fully served in every "
                "month, so a contingency cell above its nominal cell is produced by the "
                "secondary per-scenario delivery objectives above the fairness floor, not "
                "by the budget regime."
            ),
            "nominal_only_ratios_company_132": {
                key[1]: value
                for key, value in sorted(nominal_only.period_service_ratio.items())
                if key[2] == "company_132"
            },
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    for case in cases:
        print("=" * 78)
        print(case["label"])
        print("  sorted rho        :", [round(value, 6) for value in case["sorted_rho"]])
        print("  RLex nominal af   :", round(case["nominal_af"], 1))
        print("  UTIL-BR nominal af:", round(case["utilitarian_nominal_af"], 1))
        print(
            "  PoF {:.2f}%   VoR {:.2f}%   robustness price {:.2f}%".format(
                case["price_of_fairness_pct"],
                case["value_of_recourse_pct"],
                case["price_of_robustness_pct"],
            )
        )
        print("  cells above nominal:", len(case["cells_above_nominal"]))
    print("=" * 78)
    print("guarantee vector invariant to budget regime:", invariant)
    print("wrote", OUTPUT)


if __name__ == "__main__":
    main()
