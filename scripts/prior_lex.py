"""The priority comparator PRIOR-LEX: CTI-RLex subordinated to decree priority (Reviewer 1,
point 2.1).

Reviewer 1 asked how the allocation relates to prior appropriation, the doctrine that governs
Utah water, and suggested that the max-min optimization be applied lexicographically subordinate
to the existing legal priority tiers. PRIOR-LEX does exactly that. The claimants are ordered in
priority tiers; the progressive filling of CTI-RLex runs on the first tier while every later
claimant carries no floor; the first tier's guarantees are fixed; only then is the next tier
filled (solve_cti_rlex with tiers). Inside a tier the filling is the leximin of CTI-RLex, so
claimants of one priority share a shortage in equal proportion, as rights of one priority do.
The secondary stages -- nominal delivery, contingency delivery, recourse effort -- are those of
CTI-RLex.

The tiers come from the water rights on each claimant's official paths and their decree records
in the Utah Division of Water Rights' points of diversion (DATA/Utah_Water_Rights_2026):
  * the river system of a right is the river its decree names as source, forks included: the
    Little Bear River (South Fork, East Fork, main stem) and the Logan River. Porcupine
    Reservoir impounds the East Fork and Hyrum Reservoir the main stem of the Little Bear River,
    so a release from either is water of that system;
  * a claimant's year is the decree year of its most senior decreed right on its paths;
  * within a river system the claimants are ranked by that year. A claimant with no decreed right
    on its paths that draws on a reservoir of the system -- storage only -- ranks after every
    decreed right of the system in the main variant; in the sensitivity variant, where stored
    water is shared by contract rather than by priority, it ranks first;
  * a claimant whose path rights are not in the Utah layer (the two Idaho rights) and that draws
    on no Utah reservoir shares its water with no other claimant, so it is alone in its system
    and ranks first;
  * tier k holds the claimants of rank k in every system. Claimants of different systems do not
    draw on the same water; they meet only in the recourse budget each scenario shares.
The author chose this rule before PRIOR-LEX was first solved (requirements/decisions.md,
2026-10-12), and the expectations it is checked against were written before as well
(requirements/hypotheses.md, H-2.1 and H-2.1b).

The rule ranks claimants, not rights. Whether that loses anything is a matter of the data: for
each claimant the script compares the flow of its rights of its senior decree year with its
peak diversion requirement -- the gross requirement at the place of use carried up to the point
of diversion along the most efficient path of the network, in the month that needs most. Where
the rights of the senior year cover the requirement, ranking the claimant is ranking its rights.

For each instance the script reports this tier table and solves CTI-RLex, PRIOR-LEX in both
variants, UTIL-BR and PROP-BR: guarantees by claimant and sorted, leximin levels (with their
tier), nominal and weighted contingency delivery, recourse effort and LP residuals. Each PRIOR-LEX
variant is then compared with CTI-RLex claimant by claimant.

Run:  python scripts/prior_lex.py
Writes: results/prior_lex.json
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from leximin.dag import (  # noqa: E402
    load_cti_benchmark,
    solve_cti_rlex,
    solve_robust_proportional,
    solve_utilitarian_fair,
)

BENCHMARKS = {
    "little_bear_v2": REPO / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json",
    "cache_valley_v4": REPO / "DATA" / "CacheValley_2025_Benchmark" / "benchmark.json",
}
RIGHTS = REPO / "DATA" / "Utah_Water_Rights_2026"
OUTPUT = REPO / "results" / "prior_lex.json"

AF_PER_CFS_DAY = 86400.0 / 43560.0   # acre-feet carried by one cubic foot per second in a day
TOLERANCE = 1e-7                     # the solver's blocking and preservation tolerance
MOVED = 1e-4                         # a guarantee that changes by more than this has moved
RESERVOIR_SYSTEM = {"Porcupine Reservoir": "Little Bear River", "Hyrum Reservoir": "Little Bear River"}
FORK = re.compile(r"^(?:(?:North|South|East|West|Middle) Fork(?: of)?|Unnamed Springs) ", re.IGNORECASE)
VARIANTS = {"PRIOR-LEX": "last", "PRIOR-LEX storage shared": "first"}

RULE = (
    "A claimant's tier is the rank, within its river system, of the decree year of its most senior "
    "decreed water right on its official paths (Utah Division of Water Rights, points of diversion, "
    "decree records). River systems: the Little Bear River (South Fork, East Fork, main stem; "
    "Porcupine and Hyrum reservoirs) and the Logan River. A claimant with no decreed right on its "
    "paths that draws on a reservoir of a system ranks after every decreed right of that system "
    "(PRIOR-LEX) or first (PRIOR-LEX storage shared). A claimant whose rights are not in the Utah "
    "layer and that draws on no Utah reservoir is alone in its system and ranks first. Tier k holds "
    "the claimants of rank k of every system; inside a tier the allocation is the leximin of CTI-RLex."
)


def river_system(source: str) -> str:
    """The river a decree names as source, without the fork: 'East Fork of Little Bear River' ->
    'Little Bear River'."""

    return FORK.sub("", " ".join(source.split()))


def decree_records() -> tuple[dict[str, list[dict]], dict]:
    path = RIGHTS / "points_of_diversion.csv"
    provenance = json.loads((RIGHTS / "provenance.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != provenance["sha256"]:
        raise SystemExit(f"{path} has SHA-256 {digest}, its provenance records {provenance['sha256']}")
    points: dict[str, list[dict]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            points[row["WRNUM"]].append(row)
    return points, {"file": str(path.relative_to(REPO)).replace("\\", "/"), "sha256": digest,
                    "retrieved_utc": provenance["retrieved_utc"],
                    "layer_data_last_edit_utc": provenance["layer_data_last_edit_utc"]}


def right_record(number: str, points: dict[str, list[dict]]) -> dict:
    """Priority, flow and source of a water right, from its decree records."""

    rows = points.get(number, [])
    if not rows:
        return {"right": number, "kind": "not in the Utah layer"}
    decreed = [row for row in rows if row["TYPE_OF_RIGHT"] == "Decree"]
    if not decreed:
        kinds = sorted({row["TYPE_OF_RIGHT"] for row in rows})
        dates = sorted({row["PRIORITY"] for row in rows if row["PRIORITY"]})
        return {"right": number, "kind": "not decreed", "record_types": kinds, "priorities": dates}
    priorities = {row["PRIORITY"] for row in decreed}
    flows = {float(row["CFS"]) for row in decreed}
    sources = {river_system(row["SOURCE"]) for row in decreed}
    if len(priorities) != 1 or len(flows) != 1 or len(sources) != 1:
        raise SystemExit(f"{number}: decree records disagree: {priorities}, {flows}, {sources}")
    priority = priorities.pop()
    return {
        "right": number,
        "kind": "decree",
        "priority": priority,
        "decree_year": int(priority[:4]),
        "cfs": flows.pop(),
        "source": sorted({row["SOURCE"] for row in decreed}),
        "river_system": sources.pop(),
    }


def path_efficiency(model, period: str, start_nodes: set[str], end_nodes: set[str]) -> float:
    """The largest product of nominal reach efficiencies along a path from a start to an end node."""

    outgoing = defaultdict(list)
    indegree = {node: 0 for node in model.nodes}
    for edge in model.edges:
        outgoing[edge.tail].append(edge)
        indegree[edge.head] += 1
    order, ready = [], [node for node in model.nodes if indegree[node] == 0]
    while ready:
        node = ready.pop()
        order.append(node)
        for edge in outgoing[node]:
            indegree[edge.head] -= 1
            if indegree[edge.head] == 0:
                ready.append(edge.head)
    best = {node: (1.0 if node in start_nodes else 0.0) for node in model.nodes}
    for node in order:
        for edge in outgoing[node]:
            carried = best[node] * model.edge_efficiency[model.nominal_scenario, period, edge.edge_id]
            if carried > best[edge.head]:
                best[edge.head] = carried
    return max(best[node] for node in end_nodes)


def tier_table(payload: dict, model, points: dict[str, list[dict]]) -> list[dict]:
    names = {row["claimant_id"]: row["claimant_name"] for row in payload["claimants"]}
    owner = {row["terminal_node"]: row["claimant_id"] for row in payload["claimant_terminals"]}
    source = {row["source_id"]: row for row in payload["sources"]}
    source_node = {item.source_id: item.node for item in model.sources}
    days = {row["period_id"]: row["days"] for row in payload["periods"]}

    table = []
    for claimant in model.claimants:
        paths = [route for route in payload["paths"] if owner.get(route["terminal_node"]) == claimant]
        rights = {}
        decreed_sources: set[str] = set()
        reservoirs = set()
        for route in paths:
            number = (route.get("water_right_number") or "").strip()
            origin = source[route["source_id"]]
            if origin["source_class"] == "reservoir_release":
                reservoirs.add(origin["source_name"])
            if number:
                rights.setdefault(number, right_record(number, points))
                if rights[number]["kind"] == "decree":
                    decreed_sources.add(route["source_id"])
        decreed = [item for item in rights.values() if item["kind"] == "decree"]
        reservoir_systems = {RESERVOIR_SYSTEM[name] for name in reservoirs}
        row = {
            "claimant": claimant,
            "name": names[claimant],
            "path_rights": [rights[number] for number in sorted(rights)],
            "reservoirs": sorted(reservoirs),
        }
        if decreed:
            systems = {item["river_system"] for item in decreed}
            if len(systems) != 1 or not reservoir_systems <= systems:
                raise SystemExit(f"{claimant}: rights in more than one river system: {systems | reservoir_systems}")
            # A decree may give the year alone ('1860'); it then sorts before the dated rights of its year.
            senior = min((item["priority"] for item in decreed), key=lambda date: date.ljust(8, "0"))
            year = int(senior[:4])
            of_that_year = [item for item in decreed if item["decree_year"] == year]
            terminals = model.terminals_by_claimant[claimant]
            ends = {terminal.node for terminal in terminals}
            starts = {source_node[item] for item in decreed_sources}
            requirement = {}
            for period in model.periods:
                alpha = min(model.application_efficiency[period, terminal.terminal_id] for terminal in terminals)
                efficiency = path_efficiency(model, period, starts, ends)
                if efficiency <= 0.0:
                    raise SystemExit(f"{claimant}: no path from its decreed diversions reaches it in {period}")
                gross = model.demand[period, claimant] / alpha
                requirement[period] = gross / efficiency / (AF_PER_CFS_DAY * days[period])
            peak = max(requirement, key=requirement.get)
            flow = sum(item["cfs"] for item in of_that_year)
            row.update({
                "basis": "decreed right on its paths",
                "river_system": systems.pop(),
                "most_senior_priority": senior,
                "most_senior_rights": sorted(item["right"] for item in decreed if item["priority"] == senior),
                "decree_year": year,
                "rights_of_that_year": sorted(item["right"] for item in of_that_year),
                "flow_of_rights_of_that_year_cfs": flow,
                "peak_diversion_requirement_cfs": requirement[peak],
                "peak_period": peak,
                "rights_of_that_year_cover_the_peak": flow >= requirement[peak],
            })
        elif any(item["kind"] == "not decreed" for item in rights.values()):
            raise SystemExit(f"{claimant}: its Utah rights carry no decree, which the rule does not rank")
        elif reservoirs:
            if len(reservoir_systems) != 1:
                raise SystemExit(f"{claimant}: reservoirs in more than one river system")
            row.update({"basis": "storage only", "river_system": reservoir_systems.pop(), "decree_year": None})
        else:
            row.update({
                "basis": "path rights not in the Utah layer",
                "river_system": f"own ({', '.join(sorted(rights)) or 'no right'})",
                "decree_year": None,
            })
        table.append(row)

    for variant, storage in VARIANTS.items():
        years = defaultdict(set)
        for row in table:
            if row["decree_year"] is not None:
                years[row["river_system"]].add(row["decree_year"])
        for row in table:
            ranked = sorted(years[row["river_system"]])
            if row["decree_year"] is not None:
                rank = ranked.index(row["decree_year"]) + 1
            elif row["basis"] == "storage only":
                rank = len(ranked) + 1 if storage == "last" else 1
            else:
                rank = 1
            row.setdefault("rank", {})[variant] = rank
    return table


def tiers_of(table: list[dict], variant: str) -> list[list[str]]:
    deepest = max(row["rank"][variant] for row in table)
    return [[row["claimant"] for row in table if row["rank"][variant] == rank] for rank in range(1, deepest + 1)]


def summary(solution, tiers: list[list[str]] | None = None) -> dict:
    guarantees = dict(solution.guarantees)
    tier_of = {claimant: index + 1 for index, tier in enumerate(tiers or []) for claimant in tier}
    return {
        "guarantees": guarantees,
        "sorted": sorted(guarantees.values()),
        "minimum_guarantee": min(guarantees.values()),
        "least_served": sorted(c for c, g in guarantees.items() if g <= min(guarantees.values()) + TOLERANCE),
        "levels": [
            {"theta": level.level, "blocked": list(level.blocked_claimants),
             **({"tier": tier_of[level.blocked_claimants[0]]} if tier_of else {})}
            for level in solution.leximin_levels
        ],
        "nominal_beneficial_delivery_af": solution.nominal_beneficial_delivery,
        "weighted_contingency_beneficial_delivery_af": solution.weighted_contingency_beneficial_delivery,
        "recourse_effort_by_scenario": dict(solution.recourse_by_scenario),
        "maximum_residual": max(solution.residuals.values(), default=0.0),
    }


def first_difference(left: list[float], right: list[float]) -> tuple[int | None, str | None]:
    for position, (a, b) in enumerate(zip(left, right), start=1):
        if abs(a - b) > TOLERANCE:
            return position, ("left" if a > b else "right")
    return None, None


def compare(reference: dict, tiered: dict, tiers: list[list[str]], same_solution: bool) -> dict:
    change = {c: tiered["guarantees"][c] - reference["guarantees"][c] for c in reference["guarantees"]}
    first = tiers[0]
    before = sorted(reference["guarantees"][c] for c in first)
    after = sorted(tiered["guarantees"][c] for c in first)
    position, higher = first_difference(after, before)
    sorted_position, sorted_higher = first_difference(tiered["sorted"], reference["sorted"])
    nominal = tiered["nominal_beneficial_delivery_af"] - reference["nominal_beneficial_delivery_af"]
    return {
        "tiers": tiers,
        "same_solution_as_cti_rlex": same_solution,
        "guarantee_change": change,
        "claimants_that_moved": {c: d for c, d in sorted(change.items(), key=lambda kv: kv[1]) if abs(d) > MOVED},
        "largest_change_of_a_claimant_that_did_not_move": max(
            (abs(d) for d in change.values() if abs(d) <= MOVED), default=0.0),
        "minimum_guarantee": {"CTI-RLex": reference["minimum_guarantee"], "PRIOR-LEX": tiered["minimum_guarantee"]},
        "minimum_not_above_cti_rlex": tiered["minimum_guarantee"] <= reference["minimum_guarantee"] + TOLERANCE,
        "first_tier_not_lexicographically_below_cti_rlex": higher != "right",
        "first_tier_first_difference": {"position": position, "higher": {"left": "PRIOR-LEX", "right": "CTI-RLex"}.get(higher)},
        "sorted_vectors_first_difference": {
            "position": sorted_position, "higher": {"left": "PRIOR-LEX", "right": "CTI-RLex"}.get(sorted_higher)},
        "nominal_delivery_change_af": nominal,
        "nominal_delivery_change_percent": 100.0 * nominal / reference["nominal_beneficial_delivery_af"],
        "weighted_contingency_delivery_change_af": (
            tiered["weighted_contingency_beneficial_delivery_af"]
            - reference["weighted_contingency_beneficial_delivery_af"]),
    }


def main() -> None:
    started = time.perf_counter()
    points, rights_record = decree_records()
    report = {"rule": RULE,
              "chosen": "requirements/decisions.md, 2026-10-12; expectations in requirements/hypotheses.md, H-2.1 and H-2.1b",
              "water_rights": rights_record, "moved_threshold": MOVED, "tolerance": TOLERANCE, "instances": {}}
    for instance, path in BENCHMARKS.items():
        began = time.perf_counter()
        payload = json.loads(path.read_text(encoding="utf-8"))
        model = load_cti_benchmark(path)
        table = tier_table(payload, model, points)
        cti = solve_cti_rlex(model)
        methods = {"CTI-RLex": summary(cti)}
        comparisons = {}
        for variant in VARIANTS:
            tiers = tiers_of(table, variant)
            solution = solve_cti_rlex(model, tiers=tiers)
            methods[variant] = summary(solution, tiers)
            comparisons[variant] = compare(methods["CTI-RLex"], methods[variant], tiers,
                                           solution.to_dict() == cti.to_dict())
        methods["UTIL-BR"] = summary(solve_utilitarian_fair(model))
        methods["PROP-BR"] = summary(solve_robust_proportional(model))
        report["instances"][instance] = {
            "benchmark_id": model.benchmark_id,
            "claimants": table,
            "methods": methods,
            "against_cti_rlex": comparisons,
            "seconds": round(time.perf_counter() - began, 1),
        }

        print(f"== {instance}")
        for row in table:
            if row["decree_year"] is not None:
                detail = (f"{row['most_senior_priority']} {','.join(row['most_senior_rights'])}; rights of "
                          f"{row['decree_year']} {row['flow_of_rights_of_that_year_cfs']:.1f} cfs vs peak requirement "
                          f"{row['peak_diversion_requirement_cfs']:.1f} cfs ({row['peak_period']})")
            else:
                detail = row["basis"]
            ranks = " / ".join(str(row["rank"][variant]) for variant in VARIANTS)
            print(f"   {row['claimant']:14s} {row['name'][:34]:34s} {row['river_system'][:26]:26s} tier {ranks:5s} {detail}")
        for method, block in methods.items():
            print(f"   {method:25s} sorted {[round(value, 4) for value in block['sorted']]}  "
                  f"nominal {block['nominal_beneficial_delivery_af']:8.1f}")
        for variant, item in comparisons.items():
            moved = {c: round(d, 4) for c, d in item["claimants_that_moved"].items()}
            print(f"   {variant}: tiers {[len(tier) for tier in item['tiers']]}; same solution as CTI-RLex "
                  f"{item['same_solution_as_cti_rlex']}; moved {moved or 'none'}; largest other change "
                  f"{item['largest_change_of_a_claimant_that_did_not_move']:.1e}; minimum "
                  f"{item['minimum_guarantee']['CTI-RLex']:.4f} -> {item['minimum_guarantee']['PRIOR-LEX']:.4f}; "
                  f"nominal {item['nominal_delivery_change_af']:+.1f} af; first tier not below CTI-RLex "
                  f"{item['first_tier_not_lexicographically_below_cti_rlex']}")
    report["seconds"] = round(time.perf_counter() - started, 1)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(REPO)} in {report['seconds']} s")


if __name__ == "__main__":
    main()
