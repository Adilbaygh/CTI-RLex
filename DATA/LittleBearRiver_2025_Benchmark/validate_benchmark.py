"""Validate the canonical Little Bear River CTI-RLex benchmark.

The validator uses only the Python standard library so the published benchmark can be
checked without GIS or optimization software.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
BENCHMARK_PATH = ROOT / "benchmark.json"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _is_dag(nodes: set[str], edges: list[dict[str, Any]]) -> bool:
    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree = {node: 0 for node in nodes}
    for edge in edges:
        outgoing[edge["from_node"]].append(edge["to_node"])
        indegree[edge["to_node"]] += 1
    queue = deque(sorted(node for node, degree in indegree.items() if degree == 0))
    seen = 0
    while queue:
        node = queue.popleft()
        seen += 1
        for nxt in outgoing[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    return seen == len(nodes)


def _reachable(start: str, outgoing: dict[str, list[str]]) -> set[str]:
    seen = {start}
    stack = [start]
    while stack:
        node = stack.pop()
        for nxt in outgoing.get(node, []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _weak_component_count(nodes: set[str], edges: list[dict[str, Any]]) -> int:
    adjacent: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adjacent[edge["from_node"]].add(edge["to_node"])
        adjacent[edge["to_node"]].add(edge["from_node"])
    remaining = set(nodes)
    count = 0
    while remaining:
        count += 1
        start = min(remaining)
        reached = {start}
        stack = [start]
        while stack:
            node = stack.pop()
            for nxt in adjacent.get(node, set()):
                if nxt not in reached:
                    reached.add(nxt)
                    stack.append(nxt)
        remaining -= reached
    return count


def _duplicate_free_keys(rows: list[dict[str, Any]], fields: tuple[str, ...], label: str) -> set[tuple[Any, ...]]:
    keys = {tuple(row[field] for field in fields) for row in rows}
    _require(len(keys) == len(rows), f"{label} contains duplicate keys.")
    return keys


def validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sets = payload["sets"]
    nodes = payload["nodes"]
    edges = payload["edges"]
    sources = payload["sources"]
    source_groups = payload["source_groups"]
    source_group_members = payload["source_group_members"]
    claimants = payload["claimants"]
    claimant_terminals = payload["claimant_terminals"]
    terminal_parameters = payload["terminal_parameters"]
    demands = payload["demands"]
    source_limits = payload["source_limits"]
    seasonal_limits = payload["source_seasonal_limits"]
    shared_limits = payload["shared_source_limits"]
    edge_parameters = payload["edge_parameters"]
    control_assets = payload["control_assets"]
    scenarios = payload["scenarios"]
    periods = payload["periods"]

    node_ids = {row["node_id"] for row in nodes}
    edge_ids = {row["edge_id"] for row in edges}
    source_ids = {row["source_id"] for row in sources}
    group_ids = {row["group_id"] for row in source_groups}
    claimant_ids = {row["claimant_id"] for row in claimants}
    scenario_ids = {row["scenario_id"] for row in scenarios}
    period_ids = {row["period_id"] for row in periods}

    for values, rows, label in (
        (node_ids, nodes, "node_id"),
        (edge_ids, edges, "edge_id"),
        (source_ids, sources, "source_id"),
        (group_ids, source_groups, "group_id"),
        (claimant_ids, claimants, "claimant_id"),
        (scenario_ids, scenarios, "scenario_id"),
        (period_ids, periods, "period_id"),
    ):
        _require(len(values) == len(rows), f"Duplicate {label}.")

    for name, expected in (
        ("nodes", node_ids),
        ("edges", edge_ids),
        ("sources", source_ids),
        ("source_groups", group_ids),
        ("claimants", claimant_ids),
        ("scenarios", scenario_ids),
        ("periods", period_ids),
    ):
        _require(set(sets[name]) == expected, f"sets.{name} disagrees with its table.")

    edge_by_id = {row["edge_id"]: row for row in edges}
    for edge in edges:
        _require(edge["from_node"] in node_ids, f"Unknown from_node on {edge['edge_id']}.")
        _require(edge["to_node"] in node_ids, f"Unknown to_node on {edge['edge_id']}.")
        _require(edge["from_node"] != edge["to_node"], f"Self-loop on {edge['edge_id']}.")
        _require(float(edge["capacity_cfs_base"]) > 0, f"Nonpositive capacity on {edge['edge_id']}.")
        _require(0 < float(edge["efficiency_base"]) <= 1, f"Invalid efficiency on {edge['edge_id']}.")
    _require(_is_dag(node_ids, edges), "The benchmark graph is not a DAG.")

    _duplicate_free_keys(claimant_terminals, ("terminal_id",), "claimant_terminals")
    terminal_records = {
        (row["terminal_id"], row["claimant_id"], row["terminal_node"])
        for row in claimant_terminals
    }
    terminal_nodes = {terminal for _, _, terminal in terminal_records}
    for _, claimant_id, terminal in terminal_records:
        _require(claimant_id in claimant_ids, "Unknown claimant in terminal map.")
        _require(terminal in node_ids, "Unknown terminal node.")
    _require({item[1] for item in terminal_records} == claimant_ids, "Every claimant needs a terminal.")

    outgoing: dict[str, list[str]] = defaultdict(list)
    outdegree: dict[str, int] = defaultdict(int)
    for edge in edges:
        outgoing[edge["from_node"]].append(edge["to_node"])
        outdegree[edge["from_node"]] += 1
    for terminal in terminal_nodes:
        _require(outdegree[terminal] == 0, f"Terminal {terminal} is not a leaf.")
    source_by_id = {row["source_id"]: row for row in sources}
    for source in sources:
        _require(source["node_id"] in node_ids, f"Unknown source node {source['node_id']}.")
        _require(_reachable(source["node_id"], outgoing) & terminal_nodes, f"Source {source['source_id']} reaches no terminal.")
    for terminal in terminal_nodes:
        _require(
            any(terminal in _reachable(source["node_id"], outgoing) for source in sources),
            f"Terminal {terminal} is unreachable.",
        )

    expected_demand = {(period, claimant) for period in period_ids for claimant in claimant_ids}
    actual_demand = _duplicate_free_keys(demands, ("period_id", "claimant_id"), "demands")
    _require(actual_demand == expected_demand, "Demand table is incomplete.")
    _require(all(float(row["demand_af"]) >= 0 for row in demands), "Negative demand.")
    demand_totals: dict[str, float] = defaultdict(float)
    for row in demands:
        demand_totals[row["claimant_id"]] += float(row["demand_af"])
    _require(all(value > 0 for value in demand_totals.values()), "Every claimant needs positive demand.")

    expected_terminal_parameters = {
        (period, claimant, terminal_id, terminal)
        for period in period_ids
        for terminal_id, claimant, terminal in terminal_records
    }
    actual_terminal_parameters = _duplicate_free_keys(
        terminal_parameters,
        ("period_id", "claimant_id", "terminal_id", "terminal_node"),
        "terminal_parameters",
    )
    _require(actual_terminal_parameters == expected_terminal_parameters, "Terminal parameters are incomplete.")
    _require(
        all(0 < float(row["application_efficiency"]) <= 1 for row in terminal_parameters),
        "Application efficiency outside (0, 1].",
    )

    expected_q = {
        (scenario, period, source)
        for scenario in scenario_ids
        for period in period_ids
        for source in source_ids
    }
    actual_q = _duplicate_free_keys(
        source_limits, ("scenario_id", "period_id", "source_id"), "source_limits"
    )
    _require(actual_q == expected_q, "Source-limit table is incomplete.")
    _require(all(float(row["q_af"]) >= 0 for row in source_limits), "Negative source limit.")

    expected_v = {(scenario, source) for scenario in scenario_ids for source in source_ids}
    actual_v = _duplicate_free_keys(
        seasonal_limits, ("scenario_id", "source_id"), "source_seasonal_limits"
    )
    _require(actual_v == expected_v, "Seasonal source-limit table is incomplete.")
    _require(all(float(row["v_af"]) >= 0 for row in seasonal_limits), "Negative seasonal source cap.")
    q_lookup = {(row["scenario_id"], row["period_id"], row["source_id"]): float(row["q_af"]) for row in source_limits}
    for row in seasonal_limits:
        summed_q = sum(q_lookup[(row["scenario_id"], period, row["source_id"])] for period in period_ids)
        _require(float(row["v_af"]) <= summed_q + 1e-5, "Seasonal source cap exceeds summed period limits.")

    membership_keys = _duplicate_free_keys(
        source_group_members, ("group_id", "source_id"), "source_group_members"
    )
    for group, source in membership_keys:
        _require(group in group_ids and source in source_ids, "Invalid source-group membership.")
    _require({source for _, source in membership_keys} == source_ids, "Every source must belong to a group.")
    _require(all(float(row["beta"]) > 0 for row in source_group_members), "Nonpositive group coefficient.")
    expected_w = {
        (scenario, period, group)
        for scenario in scenario_ids
        for period in period_ids
        for group in group_ids
    }
    actual_w = _duplicate_free_keys(
        shared_limits, ("scenario_id", "period_id", "group_id"), "shared_source_limits"
    )
    _require(actual_w == expected_w, "Shared source-limit table is incomplete.")
    _require(all(float(row["w_af"]) >= 0 for row in shared_limits), "Negative shared envelope.")

    expected_edge = {
        (scenario, period, edge)
        for scenario in scenario_ids
        for period in period_ids
        for edge in edge_ids
    }
    actual_edge = _duplicate_free_keys(
        edge_parameters, ("scenario_id", "period_id", "edge_id"), "edge_parameters"
    )
    _require(actual_edge == expected_edge, "Edge-parameter table is incomplete.")
    for row in edge_parameters:
        _require(float(row["capacity_af"]) >= 0, "Negative edge capacity.")
        _require(0 < float(row["efficiency"]) <= 1, "Edge efficiency outside (0, 1].")

    control_keys = _duplicate_free_keys(control_assets, ("control_asset_id",), "control_assets")
    _require(control_keys, "At least one control asset is required.")
    for row in control_assets:
        resource_type = row["resource_type"]
        resource_id = row["resource_id"]
        if resource_type == "source":
            _require(resource_id in source_ids, "Control references an unknown source.")
        elif resource_type == "edge":
            _require(resource_id in edge_ids, "Control references an unknown edge.")
            _require(edge_by_id[resource_id]["edge_role"] == "physical", "Logical connectors cannot be controls.")
        else:
            raise ValueError(f"Unknown control resource type {resource_type!r}.")
        _require(float(row["normalization_scale_af"]) > 0, "Nonpositive control normalization scale.")
        _require(float(row["effort_coefficient"]) > 0, "Nonpositive effort coefficient.")

    scenario_by_id = {row["scenario_id"]: row for row in scenarios}
    _require("nominal" in scenario_by_id, "Exactly one nominal scenario is required.")
    _require(float(scenario_by_id["nominal"]["recourse_budget"]) == 0, "Nominal recourse budget must be zero.")
    _require(float(scenario_by_id["nominal"]["probability_weight"]) == 0, "Nominal contingency weight must be zero.")
    contingency_weight = sum(
        float(row["probability_weight"]) for row in scenarios if row["scenario_id"] != "nominal"
    )
    _require(abs(contingency_weight - 1.0) <= 1e-9, "Contingency weights must sum to one.")
    _require(any(float(row["q_af"]) == 0 for row in source_limits), "No disabled-source contingency.")
    _require(
        any(0 < float(row["capacity_factor"]) < 1 for row in edge_parameters),
        "No partial edge-restriction contingency.",
    )

    for scenario in scenario_ids:
        for period in period_ids:
            active_outgoing: dict[str, list[str]] = defaultdict(list)
            for row in edge_parameters:
                if row["scenario_id"] == scenario and row["period_id"] == period and float(row["capacity_af"]) > 0:
                    edge = edge_by_id[row["edge_id"]]
                    active_outgoing[edge["from_node"]].append(edge["to_node"])
            active_sources = [
                source_by_id[row["source_id"]]["node_id"]
                for row in source_limits
                if row["scenario_id"] == scenario and row["period_id"] == period and float(row["q_af"]) > 0
            ]
            for terminal in terminal_nodes:
                _require(
                    any(terminal in _reachable(source, active_outgoing) for source in active_sources),
                    f"Terminal {terminal} is disconnected in {scenario}/{period}.",
                )

    source_roles = payload["source_roles"]
    _duplicate_free_keys(source_roles, ("source_id", "claimant_id"), "source_roles")
    terminal_by_claimant: dict[str, set[str]] = defaultdict(set)
    for _, claimant, terminal in terminal_records:
        terminal_by_claimant[claimant].add(terminal)
    for row in source_roles:
        _require(row["source_id"] in source_ids and row["claimant_id"] in claimant_ids, "Invalid source role.")
        reached = _reachable(source_by_id[row["source_id"]]["node_id"], outgoing)
        _require(reached & terminal_by_claimant[row["claimant_id"]], "Source role contradicts graph reachability.")

    parcel_count = len(payload["parcels"])
    _require(parcel_count > 0, "No WRLU polygons were assigned.")
    parcel_ids = {row["wrlu_objectid"] for row in payload["parcels"]}
    _require(parcel_count == len(parcel_ids), "A WRLU polygon was assigned more than once.")
    _require({row["edge_id"] for row in payload["path_edges"]} <= edge_ids, "Path references an unknown edge.")

    return {
        "status": "pass",
        "benchmark_id": payload["benchmark_id"],
        "schema_version": payload["schema_version"],
        "graph_is_dag": True,
        "weakly_connected_components": _weak_component_count(node_ids, edges),
        "every_terminal_reachable_in_every_scenario": True,
        "counts": {
            "nodes": len(nodes),
            "edges": len(edges),
            "physical_edges": sum(row["edge_role"] == "physical" for row in edges),
            "derived_connectors": sum(row["edge_role"] == "derived_connector" for row in edges),
            "sources": len(sources),
            "source_groups": len(source_groups),
            "claimants": len(claimants),
            "terminals": len(terminal_nodes),
            "control_assets": len(control_assets),
            "periods": len(periods),
            "scenarios": len(scenarios),
            "wrlu_polygons": parcel_count,
            "demand_rows": len(demands),
            "source_limit_rows": len(source_limits),
            "edge_parameter_rows": len(edge_parameters),
            "sensitivity_cases": len(payload["sensitivity_cases"]),
        },
        "seasonal_totals": {
            "assigned_acres": round(sum(float(row["acres"]) for row in payload["parcels"]), 6),
            "irrigated_demand_acres": round(sum(float(row["irrigated_demand_acres"]) for row in claimants), 6),
            "excluded_nonirrigated_acres": round(sum(float(row["excluded_nonirrigated_acres"]) for row in claimants), 6),
            "net_demand_af": round(sum(float(row["demand_af"]) for row in demands), 6),
        },
        "scientific_scope": payload["scientific_scope"],
    }


def main() -> None:
    with BENCHMARK_PATH.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    report = validate_payload(payload)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
