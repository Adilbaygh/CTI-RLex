"""Application bootstrap, including automated visual-QA screenshot support."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from .data import ProjectPaths, project_version
from .theme import APP_STYLE
from .window import MainWindow


def launch(
    project_root: Path,
    benchmark: Path | None = None,
    screenshot: Path | None = None,
    page_index: int = 0,
    language: str | None = None,
) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("CTI-RLex Studio")
    app.setApplicationVersion(project_version(project_root))
    app.setOrganizationName("Leximin Research")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    paths = ProjectPaths.from_root(project_root)
    window = MainWindow(paths, initial_benchmark=benchmark, language=language)
    if 0 <= page_index < window.stack.count():
        window.stack.setCurrentIndex(page_index)
        window.nav_buttons[page_index].setChecked(True)
    window.show()

    if screenshot is not None:
        target = screenshot.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        def capture() -> None:
            window.grab().save(str(target), "PNG")
            app.quit()

        QTimer.singleShot(4500, capture)
    return app.exec()
