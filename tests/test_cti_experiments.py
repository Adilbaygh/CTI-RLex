from __future__ import annotations

from pathlib import Path

import pytest

from leximin.dag import (
    disable_source,
    load_cti_benchmark,
    scale_benchmark,
    solve_cti_rlex,
    solve_robust_proportional,
    solve_utilitarian,
    subset_scenarios,
)


BENCHMARK = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "LittleBearRiver_2025_Benchmark"
    / "benchmark.json"
)


@pytest.fixture(scope="module")
def model():
    return load_cti_benchmark(BENCHMARK)


@pytest.fixture(scope="module")
def proposed(model):
    return solve_cti_rlex(model)


def test_utilitarian_is_nominal_delivery_upper_bound(model, proposed):
    utilitarian = solve_utilitarian(model)
    assert utilitarian.nominal_beneficial_delivery >= (
        proposed.nominal_beneficial_delivery - 1e-5
    )


def test_bounded_recourse_improves_rigid_robust_floor(model, proposed):
    rigid = scale_benchmark(
        model,
        demand_duty=2.0,
        conveyance_loss_multiplier=1.0,
        source_limit_scale=1.0,
        recourse_budget_scale=0.0,
    )
    rigid_solution = solve_cti_rlex(rigid)
    assert proposed.first_leximin_level >= rigid_solution.first_leximin_level + 1e-4


def test_leximin_refines_the_common_robust_floor(model, proposed):
    proportional = solve_robust_proportional(model)
    assert proportional.first_leximin_level == pytest.approx(
        proposed.first_leximin_level, abs=1e-6
    )
    assert sorted(proposed.guarantees.values()) >= sorted(
        proportional.guarantees.values()
    )


def test_base_scaling_reproduces_benchmark(model, proposed):
    scaled = scale_benchmark(
        model,
        demand_duty=2.0,
        conveyance_loss_multiplier=1.0,
        source_limit_scale=1.0,
        recourse_budget_scale=1.0,
    )
    result = solve_cti_rlex(scaled)
    assert dict(result.guarantees) == pytest.approx(dict(proposed.guarantees), abs=1e-7)


def test_scenario_subset_retains_only_requested_scenarios(model):
    selected = (model.nominal_scenario, model.contingency_scenarios[0])
    reduced = subset_scenarios(model, selected)
    result = solve_cti_rlex(reduced)
    assert reduced.scenarios == selected
    assert all(key[0] in selected for key in result.beneficial_delivery)


def test_disabled_source_has_zero_injection(model):
    source = model.source_ids[0]
    reduced = disable_source(model, source)
    result = solve_cti_rlex(reduced)
    assert max(
        abs(value)
        for (scenario, period, source_id), value in result.source_injection.items()
        if source_id == source
    ) <= 1e-8
