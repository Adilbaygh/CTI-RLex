from __future__ import annotations

from pathlib import Path

from leximin.dag import load_cti_benchmark, run_full_analysis, solve_cti_rlex
from leximin.gui.data import (
    ProjectPaths,
    allocation_table,
    base_result_tables,
    benchmark_counts,
    load_benchmark_document,
    validate_benchmark_document,
)
from leximin.gui.i18n import normalize_language


ROOT = Path(__file__).resolve().parents[1]
PATHS = ProjectPaths.from_root(ROOT)


def test_default_interface_language_is_english() -> None:
    assert normalize_language(None) == "en"


def test_project_paths_require_no_generated_result_folder() -> None:
    assert PATHS.default_benchmark.exists()
    assert set(PATHS.__dataclass_fields__) == {"root", "default_benchmark"}


def test_benchmark_counts_and_dynamic_result_tables() -> None:
    raw = load_benchmark_document(PATHS.default_benchmark)
    counts = benchmark_counts(raw)
    solution = solve_cti_rlex(load_cti_benchmark(PATHS.default_benchmark)).to_dict()

    assert counts["claimants"] == 3
    assert counts["sources"] == 4
    assert counts["scenarios"] == 5
    assert counts["periods"] == 5
    # The language is passed explicitly on both sides, so these row counts stay valid
    # whichever language the interface defaults to.
    uzbek_tables = base_result_tables(solution, "uz")
    assert len(uzbek_tables["Ойлик нисбатлар"][1]) == 75
    assert len(uzbek_tables["Тармоқ оқимлари"][1]) == 475
    assert len(allocation_table(raw, solution, "uz")[1]) == 3

    english_tables = base_result_tables(solution, "en")
    assert len(english_tables["Period ratios"][1]) == 75
    assert len(english_tables["Network flows"][1]) == 475
    assert allocation_table(raw, solution, "en")[0][1] == "Name"

    # English is the interface default, so calling without a language must match "en".
    assert set(base_result_tables(solution)) == set(english_tables)


def test_benchmark_template_validation_reports_missing_fields() -> None:
    try:
        validate_benchmark_document({"benchmark_id": "incomplete"})
    except ValueError as exc:
        assert "claimants" in str(exc)
        assert "sources" in str(exc)
    else:
        raise AssertionError("Incomplete benchmark was accepted")


def test_extended_analysis_uses_benchmark_payload_without_working_files() -> None:
    raw = load_benchmark_document(PATHS.default_benchmark)
    raw["sensitivity_cases"] = []
    analysis = run_full_analysis(
        load_cti_benchmark(PATHS.default_benchmark),
        raw,
        runtime_repeats=1,
    )

    assert analysis["analysis_schema"] == "cti-rlex-analysis-v1"
    assert len(analysis["method_comparison"]) == 5
    assert len(analysis["source_ablation"]) == 4
    assert len(analysis["recourse_frontier"]) == 5
    assert len(analysis["representation_tests"]) == 3
    assert len(analysis["scalability"]) == 3
