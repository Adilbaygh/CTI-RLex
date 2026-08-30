"""Does the reported allocation depend on the order of the acyclicity repair?

The county path table has gaps, and the build bridges them with logical connectors. Two
bridges can together close a loop, so a greedy repair accepts a candidate only while the
graph stays acyclic -- and which candidate is rejected depends on the order in which the
candidates are considered. The published build orders them by how many candidate paths
depend on each bridge, so a rejection breaks as few paths as possible, with node
identifiers breaking ties. That is deterministic, which is what reproducibility needs, but
it is one arbitrary choice out of 41! of them, and a result that held only for that choice
would be a property of the ordering rather than of the method.

This script answers the question the released package could not answer about itself. The
repair is a pure graph computation over the physical adjacency and the candidate bridges,
so it does not have to be rebuilt from the raw Utah layers once per order: one build dumps
its inputs, and every order is then replayed against the released
``acyclic_connector_selection`` in milliseconds. Orders that reach the same accepted set
reach the same benchmark by construction, so only the *distinct* outcomes are rebuilt and
solved.

Three checks make the replay trustworthy rather than merely fast:

* the published order must reproduce the released decision record -- all 41 positions,
  decisions and reasons -- so a drift between the replay and the build cannot pass;
* the replayed path and claimant counts under the published order must equal the released
  ones, 31 and 10;
* every rebuild goes to a scratch directory, so the released benchmark cannot be touched.

Orders tested: the published rule, its opposite tie-break, its adversarial inverse, node
order in both directions, and a sample of uniformly random permutations. The random sample
is the one that tests the claim; the hand-chosen rules only test other hand-chosen rules.

Run (needs LEXIMIN_DATASETS, one build, then the sweep):
    python scripts/connector_order_experiment.py --build --seeds 200
    python scripts/connector_order_experiment.py --rebuild        # only distinct outcomes
Writes: results/repair_inputs_cache_valley.json, results/connector_order_sensitivity.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = REPO / "DATA" / "LittleBearRiver_2025_Benchmark"
PUBLISHED = REPO / "DATA" / "CacheValley_2025_Benchmark"
RESULTS = REPO / "results"
DUMP = RESULTS / "repair_inputs_cache_valley.json"
OUTPUT = RESULTS / "connector_order_sensitivity.json"

PUBLISHED_ORDER = "dependents"
DETERMINISTIC_ORDERS = [
    "dependents",
    "dependents_desc_nodes",
    "fewest_dependents",
    "nodes",
    "nodes_desc",
]

sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))


# ------------------------------------------------------------------ the dump


def build_dump(target: Path) -> None:
    """Run the county build once, only far enough to write the repair's inputs.

    Pass one stops with a non-zero status as soon as the repair reports service areas
    without a route, which is the documented behaviour and happens after the dump is
    written. The build is sent to a scratch directory and the released selection cache is
    copied in, so the discovery pass is not repeated and nothing published is written.
    """

    if "LEXIMIN_DATASETS" not in os.environ:
        raise SystemExit("set LEXIMIN_DATASETS to the open-data root first")

    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PUBLISHED / "selection.json", target / "selection.json")
    (target / "unrouted_claimants.json").unlink(missing_ok=True)

    DUMP.parent.mkdir(parents=True, exist_ok=True)
    environment = {
        **os.environ,
        "LEXIMIN_COUNTY_TARGET": str(target),
        "LEXIMIN_REPAIR_DUMP": str(DUMP),
        "LEXIMIN_CONNECTOR_ORDER": PUBLISHED_ORDER,
    }
    completed = subprocess.run(
        [sys.executable, "-B", str(BENCHMARK_DIR / "generate_cache_valley_benchmark.py")],
        cwd=BENCHMARK_DIR,
        capture_output=True,
        text=True,
        env=environment,
    )
    sys.stdout.write(completed.stdout)
    if not DUMP.exists():
        sys.stderr.write(completed.stderr)
        raise SystemExit("the build wrote no repair dump; is the generator patched?")
    print(f"wrote {DUMP.relative_to(REPO)}")


# ------------------------------------------------------------------ the replay


def replay(dump: dict, order: str) -> dict[str, Any]:
    """Run the released repair over the dumped inputs under one candidate order."""

    import generate_benchmark as gb

    physical_edges = {
        f"e{index}": {"from_node": pair[0], "to_node": pair[1]}
        for index, pair in enumerate(dump["physical_adjacency"])
    }
    # Only the length of each candidate's dependant list is read by the ordering rule, and
    # only the pair itself by the repair, so the capacities are irrelevant here.
    candidate_pairs = {
        (row["tail_raw"], row["head_raw"]): [0.0] * row["dependent_candidate_paths"]
        for row in dump["candidates"]
    }

    previous = gb.CONNECTOR_ORDER
    gb.CONNECTOR_ORDER = order
    try:
        accepted, rejected, decisions = gb.acyclic_connector_selection(
            physical_edges, candidate_pairs
        )
    finally:
        gb.CONNECTOR_ORDER = previous

    rejected_ids = {row["connector"] for row in rejected}
    retained, dropped = [], []
    for plan in dump["path_plans"]:
        blocking = sorted(set(plan["connectors"]) & rejected_ids)
        if blocking:
            dropped.append({**plan, "blocking_connectors": "|".join(blocking)})
        else:
            retained.append(plan)

    return {
        "order": order,
        "accepted_connectors": sorted(f"c_{tail}_{head}" for tail, head in accepted),
        "rejected_connectors": sorted(rejected_ids),
        "retained_paths": sorted(plan["path_id"] for plan in retained),
        "dropped_paths": sorted(plan["path_id"] for plan in dropped),
        "served_terminals": sorted({plan["terminal_raw"] for plan in retained}),
        "decisions": decisions,
    }


def claimant_view(dump: dict, outcome: dict, selection: dict) -> dict[str, Any]:
    """Which service areas the repair leaves routed, under one outcome."""

    qualifying = sorted({plan["terminal_raw"] for plan in dump["path_plans"]})
    served = set(outcome["served_terminals"])

    def named(terminal: str) -> str:
        company = selection["terminal_to_company"][terminal]
        specification = selection["companies"][company]
        return f"{specification['claimant_id']} ({specification['name']})"

    return {
        "qualifying_claimants": len(qualifying),
        "routed_claimants": sorted(named(t) for t in qualifying if t in served),
        "excluded_claimants": sorted(named(t) for t in qualifying if t not in served),
    }


# ------------------------------------------------------------------ rebuild and solve


def rebuild_and_solve(order: str, target: Path) -> dict[str, Any]:
    """Rebuild the county instance under one order and solve it, in a scratch directory.

    Every comparator the paper reports on the county instance is re-solved here, not only
    CTI-RLex. Different repair orders produce different claimant sets, so their guarantee
    vectors are not comparable term by term -- but the question the review actually asks is
    whether the *method's* result depends on the order, and that question is answered by
    whether CTI-RLex still stands in the same relation to the comparators on every graph
    the repair can produce.
    """

    from dataclasses import replace as dataclass_replace

    from timing_protocol import timed

    from leximin.dag import (
        load_cti_benchmark,
        lp_dimensions,
        solve_cti_rlex,
        solve_robust_proportional,
        solve_utilitarian_fair,
        subset_scenarios,
    )

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PUBLISHED / "selection.json", target / "selection.json")

    completed = subprocess.run(
        [
            sys.executable, "-B", str(REPO / "scripts" / "rebuild_cache_valley.py"),
            "--python", sys.executable,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "LEXIMIN_COUNTY_TARGET": str(target),
             "LEXIMIN_CONNECTOR_ORDER": order},
    )
    benchmark = target / "benchmark.json"
    if completed.returncode != 0 or not benchmark.exists():
        sys.stderr.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        raise SystemExit(f"the rebuild under order {order!r} failed")

    model = load_cti_benchmark(benchmark)
    solution, timing = timed(lambda: solve_cti_rlex(model))
    totals = {
        scenario: sum(
            value
            for (item_scenario, _period, _terminal), value
            in solution.beneficial_delivery.items()
            if item_scenario == scenario
        )
        for scenario in model.scenarios
    }

    # The comparator set of the paper, on this instance: the fairness-optimistic
    # utilitarian best response, the robust proportional rule, the same model with every
    # recourse budget set to zero, and the model with the contingencies removed. The last
    # two are what the value of recourse and the price of robustness are measured against.
    utilitarian = solve_utilitarian_fair(model)
    proportional = solve_robust_proportional(model)
    rigid = solve_cti_rlex(
        dataclass_replace(
            model,
            recourse_budget={scenario: 0.0 for scenario in model.scenarios},
        )
    )
    nominal_only = solve_cti_rlex(subset_scenarios(model, (model.nominal_scenario,)))

    minimum = min(solution.guarantees.values())
    rigid_min = min(rigid.guarantees.values())
    delivery = solution.nominal_beneficial_delivery
    nominal_only_af = nominal_only.nominal_beneficial_delivery
    return {
        "benchmark_id": model.benchmark_id,
        "claimants": len(model.claimants),
        "nodes": len(model.nodes),
        "edges": len(model.edges),
        "sources": len(model.sources),
        "source_groups": len(model.source_groups),
        "controls": len(model.controls),
        **lp_dimensions(model),
        "sorted_rho": sorted(solution.guarantees.values()),
        "guarantees": dict(solution.guarantees),
        "min_guarantee": minimum,
        "nominal_delivery_af": delivery,
        "worst_scenario_delivery_af": min(totals.values()),
        "utilitarian_min_guarantee": min(utilitarian.guarantees.values()),
        "utilitarian_nominal_af": utilitarian.nominal_beneficial_delivery,
        "proportional_min_guarantee": min(proportional.guarantees.values()),
        "proportional_nominal_af": proportional.nominal_beneficial_delivery,
        "rigid_min_guarantee": rigid_min,
        "nominal_only_delivery_af": nominal_only_af,
        "price_of_fairness_pct": 100.0
        * (utilitarian.nominal_beneficial_delivery - delivery)
        / utilitarian.nominal_beneficial_delivery,
        "value_of_recourse_pct": (
            100.0 * (minimum - rigid_min) / rigid_min if rigid_min > 0 else None
        ),
        "price_of_robustness_pct": 100.0 * (nominal_only_af - delivery) / nominal_only_af,
        "beats_utilitarian_on_the_minimum": minimum > min(utilitarian.guarantees.values()),
        "beats_rigid_on_the_minimum": minimum > rigid_min,
        "max_lp_residual": max(solution.residuals.values(), default=0.0),
        **timing,
    }


# ------------------------------------------------------------------ driver


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true",
                        help="run one county build first to write the repair inputs")
    parser.add_argument("--seeds", type=int, default=200,
                        help="uniformly random candidate orders to test (default 200)")
    parser.add_argument("--rebuild", action="store_true",
                        help="rebuild and solve one instance per distinct outcome")
    parser.add_argument("--max-rebuilds", type=int, default=6,
                        help="stop after this many rebuilds (default 6)")
    arguments = parser.parse_args()

    scratch = Path(tempfile.gettempdir()) / "cti_rlex_connector_order"
    if arguments.build:
        build_dump(scratch / "dump_build")
    if not DUMP.exists():
        raise SystemExit(f"no repair dump at {DUMP}; run once with --build")

    sys.path.insert(0, str(BENCHMARK_DIR))
    dump = json.loads(DUMP.read_text(encoding="utf-8"))
    selection = json.loads((PUBLISHED / "selection.json").read_text(encoding="utf-8"))
    published_summary = json.loads(
        (PUBLISHED / "discovery_summary.json").read_text(encoding="utf-8")
    )
    reduction = published_summary["acyclic_reduction"]

    orders = list(DETERMINISTIC_ORDERS) + [f"seed:{n}" for n in range(1, arguments.seeds + 1)]
    print(f"candidates: {len(dump['candidates'])}   paths before repair: "
          f"{len(dump['path_plans'])}   orders to test: {len(orders)}")

    outcomes: dict[tuple, dict[str, Any]] = {}
    control: dict[str, Any] | None = None
    for order in orders:
        result = replay(dump, order)
        if order == PUBLISHED_ORDER:
            control = result
        signature = (
            tuple(result["accepted_connectors"]),
            tuple(result["retained_paths"]),
            tuple(result["served_terminals"]),
        )
        record = outcomes.setdefault(
            signature,
            {**{key: value for key, value in result.items() if key != "decisions"},
             "orders": [], "first_order": order},
        )
        record["orders"].append(order)

    assert control is not None, "the published order was not replayed"

    # The replay is only evidence if it reproduces the build it replaces.
    published_decisions = [
        {key: row[key] for key in ("position", "connector", "decision", "reason")}
        for row in reduction["connector_decisions"]
    ]
    replayed_decisions = [
        {key: row[key] for key in ("position", "connector", "decision", "reason")}
        for row in control["decisions"]
    ]
    control_ok = replayed_decisions == published_decisions
    control_paths = len(control["retained_paths"]) == published_summary["path_count"]
    control_claimants = (
        len(claimant_view(dump, control, selection)["routed_claimants"])
        == len(published_summary["claimants"])
    )
    print(f"control: decision record reproduced={control_ok}  "
          f"paths={len(control['retained_paths'])}  "
          f"rejected={len(control['rejected_connectors'])}")
    if not (control_ok and control_paths and control_claimants):
        raise SystemExit(
            "the replay does not reproduce the published reduction under the published "
            "order; nothing below it can be trusted"
        )

    published_signature = (
        tuple(control["accepted_connectors"]),
        tuple(control["retained_paths"]),
        tuple(control["served_terminals"]),
    )

    rows: list[dict[str, Any]] = []
    for index, (signature, record) in enumerate(
        sorted(outcomes.items(), key=lambda item: -len(item[1]["orders"])), start=1
    ):
        view = claimant_view(dump, record, selection)
        rows.append(
            {
                "outcome": index,
                "orders_reaching_it": len(record["orders"]),
                "example_orders": record["orders"][:6],
                "same_graph_as_published": signature == published_signature,
                "accepted_connectors": len(record["accepted_connectors"]),
                "rejected_connectors": len(record["rejected_connectors"]),
                "paths_retained": len(record["retained_paths"]),
                "paths_dropped": len(record["dropped_paths"]),
                **view,
                "retained_path_ids": record["retained_paths"],
                "accepted_connector_ids": record["accepted_connectors"],
            }
        )

    print(f"distinct repaired graphs: {len(rows)}")
    for row in rows:
        print(f"  outcome {row['outcome']}: {row['orders_reaching_it']:>4} orders, "
              f"{row['paths_retained']:>2} paths, {len(row['routed_claimants']):>2} claimants, "
              f"same graph as published: {row['same_graph_as_published']}")

    if arguments.rebuild:
        for row in rows[: arguments.max_rebuilds]:
            order = row["example_orders"][0]
            print(f"rebuilding outcome {row['outcome']} under order {order!r} ...", flush=True)
            row["solution"] = rebuild_and_solve(order, scratch / f"outcome_{row['outcome']}")
            item = row["solution"]
            print(f"  {item['claimants']} claimants, {item['variables']} variables")
            print(f"  RLex min {item['min_guarantee']:.6f}   "
                  f"UTIL-BR min {item['utilitarian_min_guarantee']:.6f}   "
                  f"rigid min {item['rigid_min_guarantee']:.6f}")
            print(f"  nominal {item['nominal_delivery_af']:.1f} af   "
                  f"PoF {item['price_of_fairness_pct']:.2f}%   "
                  f"VoR {item['value_of_recourse_pct'] if item['value_of_recourse_pct'] is None else round(item['value_of_recourse_pct'], 2)}%   "
                  f"PoR {item['price_of_robustness_pct']:.2f}%")

    payload = {
        "question": (
            "whether the reported CTI-RLex allocation depends on the order in which the "
            "acyclicity repair considers candidate connectors"
        ),
        "instance": "cache_valley_2025_multiclaimant_v3",
        "published_order": PUBLISHED_ORDER,
        "connector_candidates": len(dump["candidates"]),
        "paths_before_repair": len(dump["path_plans"]),
        "orders_tested": len(orders),
        "deterministic_orders": DETERMINISTIC_ORDERS,
        "random_permutations": arguments.seeds,
        "control": {
            "published_decision_record_reproduced": control_ok,
            "paths_retained": len(control["retained_paths"]),
            "connectors_rejected": len(control["rejected_connectors"]),
        },
        "distinct_repaired_graphs": len(rows),
        "orders_reaching_the_published_graph": sum(
            row["orders_reaching_it"] for row in rows if row["same_graph_as_published"]
        ),
        "outcomes": rows,
    }

    solved = [row for row in rows if "solution" in row]
    if solved:
        # The instance is a function of the repair order; the question is whether the
        # method's standing against its comparators is too. Only a statement that holds on
        # every graph the repair can produce may be made without qualification.
        payload["method_conclusion"] = {
            "graphs_solved": len(solved),
            "claimant_counts": sorted({row["solution"]["claimants"] for row in solved}),
            "rlex_beats_utilitarian_on_every_graph": all(
                row["solution"]["beats_utilitarian_on_the_minimum"] for row in solved
            ),
            "rlex_beats_rigid_on_every_graph": all(
                row["solution"]["beats_rigid_on_the_minimum"] for row in solved
            ),
            "price_of_fairness_range_pct": [
                min(row["solution"]["price_of_fairness_pct"] for row in solved),
                max(row["solution"]["price_of_fairness_pct"] for row in solved),
            ],
            "value_of_recourse_range_pct": [
                min(row["solution"]["value_of_recourse_pct"] for row in solved),
                max(row["solution"]["value_of_recourse_pct"] for row in solved),
            ],
            "price_of_robustness_range_pct": [
                min(row["solution"]["price_of_robustness_pct"] for row in solved),
                max(row["solution"]["price_of_robustness_pct"] for row in solved),
            ],
            "max_lp_residual": max(row["solution"]["max_lp_residual"] for row in solved),
        }
        print()
        print("method conclusion across every repaired graph:")
        conclusion = payload["method_conclusion"]
        print(f"  claimant counts        : {conclusion['claimant_counts']}")
        print(f"  RLex > UTIL-BR minimum : {conclusion['rlex_beats_utilitarian_on_every_graph']}")
        print(f"  RLex > rigid minimum   : {conclusion['rlex_beats_rigid_on_every_graph']}")
        for key in ("price_of_fairness", "value_of_recourse", "price_of_robustness"):
            low, high = conclusion[f"{key}_range_pct"]
            print(f"  {key:<22}: {low:.2f}% .. {high:.2f}%")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
