"""What the package promises about itself.

Two small things that go wrong quietly. A version declared in two files drifts apart the
first time only one of them is bumped -- pyproject.toml said 0.3.0 while the package said
0.2.0 -- and it is the package attribute a citation tool reads. And a package that
re-exports code the article does not use invites a reviewer to ask which implementation
produced the results; the seven single-source modules that prompted that question were
removed on 31 August 2026, and this keeps them from coming back unnoticed.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import leximin

ROOT = Path(__file__).resolve().parents[1]

# The names the experiment scripts and the tests import from the package root.
CTI_API = {
    "CTIBenchmark",
    "CTIRLexSolution",
    "ClaimantTerminal",
    "ControlAsset",
    "DAGEdge",
    "DAGSource",
    "LeximinLevel",
    "OptimizationError",
    "load_cti_benchmark",
    "parse_cti_payload",
    "representation_invariance_error",
    "solve_cti_rlex",
    "split_terminal_record",
    "validate_cti_benchmark",
}


def test_the_package_and_the_project_declare_one_version() -> None:
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert leximin.__version__ == declared["project"]["version"], (
        "leximin.__version__ and pyproject.toml disagree; a citation tool reads the first "
        "and an installer reads the second"
    )


def test_the_package_exports_the_cti_rlex_api_and_nothing_else() -> None:
    assert set(leximin.__all__) == CTI_API


def test_the_single_source_solver_is_not_back() -> None:
    package = Path(leximin.__file__).parent
    removed = [
        "domain.py", "io.py", "operators.py", "stage1.py",
        "lexicographic.py", "robust.py", "verification.py",
    ]
    present = [name for name in removed if (package / name).exists()]
    assert not present, (
        f"{present} implement a different formulation from the one the article reports "
        "and nothing in this repository imports them"
    )
