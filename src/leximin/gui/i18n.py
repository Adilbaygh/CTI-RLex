"""Small, dependency-free internationalization helpers for the desktop GUI."""

from __future__ import annotations


SUPPORTED_LANGUAGES = ("uz", "en")
DEFAULT_LANGUAGE = "en"


def normalize_language(value: object) -> str:
    """Return a supported two-letter GUI language code."""

    language = str(value or "").strip().lower()
    return language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def pick(language: str, uzbek: str, english: str) -> str:
    """Select one of two complete user-facing translations."""

    return english if normalize_language(language) == "en" else uzbek
