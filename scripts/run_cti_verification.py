from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from leximin.dag import load_cti_benchmark, solve_cti_rlex, split_terminal_record


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CTI-RLex scientific verification checks.")
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--terminal-id",
        default="terminal_company_130_1",
        help="Terminal record used for representation tests.",
    )
    args = parser.parse_args()

    model = load_cti_benchmark(args.benchmark)
    base = solve_cti_rlex(model)

    representation_tests: list[dict[str, object]] = []
    for copies in (2, 4, 8):
        split = solve_cti_rlex(split_terminal_record(model, args.terminal_id, copies))
        error = max(
            abs(base.guarantees[claimant] - split.guarantees[claimant])
            for claimant in model.claimants
        )
        representation_tests.append(
            {
                "terminal_id": args.terminal_id,
                "copies": copies,
                "guarantee_infinity_norm_error": error,
                "pass_at_1e-8": error <= 1e-8,
            }
        )

    frontier: list[dict[str, object]] = []
    for scale in (0.0, 0.25, 0.5, 1.0, 2.0):
        scaled = replace(
            model,
            recourse_budget={
                scenario: model.recourse_budget[scenario] * scale
                for scenario in model.scenarios
            },
        )
        solution = solve_cti_rlex(scaled)
        frontier.append(
            {
                "budget_scale": scale,
                "first_leximin_level": solution.first_leximin_level,
                "guarantees": dict(solution.guarantees),
                "normalized_recourse_effort": solution.normalized_recourse_effort,
            }
        )
    monotone = all(
        frontier[index + 1]["first_leximin_level"] + 1e-8
        >= frontier[index]["first_leximin_level"]
        for index in range(len(frontier) - 1)
    )

    payload = {
        "benchmark_id": model.benchmark_id,
        "base_guarantees": dict(base.guarantees),
        "base_residuals": dict(base.residuals),
        "representation_tests": representation_tests,
        "recourse_frontier": frontier,
        "recourse_frontier_nondecreasing": monotone,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
