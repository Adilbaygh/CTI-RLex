"""What the seven components of the county instance decide separately.

The ten-claimant instance is not one network in which ten claimants compete: it is seven
weakly connected components, the largest holding two claimants. A global sorted guarantee
vector therefore interleaves guarantees that were decided in different subsystems, and a
reader who reads position 4 as "the fourth-worst competitor" is reading competition into an
interleaving. The remedy is to report the components themselves.

Two things follow, and the second is the one worth stating in the paper.

First, per component: which claimants it holds, which sources and which shared envelope
serve them, and what CTI-RLex and the common-floor comparator give each of them. Where a
component holds one claimant the two rules must agree, because a single claimant is its own
floor; where it holds two they can differ, and that difference is the whole of the
lexicographic refinement the instance reports.

Second, how far the instance separates, which is less far than it looks. Claimants in
different components share no reach, no source and no group envelope, but they do share the
recourse budget: that constraint sums control deviations over the whole instance, and the
contingency plans deviate from one common first-stage plan, so a deviation spent in one
component is not available in another. The feasible set is therefore not a product and no
separability theorem applies.

What can be measured is what actually happens. Each component is solved alone, with the whole
budget to itself, and the merged guarantee vector is compared with the global one; on this
instance they agree exactly, which is a property of this instance rather than a theorem, and
it is consistent with the budget being slack for the fairness stage here. Delivery does not
agree: a component whose guarantee is identical under both rules can still deliver a
different volume in the global solve, and solving it alone makes that difference vanish.
That gap is where the shared budget shows, and reporting it is what keeps the separability
statement from being read as more than it is.

Run:  python scripts/component_analysis.py
Writes: results/component_analysis.json
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from timing_protocol import timed  # noqa: E402

from leximin.dag import (  # noqa: E402
    load_cti_benchmark,
    solve_cti_rlex,
    solve_robust_proportional,
    subset_claimants,
    weakly_connected_components,
)

BENCHMARK = REPO / "DATA" / "CacheValley_2025_Benchmark" / "benchmark.json"
OUTPUT = REPO / "results" / "component_analysis.json"
TOLERANCE = 1e-7


def node_components(model) -> dict[str, int]:
    """The component index of every node, by the same walk the claimant labels use."""

    adjacency: dict[str, set[str]] = collections.defaultdict(set)
    for edge in model.edges:
        adjacency[edge.tail].add(edge.head)
        adjacency[edge.head].add(edge.tail)
    seen: set[str] = set()
    index: dict[str, int] = {}
    counter = 0
    for node in list(adjacency):
        if node in seen:
            continue
        stack = [node]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            index[current] = counter
            stack.extend(adjacency[current] - seen)
        counter += 1
    return index


def scenario_delivery(model, solution, claimants: set[str]) -> float:
    """Nominal beneficial delivery to a set of claimants, from the terminals serving them.

    The delivery map is keyed by terminal identifier rather than by node, and a set of nodes
    matches none of those keys silently: every component would report zero and every
    difference between two rules would report zero as well. The partition check in main is
    what makes that failure loud instead.
    """

    terminals = {
        terminal.terminal_id
        for terminal in model.terminals
        if terminal.claimant_id in claimants
    }
    return sum(
        value
        for (scenario, _period, terminal), value in solution.beneficial_delivery.items()
        if scenario == model.nominal_scenario and terminal in terminals
    )


def main() -> None:
    model = load_cti_benchmark(BENCHMARK)
    labels = weakly_connected_components(model)
    node_index = node_components(model)

    names = {}
    payload_benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    for row in payload_benchmark["claimants"]:
        names[row["claimant_id"]] = row.get("claimant_name", row["claimant_id"])

    global_solution, global_timing = timed(lambda: solve_cti_rlex(model))
    proportional = solve_robust_proportional(model)

    members: dict[str, list[str]] = collections.defaultdict(list)
    for claimant, label in labels.items():
        members[label].append(claimant)

    # A component's index is the one its claimants' terminals fall in, so the sources and
    # envelopes of the same component are found by looking up their own nodes.
    label_of_index = {}
    for claimant, label in labels.items():
        for terminal in model.terminals:
            if terminal.claimant_id == claimant:
                label_of_index[node_index[terminal.node]] = label
                break

    sources_by_label: dict[str, list[str]] = collections.defaultdict(list)
    for source in model.sources:
        label = label_of_index.get(node_index.get(source.node, -1))
        if label:
            sources_by_label[label].append(source.source_id)

    groups_by_label: dict[str, list[str]] = collections.defaultdict(list)
    for group in model.source_groups:
        holders = {
            label_of_index.get(node_index.get(source.node, -1))
            for source in model.sources
            if source.source_id in {member for member, _beta in model.group_members[group]}
        }
        for label in sorted(holder for holder in holders if holder):
            groups_by_label[label].append(group)

    rows = []
    merged: list[float] = []
    for label in sorted(members, key=lambda item: int(item[1:])):
        claimants = sorted(members[label])
        isolated = subset_claimants(model, claimants)
        alone, timing = timed(lambda: solve_cti_rlex(isolated))
        alone_proportional = solve_robust_proportional(isolated)
        merged.extend(alone.guarantees[claimant] for claimant in claimants)
        rows.append({
            "component": label,
            "claimants": [names.get(claimant, claimant) for claimant in claimants],
            "claimant_ids": claimants,
            "sources": sorted(sources_by_label.get(label, [])),
            "shared_groups": sorted(groups_by_label.get(label, [])),
            "cti_rlex": {claimant: global_solution.guarantees[claimant] for claimant in claimants},
            "prop_br": {claimant: proportional.guarantees[claimant] for claimant in claimants},
            "solved_alone": {claimant: alone.guarantees[claimant] for claimant in claimants},
            "cti_rlex_nominal_delivery_af": scenario_delivery(
                model, global_solution, set(claimants)
            ),
            "prop_br_nominal_delivery_af": scenario_delivery(
                model, proportional, set(claimants)
            ),
            "cti_rlex_nominal_delivery_alone_af": alone.nominal_beneficial_delivery,
            "prop_br_nominal_delivery_alone_af": alone_proportional.nominal_beneficial_delivery,
            "max_lp_residual": max(alone.residuals.values(), default=0.0),
            **timing,
        })
        rows[-1]["delivery_cost_af"] = (
            rows[-1]["prop_br_nominal_delivery_af"] - rows[-1]["cti_rlex_nominal_delivery_af"]
        )
        rows[-1]["delivery_cost_alone_af"] = (
            rows[-1]["prop_br_nominal_delivery_alone_af"]
            - rows[-1]["cti_rlex_nominal_delivery_alone_af"]
        )
        rows[-1]["rules_agree_within_the_component"] = all(
            abs(rows[-1]["cti_rlex"][claimant] - rows[-1]["prop_br"][claimant]) <= TOLERANCE
            for claimant in claimants
        )
        rows[-1]["solving_alone_reproduces_the_global_guarantee"] = all(
            abs(rows[-1]["solved_alone"][claimant] - rows[-1]["cti_rlex"][claimant]) <= TOLERANCE
            for claimant in claimants
        )

    # The components partition the claimants, so their deliveries must add up to the whole.
    # A lookup that matched nothing would give every component zero and every comparison a
    # difference of zero, which is exactly what this catches.
    for label, solution in (("CTI-RLex", global_solution), ("PROP-BR", proportional)):
        key = "cti_rlex_nominal_delivery_af" if label == "CTI-RLex" else "prop_br_nominal_delivery_af"
        total = sum(row[key] for row in rows)
        if abs(total - solution.nominal_beneficial_delivery) > 0.05:
            raise SystemExit(
                f"{label}: the components deliver {total:.1f} af but the instance delivers "
                f"{solution.nominal_beneficial_delivery:.1f}; the per-component lookup is wrong"
            )

    global_sorted = sorted(global_solution.guarantees.values())
    merged_sorted = sorted(merged)
    separable = len(merged_sorted) == len(global_sorted) and all(
        abs(a - b) <= TOLERANCE for a, b in zip(merged_sorted, global_sorted)
    )

    report = {
        "benchmark_id": model.benchmark_id,
        "components": len(rows),
        "largest_component_claimants": max(len(row["claimant_ids"]) for row in rows),
        "components_where_the_rules_differ": [
            row["component"] for row in rows if not row["rules_agree_within_the_component"]
        ],
        "global_sorted_rho": global_sorted,
        "merged_sorted_rho": merged_sorted,
        "the_guarantee_vector_decomposes_by_component": separable,
        "the_delivery_decomposes_by_component": all(
            abs(row["delivery_cost_af"] - row["delivery_cost_alone_af"]) <= 0.05 for row in rows
        ),
        "the_recourse_budget_is_the_only_coupling": (
            "components share no reach, no source and no group envelope, but the recourse "
            "budget sums control deviations over the whole instance and the contingency "
            "plans deviate from one common first-stage plan"
        ),
        "total_delivery_cost_af": sum(row["delivery_cost_af"] for row in rows),
        "total_delivery_cost_alone_af": sum(row["delivery_cost_alone_af"] for row in rows),
        **{f"global_{key}": value for key, value in global_timing.items()},
        "rows": rows,
    }
    if not separable:
        raise SystemExit(
            "solving the components separately did not reproduce the global guarantee vector; "
            "the components are not independent and the claim must not be made"
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"{report['components']} components, largest holds "
          f"{report['largest_component_claimants']} claimants")
    for row in rows:
        agree = "same" if row["rules_agree_within_the_component"] else "DIFFER"
        print(f"  {row['component']}  {len(row['claimant_ids'])} claimant(s), "
              f"{len(row['sources'])} source(s)  rules {agree}  "
              f"delivery cost {row['delivery_cost_af']:>8.1f} af "
              f"({row['delivery_cost_alone_af']:>6.1f} af solved alone)")
    print(f"the guarantee vector decomposes by component: {separable}")
    print(f"the delivery decomposes by component: "
          f"{report['the_delivery_decomposes_by_component']}")
    print(f"total delivery cost of the lexicographic refinement: "
          f"{report['total_delivery_cost_af']:.1f} af")
    print(f"wrote {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
