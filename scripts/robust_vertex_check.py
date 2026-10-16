"""Check, on both instances, that the scenario guarantees of CTI-RLex hold on the convex hull of
its scenarios (Reviewer 1, point 1.2).

Reviewer 1 asked for robust optimization over continuous uncertainty sets -- boxes, polytopes,
ellipsoids -- in place of a few deterministic scenarios. The revised article answers with a
proposition: in CTI-RLex a scenario enters only through right-hand sides -- reach capacities,
source and seasonal limits, shared envelopes, the recourse budget -- while efficiencies and
demands are the same in every scenario. With the nominal plan fixed, the convex combination of
the scenarios' recourse plans is then a recourse plan for the convex combination of their
parameters: every constraint is linear, and the effort of the combination is at most the
combination of the efforts, which is at most the combined budget. A guarantee that holds in the
scenarios therefore holds on their convex hull, a polyhedral uncertainty set, and the finite
scenario model is its exact robust counterpart.

This script tests that statement numerically, with the published nominal plan held fixed
(scripts/fixed_plan_recourse.py). For each instance it draws 1000 weight vectors from a flat
Dirichlet distribution over all of its scenarios, the nominal one included, combines every
right-hand side and the recourse budget with those weights, and finds the largest share of the
published guarantee vector that the combined scenario delivers to every claimant together. The
proposition says that share is 1. As controls it computes the same share at each scenario itself,
where it must be 1, and at a point outside the hull for each contingency scenario -- its
capacities and limits times 0.9, its budget unchanged -- where nothing guarantees it.

Before the instances are solved the script checks the premise: that no reach efficiency differs
between scenarios. Efficiencies multiply flows, so uncertainty in them is not a right-hand side
and the proposition does not cover it.

Expectations were written before the first run (requirements/hypotheses.md, H-1.2 and H-1.2b).

Run:  python scripts/robust_vertex_check.py
Writes: results/robust_vertex_check.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import fixed_plan_recourse as fixed  # noqa: E402
from leximin.dag import load_cti_benchmark  # noqa: E402

BENCHMARKS = {
    "little_bear_v2": REPO / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json",
    "cache_valley_v4": REPO / "DATA" / "CacheValley_2025_Benchmark" / "benchmark.json",
}
OUTPUT = REPO / "results" / "robust_vertex_check.json"
SAMPLES = 1000
SEED = 20261012
OUTSIDE = 0.9        # capacities and limits of the control points outside the hull
HOLDS = 1e-6         # a share within this of 1 counts as the full guarantee


def efficiencies_vary(model) -> list:
    nominal = model.nominal_scenario
    return sorted({(p, e) for (s, p, e), number in model.edge_efficiency.items()
                   if number != model.edge_efficiency[nominal, p, e]})


def share(model, plan_rows, guarantees, label: str, parameters: dict) -> tuple[float, float]:
    """The share of the guarantee vector the scenario delivers, and the effort beyond its budget."""

    instance, _, overrun = fixed.operate(model, label, parameters, plan_rows)
    return fixed.common_level(instance, label, plan_rows, guarantees), overrun


def scaled(parameters: dict, factor: float) -> dict:
    out = {}
    for name, entry in parameters.items():
        if name == "recourse_budget":
            out[name] = entry
        else:
            out[name] = {key: factor * number for key, number in entry.items()}
    return out


def main() -> None:
    started = time.perf_counter()
    report = {"samples_per_instance": SAMPLES, "seed": SEED, "dirichlet_concentration": 1.0,
              "outside_factor": OUTSIDE, "holds_within": HOLDS, "instances": {}}
    for name, path in BENCHMARKS.items():
        began = time.perf_counter()
        model = load_cti_benchmark(path)
        varying = efficiencies_vary(model)
        if varying:
            raise SystemExit(f"{name}: reach efficiencies differ between scenarios at {varying[:5]}; "
                             "the proposition does not cover that case")
        solution, plan_rows = fixed.published_plan(model)
        guarantees = dict(solution.guarantees)
        vertices = {scenario: fixed.scenario_parameters(model, scenario) for scenario in model.scenarios}

        at_vertices, vertex_overruns = {}, {}
        for scenario, parameters in vertices.items():
            at_vertices[scenario], vertex_overruns[scenario] = share(model, plan_rows, guarantees, "vertex", parameters)
        rng = np.random.default_rng(SEED)
        weights = rng.dirichlet(np.ones(len(model.scenarios)), size=SAMPLES)
        shares, overruns = [], []
        for row in weights:
            combined = fixed.combine([(float(w), vertices[s]) for w, s in zip(row, model.scenarios)])
            level, overrun = share(model, plan_rows, guarantees, "combination", combined)
            shares.append(level)
            overruns.append(overrun)
        shares, overruns = np.array(shares), np.array(overruns)
        worst = int(np.argmin(shares))
        outside, outside_overruns = {}, {}
        for scenario in model.contingency_scenarios:
            outside[scenario], outside_overruns[scenario] = share(
                model, plan_rows, guarantees, "outside", scaled(vertices[scenario], OUTSIDE))
        report["instances"][name] = {
            "benchmark_id": model.benchmark_id,
            "scenarios": list(model.scenarios),
            "recourse_budgets": {s: model.recourse_budget[s] for s in model.contingency_scenarios},
            "published_guarantees": guarantees,
            "share_at_each_scenario": at_vertices,
            "effort_beyond_budget_at_each_scenario": vertex_overruns,
            "every_scenario_delivers_the_full_guarantee": all(v >= 1 - HOLDS for v in at_vertices.values()),
            "combinations": {
                "count": SAMPLES,
                "smallest_share": float(shares.min()),
                "largest_shortfall": float(max(0.0, 1.0 - shares.min())),
                "below_full_guarantee": int((shares < 1 - HOLDS).sum()),
                "largest_effort_beyond_budget": float(overruns.max()),
                "weights_of_the_smallest_share": dict(zip(model.scenarios, map(float, weights[worst]))),
            },
            "every_combination_delivers_the_full_guarantee": bool((shares >= 1 - HOLDS).all() and overruns.max() <= 1e-9),
            "share_outside_the_hull": outside,
            "effort_beyond_budget_outside_the_hull": outside_overruns,
            "seconds": round(time.perf_counter() - began, 1),
        }
        item = report["instances"][name]
        print(f"== {name}: {len(model.scenarios)} scenarios, budgets {item['recourse_budgets']}")
        print(f"   share of the guarantee at each scenario: "
              f"{ {s: round(v, 9) for s, v in at_vertices.items()} }")
        print(f"   {SAMPLES} convex combinations: smallest share {shares.min():.9f}, "
              f"{item['combinations']['below_full_guarantee']} below 1 - {HOLDS:g}")
        print(f"   largest effort beyond the budget: at the scenarios {max(vertex_overruns.values()):.1e}, "
              f"in the combinations {overruns.max():.1e}")
        print(f"   outside the hull (limits x {OUTSIDE}): share { {s: round(v, 4) for s, v in outside.items()} }, "
              f"effort beyond the budget { {s: round(v, 4) for s, v in outside_overruns.items()} }")
    report["seconds"] = round(time.perf_counter() - started, 1)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(REPO)} in {report['seconds']} s")


if __name__ == "__main__":
    main()
