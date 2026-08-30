from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

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


def test_a_first_launch_opens_in_english(tmp_path) -> None:
    """A machine with nothing saved must open the interface in English.

    The check above covers the helper. The window has a second fallback of its own, read
    from QSettings, and that is the one a first-time reader meets -- a reviewer opening the
    application for the first time. It is also the one an author stops being able to see:
    the preference is stored per user profile, so once the interface has been switched on a
    machine, every later launch there keeps that choice.

    Isolating the settings is therefore the whole check, and the first version of it did
    not isolate anything. QSettings("organization", "application") reaches the native store
    whatever QSettings.setDefaultFormat() says, measured on Qt 6.11, so the window opened
    the author's real preference and this test reported it as a first launch. The window
    now names the format and scope, and the first assertion below is that the isolation
    actually happened. A check that silently measures the machine it runs on is worse than
    no check: it fails for the author for the wrong reason, and it passes on a fresh
    machine whatever the code does.

    Qt runs in its own process because building a QApplication inside the test process ends
    it with 0xC0000409 during Qt's own shutdown on Windows, which takes the whole suite with
    it. The child leaves through os._exit so that shutdown never runs; the property being
    checked is the same.
    """

    pytest.importorskip("PyQt6.QtCore")

    program = textwrap.dedent(
        """
        import os, sys
        from pathlib import Path
        from PyQt6.QtCore import QSettings
        from PyQt6.QtWidgets import QApplication

        # Read and write the preference inside the directory the parent passed, so this
        # neither inherits what the machine remembers nor changes it.
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, sys.argv[1]
        )

        from leximin.gui.data import ProjectPaths
        from leximin.gui.window import MainWindow

        # The application has to be held in a name. Left as a bare call it is collected
        # immediately and the window is built with none alive.
        application = QApplication([])
        window = MainWindow(ProjectPaths.from_root(Path(sys.argv[2])), auto_load=False)

        # The store comes first, so the parent can tell a first launch from this machine's
        # own saved preference before it reads anything else.
        print(window.settings.fileName())
        print(window.language)
        print(window.settings.value("ui_language"))
        sys.stdout.flush()
        os._exit(0)
        """
    )

    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), environment.get("PYTHONPATH", "")]
    ).strip(os.pathsep)

    finished = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path), str(ROOT)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=300,
    )
    reported = [line.strip() for line in finished.stdout.strip().splitlines()]
    assert len(reported) == 3, (
        f"the first-launch child reported {finished.stdout!r}\n{finished.stderr[-800:]}"
    )
    store, language, saved = reported

    assert Path(store).is_relative_to(tmp_path), (
        "this check did not isolate the settings, so what it measured is the saved "
        "preference of the machine it ran on rather than a first launch. The window "
        f"opened {store!r}, which is outside {tmp_path}."
    )
    assert [language, saved] == ["en", "en"], (
        f"a first launch came up in {language!r} and saved {saved!r}\n"
        f"{finished.stderr[-800:]}"
    )


def test_the_table_builders_import_without_qt() -> None:
    """The solver-only installation must still be able to run this suite.

    leximin.gui.data is ordinary Python: tables, ratios and the benchmark passport. Nothing
    in it needs Qt, and the README offers `pip install -e .` to readers who want the solver
    alone. This asserts that importing it does not reach for PyQt6, because while it did,
    the whole suite ended in a collection error instead of one skipped test -- and on a
    machine that has PyQt6 installed, as the author's does, that failure is invisible.

    PyQt6 is hidden with a meta path finder rather than uninstalled, so the check means the
    same thing whether or not the machine running it has Qt.
    """

    program = textwrap.dedent(
        """
        import importlib.abc, sys

        class Hidden(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "PyQt6" or fullname.startswith("PyQt6."):
                    raise ImportError("PyQt6 is hidden for this check")
                return None

        sys.meta_path.insert(0, Hidden())

        from leximin.gui.data import ProjectPaths, benchmark_counts
        from leximin.gui.i18n import normalize_language

        assert "PyQt6" not in sys.modules
        print("imported without Qt")
        """
    )

    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), environment.get("PYTHONPATH", "")]
    ).strip(os.pathsep)

    finished = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        env=environment,
        timeout=300,
    )
    assert "imported without Qt" in finished.stdout, (
        "the table builders could not be imported without PyQt6, so a solver-only "
        f"installation cannot run this suite\n{finished.stderr[-800:]}"
    )


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
