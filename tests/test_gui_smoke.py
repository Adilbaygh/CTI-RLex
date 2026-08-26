from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from leximin.gui.data import ProjectPaths  # noqa: E402
from leximin.gui.window import MainWindow  # noqa: E402
from leximin.dag import load_cti_benchmark, run_full_analysis  # noqa: E402
from leximin.gui.data import load_benchmark_document  # noqa: E402


def test_main_window_loads_canonical_benchmark() -> None:
    app = QApplication.instance() or QApplication([])
    root = Path(__file__).resolve().parents[1]
    paths = ProjectPaths.from_root(root)
    window = MainWindow(paths, auto_load=False)
    window.load_benchmark(paths.default_benchmark)
    deadline = time.monotonic() + 30
    while window.solve_worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()

    assert window.stack.count() == 11
    assert len(window.nav_buttons) == 11
    assert window.base_result is not None
    assert window.raw_tabs.count() == 9
    assert all(gate._stack.currentWidget() is gate.content for gate in window.base_gates)
    assert all(gate._stack.currentWidget() is gate.placeholder for gate in window.full_gates)
    assert {"network", "guarantees", "service"}.issubset(window.chart_paths)

    solution = window.base_result
    window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
    app.processEvents()
    assert window.base_result is solution
    assert all(gate._stack.currentWidget() is gate.content for gate in window.base_gates)
    assert "Period ratios" in [
        window.raw_tabs.tabText(index) for index in range(window.raw_tabs.count())
    ]
    window.language_combo.setCurrentIndex(window.language_combo.findData("uz"))
    app.processEvents()
    window.close()


def test_main_window_accepts_library_extended_analysis() -> None:
    app = QApplication.instance() or QApplication([])
    root = Path(__file__).resolve().parents[1]
    paths = ProjectPaths.from_root(root)
    raw = load_benchmark_document(paths.default_benchmark)
    raw["sensitivity_cases"] = []
    analysis = run_full_analysis(
        load_cti_benchmark(paths.default_benchmark), raw, runtime_repeats=1
    )
    window = MainWindow(paths, auto_load=False)
    window.current_benchmark = paths.default_benchmark
    window.benchmark_raw = load_benchmark_document(paths.default_benchmark)
    window._analysis_completed(analysis)
    app.processEvents()

    assert window.full_analysis is analysis
    assert window.method_panel.table.model().rowCount() == 5
    assert window.ablation_panel.table.model().rowCount() == 4
    assert all(gate._stack.currentWidget() is gate.content for gate in window.full_gates)
    assert "methods" in window.chart_paths
    assert "scalability" in window.chart_paths
    window.close()


def test_interface_language_switches_without_restart() -> None:
    app = QApplication.instance() or QApplication([])
    root = Path(__file__).resolve().parents[1]
    window = MainWindow(ProjectPaths.from_root(root), auto_load=False)

    english = window.language_combo.findData("en")
    window.language_combo.setCurrentIndex(english)
    app.processEvents()
    assert window.language == "en"
    assert window.open_action.text() == "Open benchmark…"
    assert window.nav_buttons[0].text() == "01   Overview"
    assert window.language_combo.currentText() == "ENG"

    uzbek = window.language_combo.findData("uz")
    window.language_combo.setCurrentIndex(uzbek)
    app.processEvents()
    assert window.language == "uz"
    assert window.open_action.text() == "Benchmarkни очиш…"
    assert window.nav_buttons[0].text() == "01   Умумий кўриниш"
    assert window.language_combo.currentText() == "ЎЗБ"
    window.close()
