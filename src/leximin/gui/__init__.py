"""Standalone PyQt6 interface for CTI-RLex benchmark analysis."""

from __future__ import annotations

from typing import Any

__all__ = ["launch"]


def __getattr__(name: str) -> Any:
    """Import the Qt application only when something actually asks for it.

    leximin.gui.data builds the tables and the benchmark passport and imports nothing
    beyond the standard library and .i18n, so a reader who installed the solver alone can
    use it and test it. While this module imported .app eagerly, importing leximin.gui.data
    reached PyQt6 through it, and pytest ended with a collection error -- no tests at all,
    rather than one skipped test -- on exactly the installation the README recommends for
    readers who do not want the desktop application.
    """

    if name == "launch":
        from .app import launch

        return launch
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
