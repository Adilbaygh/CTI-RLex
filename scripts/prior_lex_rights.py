"""PRIOR-LEX with priority tiers assigned to rights rather than to claimants (Reviewer 1, point 2.1).

scripts/prior_lex.py ranks each claimant by the decree year of its most senior decreed right. For
ten of the twelve claimants with Utah rights the rights of that year carry the claimant's whole
peak diversion requirement, so ranking the claimant is ranking its rights. Wellsville-Mendon is
the exception that matters: it holds 2.4 cfs of 1860 rights, 1.0 cfs of 1867 and 1.0 cfs of 1875
against a peak requirement of 44.5 cfs, draws most of its water from Hyrum Reservoir, and shares
that water with Hyrum and Wellsville East Field. Ranking it in the first tier treats its stored
water as senior. Blacksmith Fork's 1877 rights also fall short (34 against 37.1 cfs), but it shares
water with no other claimant, so its tier cannot change anyone's allocation.

This variant splits the demand of every claimant whose senior-year rights do not carry its demand
and that shares a weakly connected component with another claimant. In each month its net demand
is assigned to its decree years in order of seniority: the rights of a year carry their flow (cfs)
times the days of the month, carried to the place of use along the most efficient path from their
points of diversion and multiplied by the application efficiency. The demand no decreed right
carries is the storage part. Each part becomes a claimant of its own, served by a terminal at the
same node with the same application efficiency, and enters the tier of its year (its rank among
the decree years of its river system); the storage part enters after every decreed year of the
system, as storage-only claimants do in the main PRIOR-LEX variant. Everything else is PRIOR-LEX.
The claimant-level guarantee of a split claimant is read back from the solution: the smallest
ratio, over scenarios and positive-demand periods, of the deliveries to all its parts to its
demand.

This variant was added after the claimant-level PRIOR-LEX results were known (requirements/
decisions.md, 2026-10-15); its expectations were written before its first run (requirements/
hypotheses.md, the third H-2.1 entry, dated 2026-10-15). It is reported as a post hoc analysis.

Run:  python scripts/prior_lex_rights.py
Writes: results/prior_lex_rights.json
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from leximin.dag import load_cti_benchmark, solve_cti_rlex  # noqa: E402
from leximin.dag.analysis import weakly_connected_components  # noqa: E402
from leximin.dag.domain import ClaimantTerminal  # noqa: E402

import prior_lex  # noqa: E402

OUTPUT = REPO / "results" / "prior_lex_rights.json"
VARIANT = "PRIOR-LEX"          # the main variant: storage ranks after every decreed right
UNCHANGED = 1e-4               # third H-2.1 entry of hypotheses.md, expectation 1
SAME = 1e-9                    # the check against claimant-level PRIOR-LEX where nothing is split
STORAGE = "storage"


def claimant_paths(payload: dict, claimant: str) -> list[dict]:
    owner = {row["terminal_node"]: row["claimant_id"] for row in payload["claimant_terminals"]}
    return [route for route in payload["paths"] if owner.get(route["terminal_node"]) == claimant]


def demand_parts(payload: dict, model, row: dict) -> tuple[dict[str, dict[str, float]], list[dict]]:
    """Net demand of one claimant split by decree year, the remainder being the storage part."""

    claimant = row["claimant"]
    days = {item["period_id"]: item["days"] for item in payload["periods"]}
    source_node = {item.source_id: item.node for item in model.sources}
    terminals = model.terminals_by_claimant[claimant]
    ends = {terminal.node for terminal in terminals}
    decreed = {item["right"]: item for item in row["path_rights"] if item["kind"] == "decree"}
    by_year: dict[int, dict] = {}
    for route in claimant_paths(payload, claimant):
        number = (route.get("water_right_number") or "").strip()
        if number in decreed:
            year = decreed[number]["decree_year"]
            entry = by_year.setdefault(year, {"rights": set(), "starts": set()})
            entry["rights"].add(number)
            entry["starts"].add(source_node[route["source_id"]])
    parts: dict[str, dict[str, float]] = defaultdict(dict)
    carried: list[dict] = []
    for period in model.periods:
        remaining = model.demand[period, claimant]
        alpha = min(model.application_efficiency[period, terminal.terminal_id] for terminal in terminals)
        for year in sorted(by_year):
            entry = by_year[year]
            flow = sum(decreed[number]["cfs"] for number in entry["rights"])
            efficiency = prior_lex.path_efficiency(model, period, entry["starts"], ends)
            capacity = flow * prior_lex.AF_PER_CFS_DAY * days[period] * efficiency * alpha
            share = min(remaining, capacity)
            parts[str(year)][period] = share
            remaining -= share
            carried.append({"period": period, "year": year, "rights": sorted(entry["rights"]), "cfs": flow,
                            "path_efficiency": efficiency, "net_capacity_af": capacity, "assigned_af": share})
        parts[STORAGE][period] = remaining
    return dict(parts), carried


def split_model(model, splits: dict[str, dict[str, dict[str, float]]]):
    """The benchmark with each split claimant replaced by one claimant per part."""

    claimants, terminals = [], []
    demand = {key: value for key, value in model.demand.items() if key[1] not in splits}
    alpha = {key: value for key, value in model.application_efficiency.items()}
    for claimant in model.claimants:
        if claimant not in splits:
            claimants.append(claimant)
            continue
        originals = model.terminals_by_claimant[claimant]
        for part, by_period in splits[claimant].items():
            if max(by_period.values()) <= 0.0:
                continue
            name = f"{claimant}#{part}"
            claimants.append(name)
            for period, value in by_period.items():
                demand[period, name] = value
            for terminal in originals:
                copy = ClaimantTerminal(terminal_id=f"{terminal.terminal_id}#{part}", claimant_id=name, node=terminal.node)
                terminals.append(copy)
                for period in model.periods:
                    alpha[period, copy.terminal_id] = model.application_efficiency[period, terminal.terminal_id]
    split_ids = {terminal.terminal_id for claimant in splits for terminal in model.terminals_by_claimant[claimant]}
    kept = [terminal for terminal in model.terminals if terminal.terminal_id not in split_ids]
    alpha = {key: value for key, value in alpha.items() if key[1] not in split_ids}
    return replace(
        model,
        benchmark_id=f"{model.benchmark_id}__rights",
        claimants=tuple(claimants),
        terminals=tuple(kept + terminals),
        demand=demand,
        application_efficiency=alpha,
    )


def right_tiers(table: list[dict], split_model_claimants: tuple[str, ...], splits: dict) -> list[list[str]]:
    """Rank every claimant or part by its decree year within its river system; storage last."""

    years = defaultdict(set)
    system = {}
    for row in table:
        system[row["claimant"]] = row["river_system"]
        if row["claimant"] in splits:
            years[row["river_system"]].update(int(part) for part in splits[row["claimant"]] if part != STORAGE)
        elif row["decree_year"] is not None:
            years[row["river_system"]].add(row["decree_year"])
    year_of = {row["claimant"]: row["decree_year"] for row in table}
    basis = {row["claimant"]: row["basis"] for row in table}
    rank = {}
    for name in split_model_claimants:
        claimant, _, part = name.partition("#")
        ranked = sorted(years[system[claimant]])
        if part and part != STORAGE:
            rank[name] = ranked.index(int(part)) + 1
        elif part == STORAGE or basis[claimant] == "storage only":
            rank[name] = len(ranked) + 1
        elif year_of[claimant] is not None:
            rank[name] = ranked.index(year_of[claimant]) + 1
        else:
            rank[name] = 1
    deepest = max(rank.values())
    return [[name for name in split_model_claimants if rank[name] == r] for r in range(1, deepest + 1)
            if any(rank[name] == r for name in split_model_claimants)]


def claimant_level(model, solution, claimant: str, parts: list[str]) -> float:
    """Smallest ratio, over scenarios and positive-demand periods, of all parts' deliveries to the demand."""

    terminals = [terminal.terminal_id for part in parts for terminal in model.terminals_by_claimant[part]]
    worst = float("inf")
    for scenario in model.scenarios:
        for period in model.periods:
            demand = sum(model.demand[period, part] for part in parts)
            if demand <= 0.0:
                continue
            delivered = sum(solution.beneficial_delivery[scenario, period, terminal] for terminal in terminals)
            worst = min(worst, delivered / demand)
    return worst


def main() -> None:
    started = time.perf_counter()
    points, rights_record = prior_lex.decree_records()
    report = {
        "rule": ("PRIOR-LEX (storage after every decreed right) with the demand of every claimant whose "
                 "senior-year rights do not carry it, and that shares its component with another claimant, "
                 "split by decree year; the remainder is the storage part"),
        "chosen": "requirements/decisions.md, 2026-10-15; expectations in requirements/hypotheses.md, third H-2.1 entry (2026-10-15)",
        "post_hoc": True,
        "water_rights": rights_record,
        "instances": {},
    }
    for instance, path in prior_lex.BENCHMARKS.items():
        began = time.perf_counter()
        payload = json.loads(path.read_text(encoding="utf-8"))
        model = load_cti_benchmark(path)
        table = prior_lex.tier_table(payload, model, points)
        component = weakly_connected_components(model)
        members = defaultdict(list)
        for claimant, label in component.items():
            members[label].append(claimant)

        splits, carried = {}, {}
        for row in table:
            if row["decree_year"] is None or row["rights_of_that_year_cover_the_peak"]:
                continue
            if len(members[component[row["claimant"]]]) < 2:
                continue
            splits[row["claimant"]], carried[row["claimant"]] = demand_parts(payload, model, row)

        claimant_tiers = prior_lex.tiers_of(table, VARIANT)
        claimant_level_solution = solve_cti_rlex(model, tiers=claimant_tiers)
        cti = solve_cti_rlex(model)
        result = {
            "benchmark_id": model.benchmark_id,
            "split_claimants": {
                claimant: {
                    "component": component[claimant],
                    "seasonal_demand_by_part_af": {part: sum(values.values()) for part, values in parts.items()},
                    "monthly_demand_by_part_af": parts,
                    "carried_by_year": carried[claimant],
                }
                for claimant, parts in splits.items()
            },
        }
        if splits:
            right_model = split_model(model, splits)
            tiers = right_tiers(table, right_model.claimants, splits)
            solution = solve_cti_rlex(right_model, tiers=tiers)
            guarantees = dict(solution.guarantees)
            aggregated = {name: value for name, value in guarantees.items() if "#" not in name}
            for claimant in splits:
                parts = [name for name in right_model.claimants if name.startswith(f"{claimant}#")]
                aggregated[claimant] = claimant_level(right_model, solution, claimant, parts)
            result.update({
                "tiers": tiers,
                "part_guarantees": {name: value for name, value in guarantees.items() if "#" in name},
                "levels": [{"theta": level.level, "blocked": list(level.blocked_claimants)}
                           for level in solution.leximin_levels],
                "nominal_beneficial_delivery_af": solution.nominal_beneficial_delivery,
                "weighted_contingency_beneficial_delivery_af": solution.weighted_contingency_beneficial_delivery,
                "maximum_residual": max(solution.residuals.values(), default=0.0),
            })
        else:
            solution = claimant_level_solution
            aggregated = dict(solution.guarantees)
            result.update({"tiers": claimant_tiers, "part_guarantees": {},
                           "nominal_beneficial_delivery_af": solution.nominal_beneficial_delivery,
                           "weighted_contingency_beneficial_delivery_af":
                               solution.weighted_contingency_beneficial_delivery,
                           "maximum_residual": max(solution.residuals.values(), default=0.0)})

        claimant_prior = dict(claimant_level_solution.guarantees)
        reference = dict(cti.guarantees)
        changed = {c: aggregated[c] - claimant_prior[c] for c in claimant_prior}
        split_components = {component[c] for c in splits}
        outside = [c for c in claimant_prior if component[c] not in split_components]
        floor = min(aggregated.values())
        result.update({
            "claimant_guarantees": aggregated,
            "claimant_level_prior_lex": claimant_prior,
            "cti_rlex": reference,
            "change_against_claimant_level_prior_lex": changed,
            "least_served": sorted(c for c, value in aggregated.items() if value <= floor + prior_lex.TOLERANCE),
            "minimum_guarantee": floor,
            "nominal_delivery_change_against_claimant_level_af": (
                result["nominal_beneficial_delivery_af"] - claimant_level_solution.nominal_beneficial_delivery),
            "checks_and_expectations": {
                "same_as_claimant_level_where_nothing_is_split": (
                    max(abs(d) for d in changed.values()) <= SAME if not splits else None),
                "1_outside_split_components_unchanged": (
                    max((abs(changed[c]) for c in outside), default=0.0) < UNCHANGED if splits else None),
                "largest_change_outside_split_components": max((abs(changed[c]) for c in outside), default=0.0),
                "2_split_component": {
                    claimant: {
                        "others_rise_above_claimant_level": {
                            other: aggregated[other] > claimant_prior[other] + prior_lex.TOLERANCE
                            for other in members[component[claimant]] if other != claimant},
                        "split_claimant_falls_below_claimant_level": (
                            aggregated[claimant] < claimant_prior[claimant] - prior_lex.TOLERANCE),
                    }
                    for claimant in splits
                },
            },
            "seconds": round(time.perf_counter() - began, 1),
        })
        report["instances"][instance] = result

        print(f"== {instance}: split {sorted(splits) or 'none'}")
        for claimant in sorted(aggregated, key=aggregated.get):
            print(f"   {claimant:16s} {aggregated[claimant]:.4f}  claimant-level PRIOR-LEX {claimant_prior[claimant]:.4f}"
                  f"  CTI-RLex {reference[claimant]:.4f}")
        if splits:
            print(f"   parts {[(k, round(v, 4)) for k, v in result['part_guarantees'].items()]}; tiers {result['tiers']}")
    report["seconds"] = round(time.perf_counter() - started, 1)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(REPO)} in {report['seconds']} s")


if __name__ == "__main__":
    main()
