from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DAGEdge:
    edge_id: str
    tail: str
    head: str
    role: str


@dataclass(frozen=True, slots=True)
class DAGSource:
    source_id: str
    node: str
    source_class: str


@dataclass(frozen=True, slots=True)
class ClaimantTerminal:
    terminal_id: str
    claimant_id: str
    node: str


@dataclass(frozen=True, slots=True)
class ControlAsset:
    asset_id: str
    resource_type: str
    resource_id: str
    effort_coefficient: float


@dataclass(frozen=True, slots=True)
class CTIBenchmark:
    benchmark_id: str
    nodes: tuple[str, ...]
    edges: tuple[DAGEdge, ...]
    sources: tuple[DAGSource, ...]
    claimants: tuple[str, ...]
    terminals: tuple[ClaimantTerminal, ...]
    periods: tuple[str, ...]
    scenarios: tuple[str, ...]
    nominal_scenario: str
    source_groups: tuple[str, ...]
    group_members: Mapping[str, tuple[tuple[str, float], ...]]
    controls: tuple[ControlAsset, ...]
    demand: Mapping[tuple[str, str], float]
    edge_capacity: Mapping[tuple[str, str, str], float]
    edge_efficiency: Mapping[tuple[str, str, str], float]
    source_limit: Mapping[tuple[str, str, str], float]
    source_seasonal_limit: Mapping[tuple[str, str], float]
    shared_source_limit: Mapping[tuple[str, str, str], float]
    application_efficiency: Mapping[tuple[str, str], float]
    recourse_budget: Mapping[str, float]
    scenario_weight: Mapping[str, float]
    metadata: Mapping[str, object] | None = None

    @property
    def edge_ids(self) -> tuple[str, ...]:
        return tuple(edge.edge_id for edge in self.edges)

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(source.source_id for source in self.sources)

    @property
    def terminal_ids(self) -> tuple[str, ...]:
        return tuple(terminal.terminal_id for terminal in self.terminals)

    @property
    def contingency_scenarios(self) -> tuple[str, ...]:
        return tuple(item for item in self.scenarios if item != self.nominal_scenario)

    @property
    def terminals_by_claimant(self) -> dict[str, tuple[ClaimantTerminal, ...]]:
        return {
            claimant: tuple(item for item in self.terminals if item.claimant_id == claimant)
            for claimant in self.claimants
        }

    @property
    def terminals_by_node(self) -> dict[str, tuple[ClaimantTerminal, ...]]:
        return {
            node: tuple(item for item in self.terminals if item.node == node)
            for node in self.nodes
        }

    @property
    def source_node(self) -> dict[str, str]:
        return {source.source_id: source.node for source in self.sources}

    @property
    def edge_by_id(self) -> dict[str, DAGEdge]:
        return {edge.edge_id: edge for edge in self.edges}

    @property
    def control_by_id(self) -> dict[str, ControlAsset]:
        return {asset.asset_id: asset for asset in self.controls}

    def incoming_edges(self) -> dict[str, tuple[DAGEdge, ...]]:
        return {
            node: tuple(edge for edge in self.edges if edge.head == node)
            for node in self.nodes
        }

    def outgoing_edges(self) -> dict[str, tuple[DAGEdge, ...]]:
        return {
            node: tuple(edge for edge in self.edges if edge.tail == node)
            for node in self.nodes
        }
