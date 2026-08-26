from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import networkx as nx

from .domain import ClaimantTerminal, ControlAsset, CTIBenchmark, DAGEdge, DAGSource


def parse_cti_payload(raw: Mapping[str, Any]) -> CTIBenchmark:
    periods = tuple(str(row["period_id"]) for row in raw["periods"])
    scenarios = tuple(str(row["scenario_id"]) for row in raw["scenarios"])
    claimants = tuple(str(row["claimant_id"]) for row in raw["claimants"])
    edges = tuple(
        DAGEdge(
            edge_id=str(row["edge_id"]),
            tail=str(row["from_node"]),
            head=str(row["to_node"]),
            role=str(row.get("edge_role", "physical")),
        )
        for row in raw["edges"]
    )
    sources = tuple(
        DAGSource(
            source_id=str(row["source_id"]),
            node=str(row["node_id"]),
            source_class=str(row.get("source_class", "unspecified")),
        )
        for row in raw["sources"]
    )
    terminals = tuple(
        ClaimantTerminal(
            terminal_id=str(row.get("terminal_id", f"terminal_{index}")),
            claimant_id=str(row["claimant_id"]),
            node=str(row["terminal_node"]),
        )
        for index, row in enumerate(raw["claimant_terminals"], start=1)
    )
    controls = tuple(
        ControlAsset(
            asset_id=str(row["control_asset_id"]),
            resource_type=str(row["resource_type"]),
            resource_id=str(row["resource_id"]),
            effort_coefficient=float(row["effort_coefficient"]),
        )
        for row in raw["control_assets"]
    )

    group_members_mutable: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in raw["source_group_members"]:
        group_members_mutable[str(row["group_id"])].append(
            (str(row["source_id"]), float(row.get("beta", 1.0)))
        )
    group_members = {
        group: tuple(sorted(members)) for group, members in group_members_mutable.items()
    }

    terminal_parameter_rows = raw["terminal_parameters"]
    application_efficiency = {
        (str(row["period_id"]), str(row["terminal_id"])): float(row["application_efficiency"])
        for row in terminal_parameter_rows
    }

    benchmark = CTIBenchmark(
        benchmark_id=str(raw.get("benchmark_id", "unnamed_cti_benchmark")),
        nodes=tuple(str(row["node_id"]) for row in raw["nodes"]),
        edges=edges,
        sources=sources,
        claimants=claimants,
        terminals=terminals,
        periods=periods,
        scenarios=scenarios,
        nominal_scenario="nominal",
        source_groups=tuple(str(row["group_id"]) for row in raw["source_groups"]),
        group_members=group_members,
        controls=controls,
        demand={
            (str(row["period_id"]), str(row["claimant_id"])): float(row["demand_af"])
            for row in raw["demands"]
        },
        edge_capacity={
            (str(row["scenario_id"]), str(row["period_id"]), str(row["edge_id"])): float(row["capacity_af"])
            for row in raw["edge_parameters"]
        },
        edge_efficiency={
            (str(row["scenario_id"]), str(row["period_id"]), str(row["edge_id"])): float(row["efficiency"])
            for row in raw["edge_parameters"]
        },
        source_limit={
            (str(row["scenario_id"]), str(row["period_id"]), str(row["source_id"])): float(row["q_af"])
            for row in raw["source_limits"]
        },
        source_seasonal_limit={
            (str(row["scenario_id"]), str(row["source_id"])): float(row["v_af"])
            for row in raw["source_seasonal_limits"]
        },
        shared_source_limit={
            (str(row["scenario_id"]), str(row["period_id"]), str(row["group_id"])): float(row["w_af"])
            for row in raw["shared_source_limits"]
        },
        application_efficiency=application_efficiency,
        recourse_budget={
            str(row["scenario_id"]): float(row["recourse_budget"])
            for row in raw["scenarios"]
        },
        scenario_weight={
            str(row["scenario_id"]): float(row["probability_weight"])
            for row in raw["scenarios"]
        },
        metadata={
            "schema_version": raw.get("schema_version"),
            "scientific_scope": raw.get("scientific_scope"),
        },
    )
    validate_cti_benchmark(benchmark)
    return benchmark


def load_cti_benchmark(path: str | Path) -> CTIBenchmark:
    with Path(path).open(encoding="utf-8") as stream:
        return parse_cti_payload(json.load(stream))


def _require_complete(actual: set[tuple[str, ...]], expected: set[tuple[str, ...]], label: str) -> None:
    if actual != expected:
        missing = sorted(expected - actual)[:5]
        extra = sorted(actual - expected)[:5]
        raise ValueError(f"{label} is incomplete: missing={missing}, extra={extra}")


def validate_cti_benchmark(model: CTIBenchmark) -> None:
    if len(set(model.nodes)) != len(model.nodes):
        raise ValueError("Node identifiers must be unique.")
    if len(set(model.edge_ids)) != len(model.edges):
        raise ValueError("Edge identifiers must be unique.")
    if len(set(model.source_ids)) != len(model.sources):
        raise ValueError("Source identifiers must be unique.")
    if len(set(model.claimants)) != len(model.claimants):
        raise ValueError("Claimant identifiers must be unique.")
    if len(set(model.terminal_ids)) != len(model.terminals):
        raise ValueError("Terminal record identifiers must be unique.")
    if model.nominal_scenario not in model.scenarios:
        raise ValueError("The nominal scenario is missing.")

    nodes = set(model.nodes)
    graph = nx.DiGraph()
    graph.add_nodes_from(nodes)
    for edge in model.edges:
        if edge.tail not in nodes or edge.head not in nodes:
            raise ValueError(f"Edge {edge.edge_id!r} references an unknown node.")
        graph.add_edge(edge.tail, edge.head)
    if not nx.is_directed_acyclic_graph(graph):
        raise ValueError("The CTI-RLex network must be a DAG.")

    for source in model.sources:
        if source.node not in nodes:
            raise ValueError(f"Unknown source node {source.node!r}.")
    claimant_set = set(model.claimants)
    for terminal in model.terminals:
        if terminal.claimant_id not in claimant_set or terminal.node not in nodes:
            raise ValueError(f"Invalid terminal record {terminal.terminal_id!r}.")
    if set(model.terminals_by_claimant) != claimant_set:
        raise ValueError("Every claimant must have at least one terminal record.")

    expected_demand = {(period, claimant) for period in model.periods for claimant in model.claimants}
    _require_complete(set(model.demand), expected_demand, "demand")
    if any(value < 0 for value in model.demand.values()):
        raise ValueError("Demands must be nonnegative.")
    if any(sum(model.demand[period, claimant] for period in model.periods) <= 0 for claimant in model.claimants):
        raise ValueError("Every claimant needs positive seasonal demand.")

    expected_edge = {
        (scenario, period, edge)
        for scenario in model.scenarios
        for period in model.periods
        for edge in model.edge_ids
    }
    _require_complete(set(model.edge_capacity), expected_edge, "edge_capacity")
    _require_complete(set(model.edge_efficiency), expected_edge, "edge_efficiency")
    if any(value < 0 for value in model.edge_capacity.values()):
        raise ValueError("Edge capacities must be nonnegative.")
    if any(not 0 < value <= 1 for value in model.edge_efficiency.values()):
        raise ValueError("Edge efficiencies must lie in (0, 1].")

    expected_source = {
        (scenario, period, source)
        for scenario in model.scenarios
        for period in model.periods
        for source in model.source_ids
    }
    _require_complete(set(model.source_limit), expected_source, "source_limit")
    expected_seasonal = {
        (scenario, source) for scenario in model.scenarios for source in model.source_ids
    }
    _require_complete(set(model.source_seasonal_limit), expected_seasonal, "source_seasonal_limit")
    if any(value < 0 for value in model.source_limit.values()) or any(
        value < 0 for value in model.source_seasonal_limit.values()
    ):
        raise ValueError("Source limits must be nonnegative.")

    expected_shared = {
        (scenario, period, group)
        for scenario in model.scenarios
        for period in model.periods
        for group in model.source_groups
    }
    _require_complete(set(model.shared_source_limit), expected_shared, "shared_source_limit")
    if any(value < 0 for value in model.shared_source_limit.values()):
        raise ValueError("Shared source limits must be nonnegative.")
    source_set = set(model.source_ids)
    for group in model.source_groups:
        members = model.group_members.get(group, ())
        if not members or any(source not in source_set or beta <= 0 for source, beta in members):
            raise ValueError(f"Invalid membership for source group {group!r}.")

    expected_alpha = {(period, terminal) for period in model.periods for terminal in model.terminal_ids}
    _require_complete(set(model.application_efficiency), expected_alpha, "application_efficiency")
    if any(not 0 < value <= 1 for value in model.application_efficiency.values()):
        raise ValueError("Application efficiencies must lie in (0, 1].")

    edge_by_id = model.edge_by_id
    for asset in model.controls:
        if asset.resource_type == "source" and asset.resource_id not in source_set:
            raise ValueError(f"Control {asset.asset_id!r} references an unknown source.")
        if asset.resource_type == "edge":
            if asset.resource_id not in edge_by_id:
                raise ValueError(f"Control {asset.asset_id!r} references an unknown edge.")
            if edge_by_id[asset.resource_id].role != "physical":
                raise ValueError("Logical connectors cannot be control assets.")
        if asset.resource_type not in {"source", "edge"} or asset.effort_coefficient <= 0:
            raise ValueError(f"Invalid control asset {asset.asset_id!r}.")

    if set(model.recourse_budget) != set(model.scenarios):
        raise ValueError("Recourse budgets are incomplete.")
    if set(model.scenario_weight) != set(model.scenarios):
        raise ValueError("Scenario weights are incomplete.")
    if model.recourse_budget[model.nominal_scenario] != 0:
        raise ValueError("Nominal recourse budget must be zero.")
