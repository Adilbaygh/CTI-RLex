from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class Edge:
    edge_id: str
    tail: str
    head: str


@dataclass(frozen=True, slots=True)
class User:
    user_id: str
    terminal: str
    weight: Fraction


@dataclass(frozen=True, slots=True)
class Benchmark:
    name: str
    description: str
    nodes: tuple[str, ...]
    source: str
    edges: tuple[Edge, ...]
    users: tuple[User, ...]
    periods: tuple[str, ...]
    demand: Mapping[str, Mapping[str, Fraction]]
    source_capacity: Mapping[str, Fraction]
    edge_capacity: Mapping[str, Mapping[str, Fraction]]
    efficiency: Mapping[str, Mapping[str, Fraction]]
    node_positions: Mapping[str, tuple[float, float]] | None = None

    @property
    def edge_ids(self) -> tuple[str, ...]:
        return tuple(edge.edge_id for edge in self.edges)

    @property
    def user_ids(self) -> tuple[str, ...]:
        return tuple(user.user_id for user in self.users)

    @property
    def terminals(self) -> tuple[str, ...]:
        return tuple(user.terminal for user in self.users)

    @property
    def active_records(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (period, user.user_id)
            for period in self.periods
            for user in self.users
            if self.demand[period][user.user_id] > 0
        )

    @property
    def weight_by_user(self) -> dict[str, Fraction]:
        return {user.user_id: user.weight for user in self.users}

    @property
    def terminal_by_user(self) -> dict[str, str]:
        return {user.user_id: user.terminal for user in self.users}

    def edge_by_id(self) -> dict[str, Edge]:
        return {edge.edge_id: edge for edge in self.edges}

    def incoming_edge_by_node(self) -> dict[str, Edge]:
        result: dict[str, Edge] = {}
        for edge in self.edges:
            if edge.head in result:
                raise ValueError(f"Node {edge.head!r} has more than one incoming edge.")
            result[edge.head] = edge
        return result

    def outgoing_edges_by_node(self) -> dict[str, tuple[Edge, ...]]:
        grouped: dict[str, list[Edge]] = {node: [] for node in self.nodes}
        for edge in self.edges:
            grouped[edge.tail].append(edge)
        return {node: tuple(edges) for node, edges in grouped.items()}

    def record_index(self) -> dict[tuple[str, str], int]:
        return {record: idx for idx, record in enumerate(self.active_records)}


def ensure_complete_mapping(
    keys: Sequence[str], mapping: Mapping[str, object], label: str
) -> None:
    missing = [key for key in keys if key not in mapping]
    extra = [key for key in mapping if key not in keys]
    if missing or extra:
        raise ValueError(f"{label}: missing={missing}, extra={extra}")
