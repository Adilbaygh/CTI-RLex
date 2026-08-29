"""Produce results/scalability_cache_valley.json: how the solve grows with the instance.

Reviewer item 3.4: Supplementary Tables S13 and S14 cite this file, but no published script
wrote it. This script is that producer. It sweeps the number of fairness subjects and the
number of scenarios on the ten-claimant network while holding reaches, sources and
envelopes fixed, so that the quantity isolated is the one the progressive-filling sequence
actually grows with, and adds the three-claimant instance as a reference row.

The number of linear programs is counted from the level trace rather than instrumented in
the solver: each round costs one common-level program plus one feasibility test per still
free claimant, and three deterministic secondary stages follow the last round.

Run:  python scripts/scalability_experiment.py
Writes: results/scalability_cache_valley.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import median
from time import perf_counter

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from leximin.dag.experiments import (  # noqa: E402
    lp_dimensions,
    subset_claimants,
    subset_scenarios,
)
from leximin.dag.io import load_cti_benchmark  # noqa: E402
from leximin.dag.solver import solve_cti_rlex  # noqa: E402

OUTPUT = REPO / "results" / "scalability_cache_valley.json"
CACHE_VALLEY = REPO / "DATA" / "CacheValley_2025_Benchmark" / "benchmark.json"
LITTLE_BEAR = REPO / "DATA" / "LittleBearRiver_2025_Benchmark" / "benchmark.json"

CLAIMANT_COUNTS = (2, 4, 6, 8, 10)
SCENARIO_COUNTS = (1, 3, 5)
REPEATS = 3
SECONDARY_STAGES = 3


def linear_programs(solution) -> int:
    """One common-level program plus one feasibility test per free claimant, each round."""

    free = sum(len(level.blocked_claimants) for level in solution.leximin_levels)
    total = 0
    for level in solution.leximin_levels:
        total += 1 + free
        free -= len(level.blocked_claimants)
    return total + SECONDARY_STAGES


def measure(model, benchmark: str) -> dict:
    runtimes = []
    for _ in range(REPEATS):
        start = perf_counter()
        solution = solve_cti_rlex(model)
        runtimes.append(perf_counter() - start)
    dimensions = lp_dimensions(model)
    return {
        "claimants": len(model.claimants),
        "scenarios": len(model.scenarios),
        "variables": dimensions["variables"],
        "equality_constraints": dimensions["equality_constraints"],
        "inequality_constraints": dimensions["inequality_constraints"],
        "nonzeros": dimensions["nonzeros"],
        "levels": len(solution.leximin_levels),
        "lp_solves": linear_programs(solution),
        "runtime_s": median(runtimes),
        "min_rho": min(solution.guarantees.values()),
        "benchmark": benchmark,
        "edges": len(model.edges),
    }


def main() -> None:
    rows = []
    cache_valley = load_cti_benchmark(CACHE_VALLEY)
    for count in CLAIMANT_COUNTS:
        claimants = list(cache_valley.claimants)[:count]
        reduced = subset_claimants(cache_valley, claimants)
        for scenarios in SCENARIO_COUNTS:
            selected = (reduced.nominal_scenario,) + tuple(
                reduced.contingency_scenarios[: scenarios - 1]
            )
            rows.append(measure(subset_scenarios(reduced, selected), "cache_valley_v3"))
            row = rows[-1]
            print(f"cache_valley  K={row['claimants']:2d} S={row['scenarios']}  "
                  f"{row['variables']:5d} var  {row['levels']} levels  "
                  f"{row['lp_solves']:2d} LPs  {row['runtime_s']:.3f} s", flush=True)

    little_bear = load_cti_benchmark(LITTLE_BEAR)
    rows.append(measure(little_bear, "little_bear_v2"))
    row = rows[-1]
    print(f"little_bear   K={row['claimants']:2d} S={row['scenarios']}  "
          f"{row['variables']:5d} var  {row['levels']} levels  "
          f"{row['lp_solves']:2d} LPs  {row['runtime_s']:.3f} s")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote", OUTPUT)


if __name__ == "__main__":
    main()
