"""Leximin — fair water allocation on lossy irrigation trees and DAGs.

Core solver copied and adapted from the appliedmath-lexflow project.
Stage 1 (max-min guarantee lambda*), Stage 2 (weighted seasonal satisfaction S*),
Stage 3 (temporal service-ratio smoothness Omega), plus price-of-fairness and
exact progressive-filling leximin.
"""

from .domain import Benchmark, Edge, User
from .io import load_benchmark, validate_benchmark
from .operators import build_graph, build_operator_exact
from .stage1 import (
    Stage1ClosedForm,
    Stage1LP,
    solve_stage1_closed_form,
    solve_stage1_lp,
)
from .lexicographic import (
    StageSolution,
    ThreeStageSolution,
    solve_three_stage,
)
from .robust import (
    LeximinSolution,
    PriceOfFairness,
    VariationBounds,
    price_of_fairness,
    solve_leximin,
    stage2_variation_bounds,
)
from .verification import (
    OperatorVerification,
    maximum_physical_violation,
    verify_operator_exact,
)
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
    "Benchmark",
    "Edge",
    "User",
    "load_benchmark",
    "validate_benchmark",
    "build_graph",
    "build_operator_exact",
    "Stage1ClosedForm",
    "Stage1LP",
    "solve_stage1_closed_form",
    "solve_stage1_lp",
    "StageSolution",
    "ThreeStageSolution",
    "solve_three_stage",
    "LeximinSolution",
    "PriceOfFairness",
    "VariationBounds",
    "price_of_fairness",
    "solve_leximin",
    "stage2_variation_bounds",
    "OperatorVerification",
    "maximum_physical_violation",
    "verify_operator_exact",
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

__version__ = "0.2.0"
