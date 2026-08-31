"""Leximin -- claimant-level robust leximin allocation on lossy irrigation networks.

The package is the CTI-RLex model of the accompanying article. ``leximin.dag`` carries the
benchmark loader and validator, the linear-programming model, the leximin solver, the
comparators and the analysis layers; ``leximin.gui`` carries the desktop benchmark
analyzer and imports Qt only when something asks it to, so the solver-only installation
can import and test everything else.

The names below are the ones the experiment scripts and the tests use. Anything deeper --
the LP builder, the ablation and scaling helpers, the audit -- is reached through
``leximin.dag`` directly.
"""

from __future__ import annotations

from .dag import (
    CTIBenchmark,
    CTIRLexSolution,
    ClaimantTerminal,
    ControlAsset,
    DAGEdge,
    DAGSource,
    LeximinLevel,
    OptimizationError,
    load_cti_benchmark,
    parse_cti_payload,
    representation_invariance_error,
    solve_cti_rlex,
    split_terminal_record,
    validate_cti_benchmark,
)

__all__ = [
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
]

# Kept equal to the version in pyproject.toml by tests/test_package_metadata.py.
__version__ = "0.3.0"
