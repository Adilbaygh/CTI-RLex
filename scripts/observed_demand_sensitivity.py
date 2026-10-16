"""Re-solve the three-claimant benchmark with each claimant's demand set to its measured 2025
diversion (Reviewer 1, point 2.2).

The comparison with the canal records (scripts/station_comparison.py) found that two of the three
claimants diverted two to three times the benchmark's gross requirement in 2025, and the third
less than it. The benchmark's demand -- irrigated acreage times an assumed duty of 2.0 acre-feet
per acre, spread by an assumed monthly profile -- is therefore not the demand the canals served.
This script asks whether the article's conclusions hold when the demand is the measured one.

The variant. For each claimant and period, the measured diversion of each of its canals is
carried down to the place of use with the efficiencies of the benchmark's reaches below the
station (scripts/station_comparison.py, efficiency_to_place_of_use) and multiplied by the
claimant's application efficiency: the net demand that the measured diversion would have served
in full. A canal the network does not contain (the Little Feeder, station 2772) delivers at the
place of use. A month counts as the comparison counts it: with at least 90% of its days recorded
it is the mean of the recorded days times the days of the month; otherwise it is the sum of the
recorded days, the days without a record being taken as days without diversion (in 2025 they lie
at the start and the end of the season). Stations on one reach measure one flow, so Paradise is
taken from station 2776 in one variant and from station 9738 in the other. Everything else is the
published benchmark: network, capacities, losses, sources, scenarios and recourse budgets.

The effort coefficient of each recourse control is the inverse of the seasonal gross demand the
control reaches (generate_benchmark.py), so it depends on demand; the variant recomputes it by
that rule. Each variant is solved a second time with the published coefficients, as the factorial
design of the article does when it varies the demand duty, to show whether the choice matters.

Each instance -- the published benchmark first, as the reference -- is solved with the five
methods of the article's method comparison (scripts/run_cti_experiments.py): UTIL-BR, PROP-BR,
CTI-RLex rigid, CTI-RLex proposed and CTI-RLex nominal only. Reported: the demand of each
claimant, each method's guarantees and deliveries, the price of fairness, the value of recourse,
the robustness cost, and the first sorted position at which CTI-RLex and PROP-BR differ.

Hypothesis H-2.2b (requirements/hypotheses.md) was written before the variant was solved.

Run:  python scripts/observed_demand_sensitivity.py
Writes: results/observed_demand_sensitivity.json
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import station_comparison as observed  # noqa: E402
from leximin.dag import (  # noqa: E402
    load_cti_benchmark,
    scale_benchmark,
    solve_cti_rlex,
    solve_robust_proportional,
    solve_utilitarian_fair,
    subset_scenarios,
)

BENCHMARK = observed.BENCHMARK
OBSERVED = observed.OBSERVED
OUTPUT = REPO / "results" / "observed_demand_sensitivity.json"
TOLERANCE = 1e-6  # two sorted guarantees closer than this are the same


def measured_month(daily: dict, month: int) -> tuple[float, dict]:
    """The month's measured diversion in acre-feet, by the comparison's coverage rule."""

    record = observed.month_record(daily, month)
    volume = record["volume_af"] if record["tested"] else record["recorded_volume_af"]
    return volume, record


def observed_demand(payload: dict, model, choice: dict[str, str]) -> tuple[dict, dict]:
    """Net demand per (period, claimant) from the measured diversions of the chosen stations."""

    nominal = model.nominal_scenario
    linked = {str(row["station_id"]): row["linked_edge_id"] or None for row in payload["measurement_stations"]}
    demand: dict[tuple[str, str], float] = {}
    detail: dict[str, dict] = {}
    for claimant in model.claimants:
        terminal = model.terminals_by_claimant[claimant][0]
        stations = choice[claimant]
        daily = {
            station: observed.read_daily(OBSERVED / f"dailydata-{station}-2025-2025.csv")[1]
            for station in stations
        }
        rows = {}
        for period in model.periods:
            month = int(period.split("-")[1])
            at_place_of_use = 0.0
            parts = {}
            for station in stations:
                volume, record = measured_month(daily[station], month)
                edge = linked[station]
                efficiency = (
                    observed.efficiency_to_place_of_use(payload, model, edge, terminal.node, period)
                    if edge is not None
                    else 1.0
                )
                at_place_of_use += volume * efficiency
                parts[station] = {
                    "measured_af": volume,
                    "days_recorded": record["days_recorded"],
                    "days": record["days"],
                    "efficiency_to_place_of_use": efficiency,
                }
            alpha = model.application_efficiency[period, terminal.terminal_id]
            demand[period, claimant] = alpha * at_place_of_use
            rows[period] = {
                "stations": parts,
                "gross_at_place_of_use_af": at_place_of_use,
                "application_efficiency": alpha,
                "net_demand_af": demand[period, claimant],
                "published_net_demand_af": model.demand[period, claimant],
            }
        detail[claimant] = {
            "stations": stations,
            "periods": rows,
            "seasonal_net_demand_af": sum(demand[period, claimant] for period in model.periods),
            "published_seasonal_net_demand_af": sum(model.demand[period, claimant] for period in model.periods),
        }
        detail[claimant]["ratio_to_published"] = (
            detail[claimant]["seasonal_net_demand_af"] / detail[claimant]["published_seasonal_net_demand_af"]
        )
    return demand, detail


def recomputed_controls(payload: dict, model, demand: dict) -> tuple:
    """Effort coefficients by the generator's rule: one over the seasonal gross demand that the
    control reaches."""

    reach = {row["control_asset_id"]: row["reachable_claimants"].split("|") for row in payload["control_assets"]}
    gross = {
        claimant: sum(
            demand[period, claimant]
            / model.application_efficiency[period, model.terminals_by_claimant[claimant][0].terminal_id]
            for period in model.periods
        )
        for claimant in model.claimants
    }
    return tuple(
        replace(asset, effort_coefficient=1.0 / sum(gross[claimant] for claimant in reach[asset.asset_id]))
        for asset in model.controls
    )


def solve_methods(model) -> dict[str, dict]:
    runs = (
        ("UTIL-BR", model, solve_utilitarian_fair),
        ("PROP-BR", model, solve_robust_proportional),
        ("CTI-RLex rigid", scale_benchmark(model, demand_duty=2.0, conveyance_loss_multiplier=1.0,
                                           source_limit_scale=1.0, recourse_budget_scale=0.0), solve_cti_rlex),
        ("CTI-RLex proposed", model, solve_cti_rlex),
        ("CTI-RLex nominal only", subset_scenarios(model, (model.nominal_scenario,)), solve_cti_rlex),
    )
    results = {}
    for method, instance, solver in runs:
        solution = solver(instance)
        guarantees = dict(solution.guarantees)
        results[method] = {
            "guarantees": guarantees,
            "sorted": sorted(guarantees.values()),
            "minimum_guarantee": min(guarantees.values()),
            "levels": len(solution.leximin_levels),
            "nominal_beneficial_delivery_af": solution.nominal_beneficial_delivery,
            "weighted_contingency_beneficial_delivery_af": solution.weighted_contingency_beneficial_delivery,
            "normalized_recourse_effort": solution.normalized_recourse_effort,
            "maximum_residual": max(solution.residuals.values(), default=0.0),
        }
    return results


def indicators(methods: dict[str, dict]) -> dict:
    proposed, rigid = methods["CTI-RLex proposed"], methods["CTI-RLex rigid"]
    util, nominal_only, prop = methods["UTIL-BR"], methods["CTI-RLex nominal only"], methods["PROP-BR"]
    first = next(
        (index + 1 for index, (a, b) in enumerate(zip(proposed["sorted"], prop["sorted"])) if abs(a - b) > TOLERANCE),
        None,
    )
    return {
        "price_of_fairness_percent": 100.0 * (1.0 - proposed["nominal_beneficial_delivery_af"]
                                              / util["nominal_beneficial_delivery_af"]),
        "util_minimum_below_cti_rlex": util["minimum_guarantee"] < proposed["minimum_guarantee"] - TOLERANCE,
        "value_of_recourse_absolute": proposed["minimum_guarantee"] - rigid["minimum_guarantee"],
        "value_of_recourse_percent": (
            100.0 * (proposed["minimum_guarantee"] / rigid["minimum_guarantee"] - 1.0)
            if rigid["minimum_guarantee"] > 0 else None
        ),
        "robustness_cost_percent": 100.0 * (1.0 - proposed["nominal_beneficial_delivery_af"]
                                            / nominal_only["nominal_beneficial_delivery_af"]),
        "first_sorted_position_cti_rlex_and_prop_br_differ": first,
        "cti_rlex_above_prop_br_there": (
            None if first is None else proposed["sorted"][first - 1] > prop["sorted"][first - 1]
        ),
    }


def main() -> None:
    started = time.perf_counter()
    payload = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    model = load_cti_benchmark(BENCHMARK)
    names = {row["claimant_id"]: row["claimant_name"] for row in payload["claimants"]}

    # The stations of each claimant, grouped by reach: a group with several stations gives
    # alternatives, and every combination of alternatives is one variant.
    linked = {str(row["station_id"]): row["linked_edge_id"] or f"unlinked:{row['station_id']}"
              for row in payload["measurement_stations"]}
    options: dict[str, list[list[str]]] = {}
    for row in payload["claimants"]:
        groups: dict[str, list[str]] = defaultdict(list)
        for station in (item.strip() for item in row["measurement_station_ids"].split(",")):
            if station:
                groups[linked[station]].append(station)
        options[row["claimant_id"]] = [list(combination) for combination in itertools.product(*groups.values())]
    claimants = list(model.claimants)
    choices = [dict(zip(claimants, combination)) for combination in itertools.product(*(options[c] for c in claimants))]

    reference = solve_methods(model)
    output = {
        "benchmark_id": model.benchmark_id,
        "reference": {"methods": reference, "indicators": indicators(reference)},
        "variants": {},
    }
    for choice in choices:
        name = "observed_" + "_".join("+".join(choice[claimant]) for claimant in claimants)
        demand, detail = observed_demand(payload, model, choice)
        variant = replace(model, benchmark_id=f"{model.benchmark_id}__{name}", demand=demand,
                          controls=recomputed_controls(payload, model, demand))
        kept = replace(variant, controls=model.controls)
        methods = solve_methods(variant)
        published_coefficients = solve_methods(kept)
        same = {
            method: max(abs(a - b) for a, b in zip(methods[method]["sorted"], published_coefficients[method]["sorted"]))
            for method in methods
        }
        output["variants"][name] = {
            "stations": choice,
            "demand": {claimant: {"claimant_name": names[claimant], **detail[claimant]} for claimant in claimants},
            "effort_coefficients": {asset.asset_id: asset.effort_coefficient for asset in variant.controls},
            "methods": methods,
            "indicators": indicators(methods),
            "with_published_effort_coefficients": {
                "methods": published_coefficients,
                "indicators": indicators(published_coefficients),
                "largest_change_in_any_sorted_guarantee": same,
            },
        }
    output["seconds"] = round(time.perf_counter() - started, 1)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    def show(label: str, block: dict) -> None:
        print(f"== {label}")
        for method, row in block["methods"].items():
            print(f"   {method:22s} sorted {[round(value, 4) for value in row['sorted']]}  nominal "
                  f"{row['nominal_beneficial_delivery_af']:8.1f}  contingency {row['weighted_contingency_beneficial_delivery_af']:8.1f}")
        item = block["indicators"]
        print(f"   price of fairness {item['price_of_fairness_percent']:.2f}%  (UTIL-BR minimum below CTI-RLex: "
              f"{item['util_minimum_below_cti_rlex']}); value of recourse {item['value_of_recourse_absolute']:.4f} "
              f"({item['value_of_recourse_percent'] if item['value_of_recourse_percent'] is None else round(item['value_of_recourse_percent'], 2)}%); "
              f"robustness cost {item['robustness_cost_percent']:.1f}%; CTI-RLex vs PROP-BR first differ at "
              f"{item['first_sorted_position_cti_rlex_and_prop_br_differ']} (CTI-RLex above: {item['cti_rlex_above_prop_br_there']})")

    show("published benchmark", output["reference"])
    for name, block in output["variants"].items():
        for claimant, row in block["demand"].items():
            print(f"   {claimant:12s} {row['claimant_name'][:28]:28s} stations {'+'.join(row['stations']):10s} seasonal net demand "
                  f"{row['seasonal_net_demand_af']:8.1f} af (published {row['published_seasonal_net_demand_af']:8.1f}; x{row['ratio_to_published']:.2f})")
        show(name, block)
        print(f"   with the published effort coefficients, largest change in a sorted guarantee: "
              f"{max(block['with_published_effort_coefficients']['largest_change_in_any_sorted_guarantee'].values()):.2e}")
    print(f"wrote {OUTPUT.relative_to(REPO)} in {output['seconds']} s")


if __name__ == "__main__":
    main()
