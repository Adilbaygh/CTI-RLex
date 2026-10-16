"""The published plan held fixed: what every scenario, and the hull of the scenarios, still
deliver (Reviewer 1, point 1.2; scripts/fixed_plan_recourse.py)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from leximin.dag import load_cti_benchmark

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fixed_plan_recourse as fixed  # noqa: E402

BENCHMARK = ROOT / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json"


@pytest.fixture(scope="module")
def published():
    model = load_cti_benchmark(BENCHMARK)
    solution, plan_rows = fixed.published_plan(model)
    return model, dict(solution.guarantees), plan_rows


def test_every_scenario_delivers_the_published_guarantees_from_the_published_plan(published) -> None:
    model, guarantees, plan_rows = published
    for scenario in model.scenarios:
        parameters = fixed.scenario_parameters(model, scenario)
        instance, _, overrun = fixed.operate(model, "check", parameters, plan_rows)
        assert overrun < 1e-9
        assert fixed.common_level(instance, "check", plan_rows, guarantees) >= 1 - 1e-6


def test_a_convex_combination_of_the_scenarios_delivers_them_too(published) -> None:
    model, guarantees, plan_rows = published
    weights = np.random.default_rng(7).dirichlet(np.ones(len(model.scenarios)), size=5)
    vertices = [fixed.scenario_parameters(model, scenario) for scenario in model.scenarios]
    for row in weights:
        combined = fixed.combine(list(zip(map(float, row), vertices)))
        instance, _, overrun = fixed.operate(model, "check", combined, plan_rows)
        assert overrun < 1e-9
        assert fixed.common_level(instance, "check", plan_rows, guarantees) >= 1 - 1e-6


def test_a_point_outside_the_hull_can_fall_short(published) -> None:
    model, guarantees, plan_rows = published
    severe = fixed.scenario_parameters(model, "severe_system_shortage")
    tighter = {name: ({key: 0.9 * number for key, number in entry.items()} if isinstance(entry, dict) else entry)
               for name, entry in severe.items()}
    instance, _, overrun = fixed.operate(model, "check", tighter, plan_rows)
    share = fixed.common_level(instance, "check", plan_rows, guarantees)
    assert overrun > 0 or share < 1 - 1e-6
