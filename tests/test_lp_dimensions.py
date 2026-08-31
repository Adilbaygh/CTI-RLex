"""The closed form of Equation (13), against the program the solver actually builds.

Section 2.8 of the manuscript says of that closed form that "the equality and inequality
counts follow from the same argument and are checked by the same test", and Section 3.1
says "the agreement is enforced by a regression test rather than asserted in prose". This
is that test.

Writing the formula out is the point of it. tests/test_cache_valley_benchmark.py already
compares the solver with three integers -- 2886, 2150 and 1539 -- but three integers cannot
tell a reader whether the model still has the shape the article describes, and they cannot
catch a change that moves the implementation and the recorded numbers together. Here the
counts are recomputed from the sets themselves, so a variable block added to the model
without a corresponding term in Equation (13) fails, and so does a term in Equation (13)
that the model does not build.

Both released benchmarks are covered, because the article prints sizes for both: 869
variables, 600 equalities and 507 inequalities for the three-claimant Little Bear River
instance, and 2886, 2150 and 1539 for the ten-claimant Cache Valley instance.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from leximin.dag import load_cti_benchmark, lp_dimensions

ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = [
    ROOT / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json",
    ROOT / "DATA" / "CacheValley_2025_Benchmark" / "benchmark.json",
]
AVAILABLE = [path for path in BENCHMARKS if path.exists()]

# Section 3.1, in the order (variables, equalities, inequalities).
PUBLISHED = {
    "LittleBearRiver_2025_Benchmark": (869, 600, 507),
    "CacheValley_2025_Benchmark": (2886, 2150, 1539),
}


def closed_form(model) -> dict[str, int]:
    """Equation (13) and the two counts that follow from the same argument.

    variables    = |O||K|(|E| + |S| + 2|T|) + (|O| - 1)|K||I_R| + |F| + 1
    equalities   = |O||K|(|V| + |T|)
    inequalities = |O||K|(|F| + |H|) + |O||S| + 2(|O| - 1)|K||I_R| + (|O| - 1) + P + |F|

    |O| scenarios, |K| periods, |E| edges, |S| sources, |T| terminals, |F| claimants,
    |V| nodes, |H| source groups, |I_R| recourse controls. The trailing |F| are the
    common-level rows binding theta to every active claimant, and the final +1 in the
    variable count is that single theta. P counts the claimant-period-scenario cells
    carrying a positive demand, which are the ones that get a service-ratio row.
    """

    scenarios = len(model.scenarios)
    periods = len(model.periods)
    contingencies = scenarios - 1
    claimants = len(model.claimants)
    controls = len(model.controls)

    positive_cells = scenarios * sum(
        1
        for period in model.periods
        for claimant in model.claimants
        if model.demand[period, claimant] > 0
    )

    return {
        "variables": scenarios * periods * (
            len(model.edges) + len(model.sources) + 2 * len(model.terminals)
        )
        + contingencies * periods * controls
        + claimants
        + 1,
        "equality_constraints": scenarios * periods * (
            len(model.nodes) + len(model.terminals)
        ),
        "inequality_constraints": scenarios * periods * (
            claimants + len(model.source_groups)
        )
        + scenarios * len(model.sources)
        + 2 * contingencies * periods * controls
        + contingencies
        + positive_cells
        + claimants,
    }


@pytest.mark.parametrize("path", AVAILABLE, ids=lambda path: path.parent.name)
def test_the_solver_builds_the_program_equation_13_describes(path: Path) -> None:
    model = load_cti_benchmark(path)
    built = lp_dimensions(model)
    expected = closed_form(model)
    for key, value in expected.items():
        assert built[key] == value, (
            f"{path.parent.name}: the solver builds {built[key]} {key.replace('_', ' ')} "
            f"and Equation (13) gives {value}; the manuscript and the implementation have "
            "diverged"
        )


@pytest.mark.parametrize("path", AVAILABLE, ids=lambda path: path.parent.name)
def test_the_closed_form_gives_the_sizes_the_article_prints(path: Path) -> None:
    expected = closed_form(load_cti_benchmark(path))
    assert (
        expected["variables"],
        expected["equality_constraints"],
        expected["inequality_constraints"],
    ) == PUBLISHED[path.parent.name]


def test_every_released_benchmark_is_covered() -> None:
    assert len(AVAILABLE) == len(BENCHMARKS), (
        "a benchmark is missing, so the parametrized tests above would pass on fewer "
        "instances than the article reports"
    )
