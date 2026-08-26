from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from leximin.dag import (
    CTIBenchmark,
    ClaimantTerminal,
    DAGEdge,
    DAGSource,
    load_cti_benchmark,
    representation_invariance_error,
    solve_cti_rlex,
)


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json"


def tiny_model(*, alpha: float = 0.8, shared_limit: float = 5.0) -> CTIBenchmark:
    return CTIBenchmark(
        benchmark_id="tiny",
        nodes=("source_node", "terminal_node"),
        edges=(DAGEdge("edge", "source_node", "terminal_node", "physical"),),
        sources=(DAGSource("source", "source_node", "surface_diversion"),),
        claimants=("claimant",),
        terminals=(ClaimantTerminal("terminal", "claimant", "terminal_node"),),
        periods=("period",),
        scenarios=("nominal",),
        nominal_scenario="nominal",
        source_groups=("system",),
        group_members={"system": (("source", 1.0),)},
        controls=(),
        demand={("period", "claimant"): 10.0},
        edge_capacity={("nominal", "period", "edge"): 100.0},
        edge_efficiency={("nominal", "period", "edge"): 1.0},
        source_limit={("nominal", "period", "source"): 100.0},
        source_seasonal_limit={("nominal", "source"): 100.0},
        shared_source_limit={("nominal", "period", "system"): shared_limit},
        application_efficiency={("period", "terminal"): alpha},
        recourse_budget={"nominal": 0.0},
        scenario_weight={"nominal": 0.0},
    )


def test_shared_envelope_and_application_efficiency_are_both_active() -> None:
    solution = solve_cti_rlex(tiny_model())
    assert solution.guarantees["claimant"] == pytest.approx(0.4, abs=1e-8)
    assert solution.beneficial_delivery["nominal", "period", "terminal"] == pytest.approx(4.0)
    assert solution.residuals["max_equality_residual"] < 1e-8


def test_little_bear_smoke_and_schema() -> None:
    model = load_cti_benchmark(BENCHMARK)
    solution = solve_cti_rlex(model)
    assert model.benchmark_id.endswith("_v2")
    assert len(model.source_groups) == 2
    assert len(model.controls) == 7
    assert 0 < solution.first_leximin_level < 1
    assert solution.guarantees["company_088"] > solution.guarantees["company_130"]
    assert max(solution.residuals.values()) < 1e-7


def test_terminal_record_split_is_numerically_invariant() -> None:
    model = load_cti_benchmark(BENCHMARK)
    error, _, _ = representation_invariance_error(model, "terminal_company_130_1", 4)
    assert error < 1e-8


def test_more_recourse_cannot_reduce_first_leximin_level() -> None:
    model = load_cti_benchmark(BENCHMARK)
    no_recourse = replace(
        model,
        recourse_budget={scenario: 0.0 for scenario in model.scenarios},
    )
    baseline = solve_cti_rlex(model)
    rigid = solve_cti_rlex(no_recourse)
    assert baseline.first_leximin_level + 1e-8 >= rigid.first_leximin_level
