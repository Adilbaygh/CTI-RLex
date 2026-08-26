from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import networkx as nx

from .domain import Benchmark, Edge, User, ensure_complete_mapping


def parse_fraction(value: Any) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value, 1)
    if isinstance(value, float):
        return Fraction(str(value))
    if isinstance(value, str):
        return Fraction(value.strip())
    raise TypeError(f"Unsupported numeric value: {value!r}")


def load_benchmark(path: str | Path) -> Benchmark:
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    nodes = tuple(str(x) for x in raw["nodes"])
    source = str(raw["source"])
    edges = tuple(
        Edge(str(item["id"]), str(item["tail"]), str(item["head"]))
        for item in raw["edges"]
    )
    users = tuple(
        User(
            str(item["id"]),
            str(item["terminal"]),
            parse_fraction(item.get("weight", 1)),
        )
        for item in raw["users"]
    )
    periods = tuple(str(x) for x in raw["periods"])
    user_ids = tuple(user.user_id for user in users)
    edge_ids = tuple(edge.edge_id for edge in edges)

    demand = {
        period: {
            user_id: parse_fraction(raw["demand"][period][user_id])
            for user_id in user_ids
        }
        for period in periods
    }
    source_capacity = {
        period: parse_fraction(raw["source_capacity"][period])
        for period in periods
    }
    edge_capacity = {
        period: {
            edge_id: parse_fraction(raw["edge_capacity"][period][edge_id])
            for edge_id in edge_ids
        }
        for period in periods
    }
    efficiency = {
        period: {
            edge_id: parse_fraction(raw["efficiency"][period][edge_id])
            for edge_id in edge_ids
        }
        for period in periods
    }

    raw_positions = raw.get("node_positions")
    node_positions = (
        {
            str(node): (float(coords[0]), float(coords[1]))
            for node, coords in raw_positions.items()
        }
        if raw_positions is not None
        else None
    )

    benchmark = Benchmark(
        name=str(raw["name"]),
        description=str(raw.get("description", "")),
        nodes=nodes,
        source=source,
        edges=edges,
        users=users,
        periods=periods,
        demand=demand,
        source_capacity=source_capacity,
        edge_capacity=edge_capacity,
        efficiency=efficiency,
        node_positions=node_positions,
    )
    validate_benchmark(benchmark)
    return benchmark


def validate_benchmark(model: Benchmark) -> None:
    if model.source not in model.nodes:
        raise ValueError("The source node is not contained in nodes.")
    if len(set(model.nodes)) != len(model.nodes):
        raise ValueError("Node identifiers must be unique.")
    if len(set(model.edge_ids)) != len(model.edge_ids):
        raise ValueError("Edge identifiers must be unique.")
    if len(set(model.user_ids)) != len(model.user_ids):
        raise ValueError("User identifiers must be unique.")

    graph = nx.DiGraph()
    graph.add_nodes_from(model.nodes)
    graph.add_edges_from((edge.tail, edge.head, {"edge_id": edge.edge_id}) for edge in model.edges)

    if not nx.is_directed_acyclic_graph(graph):
        raise ValueError("The benchmark must be a directed acyclic graph.")
    if graph.in_degree(model.source) != 0:
        raise ValueError("The source must have zero in-degree.")
    for node in model.nodes:
        if node == model.source:
            continue
        if graph.in_degree(node) != 1:
            raise ValueError(f"Tree benchmark requires in-degree 1 for node {node!r}.")
        if not nx.has_path(graph, model.source, node):
            raise ValueError(f"Node {node!r} is not reachable from the source.")
    if len(model.edges) != len(model.nodes) - 1:
        raise ValueError("A rooted tree must contain |V|-1 edges.")

    for user in model.users:
        if user.terminal not in model.nodes:
            raise ValueError(f"Unknown terminal {user.terminal!r} for user {user.user_id!r}.")
        if graph.out_degree(user.terminal) != 0:
            raise ValueError(
                f"User {user.user_id!r} must be assigned to a terminal leaf; "
                f"node {user.terminal!r} has outgoing edges."
            )
        if user.weight <= 0:
            raise ValueError("Service weights must be strictly positive.")

    if model.node_positions is not None:
        ensure_complete_mapping(model.nodes, model.node_positions, "node_positions")

    ensure_complete_mapping(model.periods, model.demand, "demand periods")
    ensure_complete_mapping(model.periods, model.source_capacity, "source capacities")
    ensure_complete_mapping(model.periods, model.edge_capacity, "edge-capacity periods")
    ensure_complete_mapping(model.periods, model.efficiency, "efficiency periods")

    for period in model.periods:
        ensure_complete_mapping(model.user_ids, model.demand[period], f"demand[{period}]")
        ensure_complete_mapping(model.edge_ids, model.edge_capacity[period], f"capacity[{period}]")
        ensure_complete_mapping(model.edge_ids, model.efficiency[period], f"efficiency[{period}]")
        if model.source_capacity[period] < 0:
            raise ValueError("Source capacities must be nonnegative.")
        for value in model.demand[period].values():
            if value < 0:
                raise ValueError("Demands must be nonnegative.")
        for value in model.edge_capacity[period].values():
            if value < 0:
                raise ValueError("Edge capacities must be nonnegative.")
        for value in model.efficiency[period].values():
            if not (Fraction(0) < value <= Fraction(1)):
                raise ValueError("Efficiencies must lie in (0, 1].")

    if not model.active_records:
        raise ValueError("At least one positive-demand service record is required.")
