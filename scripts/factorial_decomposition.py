"""Decompose the 135-case factorial exactly, into main effects and interactions.

The factorial design reports a range -- the minimum guarantee runs from 0.2243 to 0.7011 --
and the direction of each factor, which says that the result is conditional on the
assumptions but not what carries that conditionality. A reader cannot tell from a range
whether one factor dominates, whether two of them interact, or whether the recourse budget
matters at all once the physical assumptions are fixed.

The design answers that exactly rather than approximately. It is a complete balanced
3x3x3x5 factorial: every combination of net duty, conveyance-loss multiplier, source-limit
scale and recourse-budget scale is present exactly once, so the sum of squares about the
grand mean splits into the fifteen effect terms with nothing left over. The identity is
asserted here rather than assumed, and if it ever fails the design is no longer balanced and
the decomposition is void.

Two things this is not. It is not an analysis of variance in the inferential sense: the
cases are deterministic solves of one model, not draws from a population, so there is no
error term, no replication and no p-value, and the percentages below describe the observed
variation rather than estimating anything. And it is not a claim about the world: it
partitions the response of this benchmark to the ranges the design happens to sweep, which
is why the marginal means are reported beside the percentages.

Run:  python scripts/factorial_decomposition.py
Writes: results/factorial_decomposition.json
"""

from __future__ import annotations

import itertools
import json
import statistics
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "results" / "cti_rlex_experiments.json"
OUTPUT = REPO / "results" / "factorial_decomposition.json"

FACTORS = {
    "demand_duty_af_per_acre": "net duty",
    "conveyance_loss_multiplier": "conveyance loss",
    "source_limit_scale": "source limit",
    "recourse_budget_scale": "recourse budget",
}
RESPONSES = {
    "minimum_guarantee": "minimum guarantee",
    "nominal_beneficial_delivery_af": "nominal beneficial delivery (acre-ft)",
    "worst_scenario_beneficial_delivery_af": "worst-scenario delivery (acre-ft)",
    "normalized_recourse_effort": "normalized recourse effort",
}
TOLERANCE = 1e-9


def levels(cases: list[dict]) -> dict[str, list[float]]:
    return {factor: sorted({case[factor] for case in cases}) for factor in FACTORS}


def check_balanced(cases: list[dict], factor_levels: dict[str, list[float]]) -> None:
    """A complete balanced design is what makes the decomposition exact rather than fitted.

    Every combination must appear exactly once; otherwise the effect terms are no longer
    orthogonal, the sums of squares no longer add to the total, and the percentages below
    would be an artefact of the imbalance.
    """

    expected = 1
    for values in factor_levels.values():
        expected *= len(values)
    if len(cases) != expected:
        raise SystemExit(f"{len(cases)} cases for a design of {expected} cells")
    seen = {tuple(case[factor] for factor in FACTORS) for case in cases}
    if len(seen) != expected:
        raise SystemExit(f"{len(seen)} distinct cells among {len(cases)} cases")


def decompose(cases: list[dict], response: str,
              factor_levels: dict[str, list[float]]) -> dict[str, Any]:
    """The exact sum-of-squares split of one response over the design.

    The effect of a factor subset S at a cell is the inclusion-exclusion alternating sum of
    the marginal means over the subsets of S. On a complete balanced design these effects
    are orthogonal, so squaring and summing them over the cells partitions the total exactly;
    that identity is the check at the end.
    """

    values = {tuple(case[factor] for factor in FACTORS): case[response] for case in cases}
    names = list(FACTORS)
    grand = statistics.fmean(values.values())

    def marginal(subset: tuple[int, ...], cell: tuple[float, ...]) -> float:
        selected = [
            value for key, value in values.items()
            if all(key[index] == cell[index] for index in subset)
        ]
        return statistics.fmean(selected)

    terms: dict[str, dict[str, Any]] = {}
    for size in range(1, len(names) + 1):
        for subset in itertools.combinations(range(len(names)), size):
            label = " x ".join(FACTORS[names[index]] for index in subset)
            total = 0.0
            for cell in values:
                effect = 0.0
                for count in range(len(subset) + 1):
                    for inner in itertools.combinations(subset, count):
                        sign = (-1) ** (len(subset) - count)
                        effect += sign * marginal(inner, cell)
                total += effect * effect
            degrees = 1
            for index in subset:
                degrees *= len(factor_levels[names[index]]) - 1
            terms[label] = {
                "order": size,
                "factors": [names[index] for index in subset],
                "sum_of_squares": total,
                "degrees_of_freedom": degrees,
            }

    total_ss = sum((value - grand) ** 2 for value in values.values())
    accounted = sum(term["sum_of_squares"] for term in terms.values())
    exact = abs(total_ss - accounted) <= TOLERANCE * max(1.0, total_ss)
    for term in terms.values():
        term["share_percent"] = 100.0 * term["sum_of_squares"] / total_ss if total_ss else 0.0

    # A share is a proportion of variation; a marginal mean is the response itself. Both are
    # reported because the first says what carries the variation and the second says what it
    # is worth in the units the paper reports.
    marginals = {
        FACTORS[name]: {
            f"{level:g}": statistics.fmean(
                [value for key, value in values.items() if key[index] == level]
            )
            for level in factor_levels[name]
        }
        for index, name in enumerate(names)
    }
    monotone = {}
    for name, table in marginals.items():
        ordered = [table[key] for key in sorted(table, key=float)]
        rising = all(a <= b + TOLERANCE for a, b in zip(ordered, ordered[1:]))
        falling = all(a >= b - TOLERANCE for a, b in zip(ordered, ordered[1:]))
        monotone[name] = "increasing" if rising else "decreasing" if falling else "neither"

    return {
        "grand_mean": grand,
        "minimum": min(values.values()),
        "maximum": max(values.values()),
        "total_sum_of_squares": total_ss,
        "sum_of_squares_accounted": accounted,
        "decomposition_is_exact": exact,
        "main_effect_share_percent": sum(
            term["share_percent"] for term in terms.values() if term["order"] == 1
        ),
        "interaction_share_percent": sum(
            term["share_percent"] for term in terms.values() if term["order"] > 1
        ),
        "terms": dict(
            sorted(terms.items(), key=lambda item: -item[1]["share_percent"])
        ),
        "marginal_means": marginals,
        "direction": monotone,
    }


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing {SOURCE.relative_to(REPO)}")
    cases = json.loads(SOURCE.read_text(encoding="utf-8"))["sensitivity"]
    factor_levels = levels(cases)
    check_balanced(cases, factor_levels)

    payload: dict[str, Any] = {
        "design": "x".join(str(len(values)) for values in factor_levels.values())
        + " complete balanced factorial",
        "cases": len(cases),
        "factors": {FACTORS[name]: values for name, values in factor_levels.items()},
        "note": (
            "the cases are deterministic solves of one model, so the split carries no "
            "inferential content: there is no error term, no replication and no p-value, "
            "and the shares describe the observed variation rather than estimating anything"
        ),
        "responses": {},
    }
    for response, label in RESPONSES.items():
        result = decompose(cases, response, factor_levels)
        payload["responses"][response] = {"label": label, **result}
        print(f"{label}:")
        print(f"  range {result['minimum']:.4f} to {result['maximum']:.4f}, "
              f"decomposition exact: {result['decomposition_is_exact']}")
        print(f"  main effects {result['main_effect_share_percent']:.2f}% of the variation, "
              f"interactions {result['interaction_share_percent']:.2f}%")
        for name, term in list(result["terms"].items())[:4]:
            print(f"    {term['share_percent']:>6.2f}%  {name}")
        print(f"  direction: {result['direction']}")

    if not all(item["decomposition_is_exact"] for item in payload["responses"].values()):
        raise SystemExit("the sums of squares do not add to the total; the design is not balanced")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
