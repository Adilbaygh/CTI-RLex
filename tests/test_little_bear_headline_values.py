"""The three-claimant headline numbers, pinned where a reviewer will run them.

test_cache_valley_benchmark.py pins the ten-claimant instance to six decimals, but the
numbers the abstract leads with come from the three-claimant Little Bear River instance,
and no test asserted them. test_cti_rlex.py checks that the first leximin level lies
strictly between zero and one and that one company is served better than another;
test_cti_experiments.py checks that the utilitarian delivery is an upper bound and that
bounded recourse beats a rigid plan. Every one of those is an ordering. A change that
moved the guarantee from 0.4195 to 0.4155 satisfied all of them.

The pinning is in two layers because they fail for different reasons.

    test_the_released_result_files_are_what_this_code_produces compares a fresh solve with
    results/, at 1e-6 -- ten times the solver's declared feasibility tolerance. It fails
    when the code and the released artefacts drift apart, which is the failure a reviewer
    would otherwise find by hand.

    test_the_article_headline_values compares the same fresh solve with the digits the
    article prints, at half of the last one. It fails when the code and the results move
    together, which the first test cannot see.

The 135-case factorial is not re-solved here: one solve is milliseconds and 135 are not,
and the range it produces is a property of the published run rather than of a single
model. It is checked against the released file instead, which is where the article takes
it from.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from leximin.dag import (
    load_cti_benchmark,
    scale_benchmark,
    solve_cti_rlex,
    solve_utilitarian_fair,
    subset_scenarios,
)

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json"
RESULTS = ROOT / "results"

# Section 3 and the abstract, to the digits they are printed with. The tolerance on each
# is half of its last digit: that is what the article claims and no more.
PUBLISHED_SORTED_VECTOR = [0.4195, 0.4195, 0.4477]
PUBLISHED_UTIL_BR = 0.1077
PUBLISHED_RIGID = 0.3841
PUBLISHED_PRICE_OF_FAIRNESS = 2.57
PUBLISHED_VALUE_OF_RECOURSE = 9.22
PUBLISHED_ROBUSTNESS_COST = 31.5
PUBLISHED_FACTORIAL_RANGE = (0.2243, 0.7011)

FOUR_DECIMALS = 0.5e-4
TWO_DECIMALS = 0.5e-2
ONE_DECIMAL = 0.5e-1


@pytest.fixture(scope="module")
def model():
    if not BENCHMARK.exists():
        pytest.skip(f"benchmark not present: {BENCHMARK}")
    return load_cti_benchmark(BENCHMARK)


@pytest.fixture(scope="module")
def solutions(model):
    """The five rows of the method comparison, built the way the experiment script builds
    them, so that a change to either is visible here rather than only in results/."""

    rigid = scale_benchmark(
        model,
        demand_duty=2.0,
        conveyance_loss_multiplier=1.0,
        source_limit_scale=1.0,
        recourse_budget_scale=0.0,
    )
    nominal_only = subset_scenarios(model, (model.nominal_scenario,))
    return {
        "CTI-RLex proposed": solve_cti_rlex(model),
        "CTI-RLex rigid": solve_cti_rlex(rigid),
        "CTI-RLex nominal only": solve_cti_rlex(nominal_only),
        "UTIL-BR": solve_utilitarian_fair(model),
    }


def guarantee(solution) -> float:
    return min(solution.guarantees.values())


def test_the_article_headline_values(solutions):
    proposed = solutions["CTI-RLex proposed"]
    rigid = solutions["CTI-RLex rigid"]
    nominal_only = solutions["CTI-RLex nominal only"]
    utilitarian = solutions["UTIL-BR"]

    assert sorted(proposed.guarantees.values()) == pytest.approx(
        PUBLISHED_SORTED_VECTOR, abs=FOUR_DECIMALS
    )
    assert guarantee(utilitarian) == pytest.approx(PUBLISHED_UTIL_BR, abs=FOUR_DECIMALS)
    assert guarantee(rigid) == pytest.approx(PUBLISHED_RIGID, abs=FOUR_DECIMALS)

    price_of_fairness = 100.0 * (
        utilitarian.nominal_beneficial_delivery - proposed.nominal_beneficial_delivery
    ) / utilitarian.nominal_beneficial_delivery
    value_of_recourse = 100.0 * (
        guarantee(proposed) - guarantee(rigid)
    ) / guarantee(rigid)
    robustness_cost = 100.0 * (
        nominal_only.nominal_beneficial_delivery - proposed.nominal_beneficial_delivery
    ) / nominal_only.nominal_beneficial_delivery

    assert price_of_fairness == pytest.approx(
        PUBLISHED_PRICE_OF_FAIRNESS, abs=TWO_DECIMALS
    )
    assert value_of_recourse == pytest.approx(
        PUBLISHED_VALUE_OF_RECOURSE, abs=TWO_DECIMALS
    )
    assert robustness_cost == pytest.approx(PUBLISHED_ROBUSTNESS_COST, abs=ONE_DECIMAL)


def test_the_released_result_files_are_what_this_code_produces(solutions):
    path = RESULTS / "cti_rlex_experiments.json"
    if not path.exists():
        pytest.skip("results/cti_rlex_experiments.json has not been produced")
    released = {
        row["method"]: row
        for row in json.loads(path.read_text(encoding="utf-8"))["method_comparison"]
    }
    for method, solution in solutions.items():
        assert guarantee(solution) == pytest.approx(
            released[method]["minimum_guarantee"], abs=1e-6
        ), f"{method}: the code and results/ disagree on the minimum guarantee"
        assert solution.nominal_beneficial_delivery == pytest.approx(
            released[method]["nominal_beneficial_delivery_af"], rel=1e-9
        ), f"{method}: the code and results/ disagree on nominal delivery"


def test_the_guarantee_vector_is_the_one_the_verification_file_records(solutions):
    path = RESULTS / "cti_rlex_verification.json"
    if not path.exists():
        pytest.skip("results/cti_rlex_verification.json has not been produced")
    recorded = json.loads(path.read_text(encoding="utf-8"))["base_guarantees"]
    fresh = solutions["CTI-RLex proposed"].guarantees
    assert set(fresh) == set(recorded)
    for claimant, value in recorded.items():
        assert fresh[claimant] == pytest.approx(value, abs=1e-6)


def test_the_factorial_range_is_the_published_one():
    path = RESULTS / "cti_rlex_experiments.json"
    if not path.exists():
        pytest.skip("results/cti_rlex_experiments.json has not been produced")
    cases = json.loads(path.read_text(encoding="utf-8"))["sensitivity"]
    assert len(cases) == 135, "the factorial is the complete 3x3x3x5 design"
    guarantees = [case["minimum_guarantee"] for case in cases]
    low, high = PUBLISHED_FACTORIAL_RANGE
    assert min(guarantees) == pytest.approx(low, abs=FOUR_DECIMALS)
    assert max(guarantees) == pytest.approx(high, abs=FOUR_DECIMALS)


def test_the_residuals_stay_below_the_declared_tolerance(solutions):
    for method, solution in solutions.items():
        assert max(solution.residuals.values(), default=0.0) <= 1e-7, method
