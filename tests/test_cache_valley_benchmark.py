"""Regression tests for the ten-claimant Cache Valley benchmark.

Reviewer item 3.8: the test suite exercised only the three-claimant instance, so the
benchmark that carries the paper's discrimination result had no automated check. These
tests pin the published program size, the number of resolved guarantee levels, and the
comparison that separates the lexicographic rule from a common floor.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from leximin.dag import (
    load_cti_benchmark,
    lp_dimensions,
    solve_cti_rlex,
    solve_robust_proportional,
)

BENCHMARK = (
    Path(__file__).resolve().parents[1]
    / "DATA"
    / "CacheValley_2025_Benchmark"
    / "benchmark.json"
)

# The published values of Section 3.1 and Table 3.
PUBLISHED_DIMENSIONS = {
    "variables": 2886,
    "equality_constraints": 2150,
    "inequality_constraints": 1539,
}
PUBLISHED_LEVELS = 7
PUBLISHED_SORTED_RLEX = [
    0.056394, 0.137445, 0.307274, 0.307274, 0.365296,
    0.365296, 0.674098, 0.674098, 0.882145, 1.000000,
]
PUBLISHED_SORTED_PROP = [
    0.056394, 0.056394, 0.137445, 0.189221, 0.424984,
    0.480500, 0.774872, 0.882145, 1.000000, 1.000000,
]


@pytest.fixture(scope="module")
def model():
    if not BENCHMARK.exists():
        pytest.skip(f"benchmark not present: {BENCHMARK}")
    return load_cti_benchmark(BENCHMARK)


@pytest.fixture(scope="module")
def proposed(model):
    return solve_cti_rlex(model)


def test_program_size_matches_the_published_closed_form(model):
    dimensions = lp_dimensions(model)
    for key, expected in PUBLISHED_DIMENSIONS.items():
        assert dimensions[key] == expected


def test_ten_claimants_and_seven_guarantee_levels(model, proposed):
    assert len(model.claimants) == 10
    assert len(proposed.leximin_levels) == PUBLISHED_LEVELS


def test_sorted_guarantee_vector_reproduces_table_3(proposed):
    assert sorted(proposed.guarantees.values()) == pytest.approx(
        PUBLISHED_SORTED_RLEX, abs=1e-6
    )


def test_common_floor_comparator_reproduces_table_3(model):
    proportional = solve_robust_proportional(model)
    assert sorted(proportional.guarantees.values()) == pytest.approx(
        PUBLISHED_SORTED_PROP, abs=1e-6
    )


def test_the_two_rules_first_differ_at_the_second_position(model, proposed):
    """The comparison the paper rests on: position 2 decides, in favour of CTI-RLex."""

    proportional = solve_robust_proportional(model)
    left = sorted(proposed.guarantees.values())
    right = sorted(proportional.guarantees.values())

    assert left[0] == pytest.approx(right[0], abs=1e-6)  # both maximize the minimum
    assert left[1] > right[1] + 1e-4
    assert left[1] == pytest.approx(0.137445, abs=1e-6)
    assert right[1] == pytest.approx(0.056394, abs=1e-6)


def test_lexicographic_plan_leaves_one_claimant_at_the_floor(model, proposed):
    proportional = solve_robust_proportional(model)

    def at_floor(values: list[float]) -> int:
        return sum(1 for value in values if abs(value - min(values)) <= 1e-7)

    assert at_floor(list(proposed.guarantees.values())) == 1
    assert at_floor(list(proportional.guarantees.values())) == 2


def test_refinement_costs_about_one_percent_of_nominal_delivery(model, proposed):
    proportional = solve_robust_proportional(model)
    price = (
        100.0
        * (proportional.nominal_beneficial_delivery - proposed.nominal_beneficial_delivery)
        / proportional.nominal_beneficial_delivery
    )
    assert price == pytest.approx(1.22, abs=0.05)


def test_residuals_stay_below_the_linear_programming_tolerance(proposed):
    assert max(proposed.residuals.values(), default=0.0) <= 1e-7
