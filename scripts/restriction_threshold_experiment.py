"""How much more severe would the declared restriction scenario have to be before it binds?

In the published three-claimant benchmark the Hyrum service ratios are the same in all five
scenarios, including the canal restriction named after that claimant, so a reader cannot
tell whether the declared scenario set exercises the model for that claimant at all. The
question is how far the scenario is from the level at which it would bind, and answering it
needs a one-parameter family of scenarios that actually contains the declared one.

That is the point this script turns on. The restriction is not a single retained fraction
but a vector: the scenario retains 0.35 of the nominal head-reach capacity, 0.30 and 0.25 of
the two local source envelopes, and 0.18 of the subsystem's shared envelope, which is the
tightest of the four. A sweep moving one common fraction over some of those quantities while
holding the others at their declared values would pass through the declared scenario at no
point, and the threshold it reported would belong to a family the benchmark does not
contain.

The severity is therefore a multiplier on the declared derating vector itself. Writing d_i
for the factor the scenario declares on quantity i, severity t retains

    min(1, t * d_i)  of the nominal value of quantity i,

so t = 1 is the declared scenario exactly -- asserted here against the published solution,
not assumed -- t < 1 intensifies every declared derating in proportion, and the family is a
ray through the point the benchmark actually contains.

Two nested families are reported, because they answer different questions:

    restriction     the quantities of the restricted subsystem: its shared envelope, its
                    sources and the head reach. The shortage background on the other
                    subsystem stays at its declared level, so the answer is about the
                    restriction rather than about the shortage it sits in
    whole scenario  every quantity the scenario derates, background included

Run:  python scripts/restriction_threshold_experiment.py
Writes: results/restriction_threshold.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from leximin.dag.io import load_cti_benchmark  # noqa: E402
from leximin.dag.solver import solve_cti_rlex  # noqa: E402

BENCHMARK = REPO / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json"
OUTPUT = REPO / "results" / "restriction_threshold.json"

SCENARIO = "hyrum_canal_restriction_under_shortage"

# Descending, so the first row that moves the guarantee vector is the threshold. The ray
# starts above the declared scenario as well, which shows what slack the declared point has
# on the mild side.
SEVERITIES = (
    2.0, 1.5, 1.25, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4,
    0.3, 0.25, 0.2, 0.15, 0.125, 0.1, 0.075, 0.05,
)
TOLERANCE = 1e-7
DECLARED = 1.0
# A grid locates the threshold only to the width of its own step, which would leave the
# reported factor an artefact of where the steps happen to fall. The bracket the grid
# returns is therefore bisected to this width, and the width is reported with the answer.
THRESHOLD_RESOLUTION = 0.001


def declared_factors(model) -> dict[str, dict[Any, float]]:
    """The derating the scenario declares, read from the benchmark rather than assumed.

    Every quantity is expressed as a fraction of its own nominal value, so the vector
    tracks the released instance: if the benchmark ever derates a different asset, the
    sweep follows it instead of sweeping an asset that is no longer there.
    """

    nominal = model.nominal_scenario

    def ratios(mapping, identity, nominal_key) -> dict[Any, float]:
        found: dict[Any, float] = {}
        for key, value in mapping.items():
            if key[0] != SCENARIO:
                continue
            base = mapping.get(nominal_key(key))
            if base is None or base <= 0.0:
                continue
            factor = value / base
            if factor < 1.0 - 1e-12:
                found[identity(key)] = factor
        return found

    return {
        "edge": ratios(model.edge_capacity, lambda k: k[2], lambda k: (nominal, k[1], k[2])),
        "source_period": ratios(
            model.source_limit, lambda k: k[2], lambda k: (nominal, k[1], k[2])
        ),
        "source_seasonal": ratios(
            model.source_seasonal_limit, lambda k: k[1], lambda k: (nominal, k[1])
        ),
        "group": ratios(
            model.shared_source_limit, lambda k: k[2], lambda k: (nominal, k[1], k[2])
        ),
    }


def restriction_scope(model, factors: dict[str, dict[Any, float]]) -> set[str]:
    """The groups holding a derated source: the subsystem the restriction acts on.

    Deriving the scope from source membership rather than naming the group keeps both
    families meaningful if the instance changes; the background is then whatever the
    scenario derates outside that subsystem.
    """

    restricted = set(factors["source_period"]) | set(factors["source_seasonal"])
    return {
        group
        for group, members in model.group_members.items()
        if any(source in restricted for source, _beta in members)
    }


def intensified(model, factors: dict[str, dict[Any, float]], severity: float,
                scope: set[str] | None):
    """The scenario with every declared derating in ``scope`` scaled by ``severity``.

    A factor can never exceed one: a scenario retaining more than the nominal value would
    not be a derating at all, so the mild end of the ray saturates at nominal rather than
    inventing capacity the benchmark does not have. Only the shared envelopes are scoped;
    the reach and the sources of the restricted subsystem belong to the restriction under
    either family.
    """

    nominal = model.nominal_scenario

    def scaled(mapping, nominal_key, factor_of, in_scope) -> dict:
        updated = dict(mapping)
        for key in list(mapping):
            if key[0] != SCENARIO:
                continue
            factor = factor_of(key)
            if factor is None or not in_scope(key):
                continue
            base = mapping.get(nominal_key(key))
            if base is None:
                continue
            updated[key] = base * min(1.0, severity * factor)
        return updated

    def group_in_scope(identifier: str) -> bool:
        return scope is None or identifier in scope

    return replace(
        model,
        benchmark_id=f"{model.benchmark_id}__{SCENARIO}_t{severity:g}",
        edge_capacity=scaled(
            model.edge_capacity,
            lambda k: (nominal, k[1], k[2]),
            lambda k: factors["edge"].get(k[2]),
            lambda k: True,
        ),
        source_limit=scaled(
            model.source_limit,
            lambda k: (nominal, k[1], k[2]),
            lambda k: factors["source_period"].get(k[2]),
            lambda k: True,
        ),
        source_seasonal_limit=scaled(
            model.source_seasonal_limit,
            lambda k: (nominal, k[1]),
            lambda k: factors["source_seasonal"].get(k[1]),
            lambda k: True,
        ),
        shared_source_limit=scaled(
            model.shared_source_limit,
            lambda k: (nominal, k[1], k[2]),
            lambda k: factors["group"].get(k[2]),
            lambda k: group_in_scope(k[2]),
        ),
    )


def binding_scenarios(solution, model) -> dict[str, list[str]]:
    """Scenarios in which a claimant sits on its own guarantee."""

    out: dict[str, list[str]] = {claimant: [] for claimant in model.claimants}
    for (scenario, _period, claimant), ratio in solution.period_service_ratio.items():
        if abs(ratio - solution.guarantees[claimant]) <= 1e-6 and scenario not in out[claimant]:
            out[claimant].append(scenario)
    return {key: sorted(value) for key, value in out.items()}


def binds(model, factors, scope, reference: dict[str, float], severity: float) -> bool:
    """Whether any claimant's guarantee falls below the declared scenario at this severity."""

    solution = solve_cti_rlex(intensified(model, factors, severity, scope))
    return any(
        value < reference[claimant] - TOLERANCE
        for claimant, value in solution.guarantees.items()
    )


def bisect(model, factors, scope, reference, binding: float, slack: float) -> tuple[float, float]:
    """Narrow the bracket between a severity that binds and the next one that does not.

    Tightening every declared derating in proportion can only lower a guarantee, so the
    predicate is monotone in the severity and bisection is sound; the grid asserts that
    monotonicity rather than assuming it.
    """

    while slack - binding > THRESHOLD_RESOLUTION:
        middle = (binding + slack) / 2.0
        if binds(model, factors, scope, reference, middle):
            binding = middle
        else:
            slack = middle
    return binding, slack


def sweep(model, factors, scope, reference: dict[str, float]) -> dict[str, Any]:
    rows, threshold = [], None
    for severity in SEVERITIES:
        solution = solve_cti_rlex(intensified(model, factors, severity, scope))
        guarantees = dict(solution.guarantees)
        reduced = sorted(
            claimant for claimant, value in guarantees.items()
            if value < reference[claimant] - TOLERANCE
        )
        rows.append({
            "severity": severity,
            "retained_of_nominal": {
                name: {
                    str(key): round(min(1.0, severity * factor), 6)
                    for key, factor in sorted(group.items())
                    if name != "group" or scope is None or key in scope
                }
                for name, group in factors.items()
            },
            "guarantees": guarantees,
            "min_guarantee": min(guarantees.values()),
            "claimants_reduced": reduced,
            "binding_scenarios": binding_scenarios(solution, model),
            "nominal_af": solution.nominal_beneficial_delivery,
            "max_lp_residual": max(solution.residuals.values(), default=0.0),
        })
        if reduced and threshold is None:
            threshold = severity

    # A guarantee can only fall as the derating tightens; if it does not, the predicate is
    # not monotone and the bisection below would return a bracket that means nothing.
    minima = [row["min_guarantee"] for row in rows]
    monotone = all(a >= b - TOLERANCE for a, b in zip(minima, minima[1:]))

    bracket = None
    if threshold is not None and monotone:
        index = [row["severity"] for row in rows].index(threshold)
        if index == 0:
            bracket = [threshold, threshold]
        else:
            bracket = list(bisect(model, factors, scope, reference,
                                  threshold, rows[index - 1]["severity"]))
    return {
        "severities": list(SEVERITIES),
        "guarantee_is_monotone_in_the_severity": monotone,
        "first_binding_severity_on_the_grid": threshold,
        "threshold_bracket": bracket,
        "threshold_resolution": THRESHOLD_RESOLUTION,
        "declared_is_weaker_by_a_factor_of": (
            round(DECLARED / bracket[1], 2) if bracket else None
        ),
        "rows": rows,
    }


def main() -> None:
    model = load_cti_benchmark(BENCHMARK)
    base = solve_cti_rlex(model)
    reference = dict(base.guarantees)
    factors = declared_factors(model)
    scope = restriction_scope(model, factors)

    print(f"declared derating of {SCENARIO}")
    for name, group in factors.items():
        for key, factor in sorted(group.items()):
            print(f"  {name:<16} {key:<12} {factor:.3f}")
    print(f"  restricted subsystem: {sorted(scope)}")

    # The ray has to pass through the point the benchmark contains, or the threshold it
    # reports belongs to a family the instance does not have. This is that check.
    at_declared = solve_cti_rlex(intensified(model, factors, DECLARED, None))
    drift = max(
        abs(at_declared.guarantees[claimant] - reference[claimant]) for claimant in reference
    )
    print(f"  severity 1 reproduces the published solution to {drift:.2e}")
    if drift > TOLERANCE:
        raise SystemExit(
            "severity 1 does not reproduce the declared scenario, so the sweep does not "
            "pass through the benchmark it claims to sweep"
        )

    families: dict[str, Any] = {}
    for name, selected in (("restriction", scope), ("whole_scenario", None)):
        print(f"{name}:")
        result = sweep(model, factors, selected, reference)
        result["scope"] = sorted(scope) if selected is not None else "every derated quantity"
        families[name] = result
        bracket = result["threshold_bracket"]
        print(f"  monotone in the severity: {result['guarantee_is_monotone_in_the_severity']}")
        print(f"  threshold between t={bracket[0]:.3f} and t={bracket[1]:.3f}, so the declared "
              f"scenario is weaker by a factor of {result['declared_is_weaker_by_a_factor_of']}")
        for row in result["rows"]:
            if row["claimants_reduced"] or row["severity"] in (DECLARED,):
                print(f"    t={row['severity']:<6g} min rho {row['min_guarantee']:.6f}  "
                      f"reduced {','.join(row['claimants_reduced']) or '-'}")

    report = {
        "scenario": SCENARIO,
        "parameterization": (
            "severity t retains min(1, t*d_i) of the nominal value of every derated "
            "quantity i, where d_i is the factor the scenario declares; t = 1 is the "
            "declared scenario"
        ),
        "declared_factors": {
            name: {str(key): value for key, value in sorted(group.items())}
            for name, group in factors.items()
        },
        "restricted_subsystem": sorted(scope),
        "severity_one_reproduces_the_published_solution": True,
        "severity_one_max_guarantee_drift": drift,
        "reference_guarantees": reference,
        "families": families,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
