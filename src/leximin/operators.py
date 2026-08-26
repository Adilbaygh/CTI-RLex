from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction
from itertools import pairwise

import networkx as nx
import numpy as np

from .domain import Benchmark


def build_graph(model: Benchmark) -> nx.DiGraph:
    graph = nx.DiGraph()
    graph.add_nodes_from(model.nodes)
    for edge in model.edges:
        graph.add_edge(edge.tail, edge.head, edge_id=edge.edge_id)
    return graph


def user_paths(model: Benchmark) -> dict[str, tuple[str, ...]]:
    graph = build_graph(model)
    edge_lookup = {(edge.tail, edge.head): edge.edge_id for edge in model.edges}
    paths: dict[str, tuple[str, ...]] = {}
    for user in model.users:
        nodes = nx.shortest_path(graph, model.source, user.terminal)
        paths[user.user_id] = tuple(
            edge_lookup[(tail, head)] for tail, head in pairwise(nodes)
        )
    return paths


def build_operator_exact(
    model: Benchmark,
) -> tuple[dict[tuple[str, str, str], Fraction], dict[tuple[str, str], Fraction]]:
    """Return exact A[k,e,f] and b[k,f] path coefficients."""
    paths = user_paths(model)
    a: dict[tuple[str, str, str], Fraction] = {}
    b: dict[tuple[str, str], Fraction] = {}
    for period in model.periods:
        for user in model.users:
            path = paths[user.user_id]
            source_coeff = Fraction(1)
            for edge_id in path:
                source_coeff /= model.efficiency[period][edge_id]
            b[(period, user.user_id)] = source_coeff
            for edge_id in model.edge_ids:
                if edge_id not in path:
                    a[(period, edge_id, user.user_id)] = Fraction(0)
                    continue
                position = path.index(edge_id)
                coeff = Fraction(1)
                for downstream_id in path[position:]:
                    coeff /= model.efficiency[period][downstream_id]
                a[(period, edge_id, user.user_id)] = coeff
    return a, b


def flows_from_operator_exact(
    model: Benchmark,
    ratios: Mapping[tuple[str, str], Fraction],
) -> tuple[dict[tuple[str, str], Fraction], dict[str, Fraction]]:
    a, b = build_operator_exact(model)
    edge_flows: dict[tuple[str, str], Fraction] = {}
    source_flows: dict[str, Fraction] = {}
    for period in model.periods:
        source_flows[period] = sum(
            b[(period, user.user_id)]
            * model.demand[period][user.user_id]
            * ratios.get((period, user.user_id), Fraction(0))
            for user in model.users
        )
        for edge_id in model.edge_ids:
            edge_flows[(period, edge_id)] = sum(
                a[(period, edge_id, user.user_id)]
                * model.demand[period][user.user_id]
                * ratios.get((period, user.user_id), Fraction(0))
                for user in model.users
            )
    return edge_flows, source_flows


def flows_from_node_balance_exact(
    model: Benchmark,
    ratios: Mapping[tuple[str, str], Fraction],
) -> tuple[dict[tuple[str, str], Fraction], dict[str, Fraction]]:
    graph = build_graph(model)
    incoming = model.incoming_edge_by_node()
    outgoing = model.outgoing_edges_by_node()
    terminal_by_user = model.terminal_by_user
    edge_flows: dict[tuple[str, str], Fraction] = {}
    source_flows: dict[str, Fraction] = {}

    reverse_topological = list(reversed(list(nx.topological_sort(graph))))
    for period in model.periods:
        withdrawals = {node: Fraction(0) for node in model.nodes}
        for user in model.users:
            withdrawals[terminal_by_user[user.user_id]] += (
                model.demand[period][user.user_id]
                * ratios.get((period, user.user_id), Fraction(0))
            )

        for node in reverse_topological:
            if node == model.source:
                continue
            outgoing_flow = sum(
                edge_flows[(period, edge.edge_id)] for edge in outgoing[node]
            )
            incoming_edge = incoming[node]
            edge_flows[(period, incoming_edge.edge_id)] = (
                withdrawals[node] + outgoing_flow
            ) / model.efficiency[period][incoming_edge.edge_id]

        source_flows[period] = sum(
            edge_flows[(period, edge.edge_id)] for edge in outgoing[model.source]
        )
    return edge_flows, source_flows


def build_balance_matrices(
    model: Benchmark, period: str
) -> tuple[np.ndarray, np.ndarray, tuple[str, ...], tuple[str, ...]]:
    """Build floating M and terminal-assignment P for M B = P x."""
    graph = build_graph(model)
    node_order = tuple(node for node in reversed(list(nx.topological_sort(graph))) if node != model.source)
    incoming = model.incoming_edge_by_node()
    edge_order = tuple(incoming[node].edge_id for node in node_order)
    edge_pos = {edge_id: idx for idx, edge_id in enumerate(edge_order)}
    node_pos = {node: idx for idx, node in enumerate(node_order)}
    outgoing = model.outgoing_edges_by_node()

    m = np.zeros((len(node_order), len(edge_order)), dtype=float)
    for node in node_order:
        row = node_pos[node]
        incoming_edge = incoming[node]
        m[row, edge_pos[incoming_edge.edge_id]] = float(
            model.efficiency[period][incoming_edge.edge_id]
        )
        for edge in outgoing[node]:
            m[row, edge_pos[edge.edge_id]] = -1.0

    p = np.zeros((len(node_order), len(model.users)), dtype=float)
    for col, user in enumerate(model.users):
        p[node_pos[user.terminal], col] += 1.0
    return m, p, node_order, edge_order


def matrix_operator(model: Benchmark, period: str) -> tuple[np.ndarray, tuple[str, ...]]:
    m, p, _, edge_order = build_balance_matrices(model, period)
    return np.linalg.solve(m, p), edge_order


def exact_node_residuals(
    model: Benchmark,
    ratios: Mapping[tuple[str, str], Fraction],
    edge_flows: Mapping[tuple[str, str], Fraction],
) -> dict[tuple[str, str], Fraction]:
    incoming = model.incoming_edge_by_node()
    outgoing = model.outgoing_edges_by_node()
    terminal_by_user = model.terminal_by_user
    residuals: dict[tuple[str, str], Fraction] = {}
    for period in model.periods:
        withdrawals = {node: Fraction(0) for node in model.nodes}
        for user in model.users:
            withdrawals[terminal_by_user[user.user_id]] += (
                model.demand[period][user.user_id]
                * ratios.get((period, user.user_id), Fraction(0))
            )
        for node in model.nodes:
            if node == model.source:
                continue
            in_edge = incoming[node]
            delivered = (
                model.efficiency[period][in_edge.edge_id]
                * edge_flows[(period, in_edge.edge_id)]
            )
            sent = sum(edge_flows[(period, edge.edge_id)] for edge in outgoing[node])
            residuals[(period, node)] = delivered - sent - withdrawals[node]
    return residuals
