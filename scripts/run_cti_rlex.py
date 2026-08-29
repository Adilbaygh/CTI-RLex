from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Run from a clone without installing the package: put src/ on the import path first.
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from leximin.dag import load_cti_benchmark, solve_cti_rlex  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Solve a CTI-RLex benchmark.")
    parser.add_argument("benchmark", type=Path, help="Path to canonical benchmark.json")
    parser.add_argument("--output", type=Path, required=True, help="JSON result path")
    args = parser.parse_args()

    model = load_cti_benchmark(args.benchmark)
    solution = solve_cti_rlex(model)
    payload = solution.to_dict()
    payload["solver"] = {
        "method": "SciPy HiGHS linear programming with progressive filling",
        "fairness_unit": "claimant aggregate across terminal records",
        "guarantee_scope": "every positive-demand period and every scenario",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["guarantees"], sort_keys=True))
    print(f"results={args.output.resolve()}")


if __name__ == "__main__":
    main()
