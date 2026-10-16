"""Claimant tiers in the progressive filling: the PRIOR-LEX comparator (Reviewer 1, point 2.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from leximin.dag import (
    CTIBenchmark,
    ClaimantTerminal,
    DAGEdge,
    DAGSource,
    load_cti_benchmark,
    solve_cti_rlex,
)


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json"


def two_claimants_one_source(source_limit: float = 10.0) -> CTIBenchmark:
    """Two claimants of 10 acre-feet each behind one source that holds `source_limit`."""

    return CTIBenchmark(
        benchmark_id="two_claimants",
        nodes=("source_node", "a_node", "b_node"),
        edges=(
            DAGEdge("to_a", "source_node", "a_node", "physical"),
            DAGEdge("to_b", "source_node", "b_node", "physical"),
        ),
        sources=(DAGSource("source", "source_node", "surface_diversion"),),
        claimants=("a", "b"),
        terminals=(
            ClaimantTerminal("terminal_a", "a", "a_node"),
            ClaimantTerminal("terminal_b", "b", "b_node"),
        ),
        periods=("period",),
        scenarios=("nominal",),
        nominal_scenario="nominal",
        source_groups=("system",),
        group_members={"system": (("source", 1.0),)},
        controls=(),
        demand={("period", "a"): 10.0, ("period", "b"): 10.0},
        edge_capacity={("nominal", "period", "to_a"): 100.0, ("nominal", "period", "to_b"): 100.0},
        edge_efficiency={("nominal", "period", "to_a"): 1.0, ("nominal", "period", "to_b"): 1.0},
        source_limit={("nominal", "period", "source"): source_limit},
        source_seasonal_limit={("nominal", "source"): source_limit},
        shared_source_limit={("nominal", "period", "system"): 100.0},
        application_efficiency={("period", "terminal_a"): 1.0, ("period", "terminal_b"): 1.0},
        recourse_budget={"nominal": 0.0},
        scenario_weight={"nominal": 0.0},
    )


def test_one_tier_is_cti_rlex() -> None:
    model = load_cti_benchmark(BENCHMARK)
    default = solve_cti_rlex(model)
    one_tier = solve_cti_rlex(model, tiers=[list(model.claimants)])
    assert one_tier.to_dict() == default.to_dict()


def test_a_senior_tier_is_filled_before_a_junior_one() -> None:
    model = two_claimants_one_source()
    shared = solve_cti_rlex(model)
    assert shared.guarantees["a"] == pytest.approx(0.5, abs=1e-8)
    assert shared.guarantees["b"] == pytest.approx(0.5, abs=1e-8)

    a_first = solve_cti_rlex(model, tiers=[["a"], ["b"]])
    assert a_first.guarantees["a"] == pytest.approx(1.0, abs=1e-8)
    assert a_first.guarantees["b"] == pytest.approx(0.0, abs=1e-8)
    assert [level.blocked_claimants for level in a_first.leximin_levels] == [("a",), ("b",)]

    b_first = solve_cti_rlex(model, tiers=[["b"], ["a"]])
    assert b_first.guarantees["b"] == pytest.approx(1.0, abs=1e-8)
    assert b_first.guarantees["a"] == pytest.approx(0.0, abs=1e-8)


def test_a_junior_tier_receives_what_the_senior_tier_cannot_use() -> None:
    model = two_claimants_one_source(source_limit=14.0)
    a_first = solve_cti_rlex(model, tiers=[["a"], ["b"]])
    assert a_first.guarantees["a"] == pytest.approx(1.0, abs=1e-8)
    assert a_first.guarantees["b"] == pytest.approx(0.4, abs=1e-8)


@pytest.mark.parametrize(
    "tiers",
    [
        [["a"]],
        [["a"], ["a", "b"]],
        [["a", "b"], []],
        [["a"], ["b"], ["c"]],
    ],
)
def test_the_tiers_must_name_every_claimant_exactly_once(tiers) -> None:
    with pytest.raises(ValueError):
        solve_cti_rlex(two_claimants_one_source(), tiers=tiers)


def test_a_senior_tier_never_does_worse_than_under_cti_rlex() -> None:
    model = load_cti_benchmark(BENCHMARK)
    senior = ["company_088", "company_130"]
    baseline = solve_cti_rlex(model)
    tiered = solve_cti_rlex(model, tiers=[senior, ["company_132"]])
    before = sorted(baseline.guarantees[claimant] for claimant in senior)
    after = sorted(tiered.guarantees[claimant] for claimant in senior)
    for old, new in zip(before, after):
        if abs(new - old) > 1e-7:
            assert new > old
            break
    assert min(tiered.guarantees.values()) <= min(baseline.guarantees.values()) + 1e-7
    assert max(tiered.residuals.values()) < 1e-7
