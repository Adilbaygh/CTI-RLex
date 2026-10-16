"""Both benchmarks re-solved with larger canal conveyance losses (Reviewer 2; Reviewer 1, point 1.4).

The benchmarks give every canal reach the efficiency exp(-lambda * L) with lambda = 0.005 per km,
an assumed rate. Published values place it at the low end: FAO's indicative conveyance
efficiency for adequately maintained earthen canals longer than 2 km is 0.60-0.80, and the
seepage measured in 2008 on reaches of the Logan and Blacksmith Fork canals has a median of
2.8 L/s per 100 m, which is 1-2.8 % of the flow per km at 35-100 cfs. This script multiplies
the canal loss rate by k = 2, 4 and 6 (1, 2 and 3 % per km), so that the efficiency of every
canal reach becomes eta ** k. Stream reaches, logical connectors, the effort coefficients and
everything else stay as published, as in the factorial design.

For each instance and each k it solves CTI-RLex, PROP-BR, the fairness-optimistic UTIL-BR
and the rigid plan (all recourse budgets zero), and reports the sorted guarantee vectors,
the first position at which CTI-RLex and PROP-BR differ, the claimants each leaves at its
floor, nominal delivery, the price of fairness against UTIL-BR, the value of recourse
against the rigid plan, the conveyance efficiency of every official route, and the peak
diversion requirement of every claimant with decreed rights (the requirement at its decreed
points of diversion, as in scripts/prior_lex.py).

The design and the expectations were written before the first run (requirements/decisions.md
and requirements/hypotheses.md, H-R2.1, 2026-10-15); the script evaluates them and records
the outcome without changing them.

Run:  python scripts/conveyance_loss_levels.py
Writes: results/conveyance_loss_levels.json
"""

from __future__ import annotations

import json
import math
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from leximin.dag import (  # noqa: E402
    load_cti_benchmark,
    solve_cti_rlex,
    solve_robust_proportional,
    solve_utilitarian_fair,
)

import prior_lex  # noqa: E402

BENCHMARKS = prior_lex.BENCHMARKS
OUTPUT = REPO / "results" / "conveyance_loss_levels.json"
PUBLISHED = REPO / "results" / "prior_lex.json"   # CTI-RLex, PROP-BR and UTIL-BR as published

CANAL_BASIS = "assumed_exp_length_decay_0.005_per_km"
CANAL_RATE_PER_KM = 0.005
MULTIPLIERS = (1, 2, 4, 6)
TOLERANCE = 1e-7          # blocking tolerance: two guarantees closer than this are one level
SAME_AS_PUBLISHED = 1e-9  # the k = 1 check
DROP_EXPECTED = 0.15      # H-R2.1, expectation 2


def canal_edges(payload: dict, model) -> set[str]:
    """The canal reaches, after checking that each carries exp(-0.005 L) in every scenario and period."""

    canals = set()
    for edge in payload["edges"]:
        if edge["efficiency_basis"] != CANAL_BASIS:
            continue
        expected = math.exp(-CANAL_RATE_PER_KM * float(edge["length_m"]) / 1000.0)
        for key, eta in model.edge_efficiency.items():
            if key[2] == edge["edge_id"] and abs(eta - expected) > 1e-9:
                raise SystemExit(f"{edge['edge_id']}: efficiency {eta} is not exp(-0.005 L) = {expected}")
        canals.add(edge["edge_id"])
    return canals


def with_canal_losses(model, canals: set[str], k: int):
    efficiency = {key: (eta ** k if key[2] in canals else eta) for key, eta in model.edge_efficiency.items()}
    return replace(model, benchmark_id=f"{model.benchmark_id}__canal_loss_x{k}", edge_efficiency=efficiency)


def route_efficiencies(payload: dict, model) -> dict:
    """Conveyance efficiency of every official route: the product over the reaches it lists."""

    period = model.periods[0]
    listed = defaultdict(set)
    for row in payload["path_edges"]:
        listed[row["path_id"]].add(row["edge_id"])
    known = set(model.edge_ids)
    values = sorted(
        math.prod(model.edge_efficiency[model.nominal_scenario, period, edge] for edge in edges if edge in known)
        for edges in listed.values()
    )
    return {"routes": len(values), "minimum": values[0], "median": statistics.median(values), "maximum": values[-1]}


def at_floor(guarantees: dict) -> list[str]:
    floor = min(guarantees.values())
    return sorted(claimant for claimant, value in guarantees.items() if value <= floor + TOLERANCE)


def first_difference(left: list[float], right: list[float]) -> tuple[int | None, str | None]:
    for position, (a, b) in enumerate(zip(left, right), start=1):
        if abs(a - b) > TOLERANCE:
            return position, ("CTI-RLex" if a > b else "PROP-BR")
    return None, None


def method_block(solution) -> dict:
    guarantees = dict(solution.guarantees)
    return {
        "guarantees": guarantees,
        "sorted": sorted(guarantees.values()),
        "minimum_guarantee": min(guarantees.values()),
        "claimants_at_floor": at_floor(guarantees),
        "levels": len(solution.leximin_levels),
        "nominal_beneficial_delivery_af": solution.nominal_beneficial_delivery,
        "weighted_contingency_beneficial_delivery_af": solution.weighted_contingency_beneficial_delivery,
        "maximum_residual": max(solution.residuals.values(), default=0.0),
    }


def level_report(payload: dict, model, points: dict) -> dict:
    cti = method_block(solve_cti_rlex(model))
    prop = method_block(solve_robust_proportional(model))
    util = method_block(solve_utilitarian_fair(model))
    rigid_model = replace(model, recourse_budget={scenario: 0.0 for scenario in model.scenarios})
    rigid = method_block(solve_cti_rlex(rigid_model))
    position, higher = first_difference(cti["sorted"], prop["sorted"])
    requirements = {
        row["claimant"]: row["peak_diversion_requirement_cfs"]
        for row in prior_lex.tier_table(payload, model, points)
        if row.get("peak_diversion_requirement_cfs") is not None
    }
    return {
        "route_conveyance_efficiency": route_efficiencies(payload, model),
        "peak_diversion_requirement_cfs": requirements,
        "methods": {"CTI-RLex": cti, "PROP-BR": prop, "UTIL-BR": util, "CTI-RLex rigid": rigid},
        "cti_rlex_against_prop_br": {"first_differing_position": position, "higher_there": higher},
        "price_of_fairness_percent": 100.0 * (util["nominal_beneficial_delivery_af"]
                                              - cti["nominal_beneficial_delivery_af"])
                                     / util["nominal_beneficial_delivery_af"],
        "value_of_recourse_percent": (100.0 * (cti["minimum_guarantee"] - rigid["minimum_guarantee"])
                                      / rigid["minimum_guarantee"]) if rigid["minimum_guarantee"] > 0 else None,
    }


def published_check(instance: str, level: dict) -> dict:
    published = json.loads(PUBLISHED.read_text(encoding="utf-8"))["instances"][instance]["methods"]
    shifts = {}
    for method in ("CTI-RLex", "PROP-BR", "UTIL-BR"):
        mine, theirs = level["methods"][method]["guarantees"], published[method]["guarantees"]
        shifts[method] = max(abs(mine[c] - theirs[c]) for c in theirs)
    return {"largest_guarantee_shift": shifts,
            "same_as_published": all(shift <= SAME_AS_PUBLISHED for shift in shifts.values())}


def evaluate(report: dict) -> dict:
    """The expectations of H-R2.1, evaluated as written."""

    lbr = report["instances"]["little_bear_v2"]["levels"]
    cv = report["instances"]["cache_valley_v4"]["levels"]
    keys = [str(k) for k in MULTIPLIERS]

    def minima(levels):
        return [levels[k]["methods"]["CTI-RLex"]["minimum_guarantee"] for k in keys]

    def non_increasing(values):
        return all(b <= a + TOLERANCE for a, b in zip(values, values[1:]))

    lbr_base, lbr_six = minima(lbr)[0], minima(lbr)[-1]
    return {
        "1_minimum_guarantee_non_increasing_in_k": {
            "little_bear_v2": non_increasing(minima(lbr)), "cache_valley_v4": non_increasing(minima(cv))},
        "2_little_bear_minimum_at_k6_at_least_15_percent_lower": {
            "drop_percent": 100.0 * (lbr_base - lbr_six) / lbr_base,
            "holds": lbr_six <= (1.0 - DROP_EXPECTED) * lbr_base},
        "3_little_bear_rules_coincide_at_every_k": all(
            lbr[k]["cti_rlex_against_prop_br"]["first_differing_position"] is None for k in keys),
        "4_cache_valley_cti_rlex_strictly_above_prop_br_with_fewer_at_floor": all(
            cv[k]["cti_rlex_against_prop_br"]["higher_there"] == "CTI-RLex"
            and len(cv[k]["methods"]["CTI-RLex"]["claimants_at_floor"])
            < len(cv[k]["methods"]["PROP-BR"]["claimants_at_floor"])
            for k in keys),
        "5_util_br_minimum_strictly_below_cti_rlex_at_every_k": {
            instance: all(
                levels[k]["methods"]["UTIL-BR"]["minimum_guarantee"]
                < levels[k]["methods"]["CTI-RLex"]["minimum_guarantee"] - TOLERANCE
                for k in keys)
            for instance, levels in (("little_bear_v2", lbr), ("cache_valley_v4", cv))},
    }


def main() -> None:
    started = time.perf_counter()
    points, rights_record = prior_lex.decree_records()
    report = {
        "design": ("canal reach efficiency eta -> eta ** k (canal loss rate 0.5 % per km times k); stream "
                   "reaches, logical connectors, effort coefficients and all other data as published"),
        "chosen": "requirements/decisions.md, 2026-10-15; expectations in requirements/hypotheses.md, H-R2.1",
        "multipliers": list(MULTIPLIERS),
        "canal_loss_rate_percent_per_km": {str(k): 100.0 * CANAL_RATE_PER_KM * k for k in MULTIPLIERS},
        "water_rights": rights_record,
        "instances": {},
    }
    for instance, path in BENCHMARKS.items():
        began = time.perf_counter()
        payload = json.loads(path.read_text(encoding="utf-8"))
        model = load_cti_benchmark(path)
        canals = canal_edges(payload, model)
        levels = {}
        for k in MULTIPLIERS:
            levels[str(k)] = level_report(payload, with_canal_losses(model, canals, k), points)
            item = levels[str(k)]
            print(f"{instance} k={k}: routes {item['route_conveyance_efficiency']['minimum']:.3f}-"
                  f"{item['route_conveyance_efficiency']['maximum']:.3f}; CTI-RLex "
                  f"{[round(v, 4) for v in item['methods']['CTI-RLex']['sorted']]}; PROP-BR first differs at "
                  f"{item['cti_rlex_against_prop_br']['first_differing_position']}; UTIL-BR min "
                  f"{item['methods']['UTIL-BR']['minimum_guarantee']:.4f}; PoF {item['price_of_fairness_percent']:.2f}%")
        report["instances"][instance] = {
            "benchmark_id": model.benchmark_id,
            "canal_reaches": len(canals),
            "k1_against_published": published_check(instance, levels["1"]),
            "levels": levels,
            "seconds": round(time.perf_counter() - began, 1),
        }
    report["expectations"] = evaluate(report)
    report["seconds"] = round(time.perf_counter() - started, 1)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report["expectations"], indent=1))
    print(f"wrote {OUTPUT.relative_to(REPO)} in {report['seconds']} s")


if __name__ == "__main__":
    main()
