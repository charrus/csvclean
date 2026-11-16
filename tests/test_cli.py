"""Tests for CLI helpers."""

from __future__ import annotations

import pytest

from txnclassify.cli import resolve_answer

CLASSES = ["Grocery", "Transport"]


@pytest.mark.parametrize(
    ("answer", "suggestion", "expected"),
    [
        ("", "Grocery", "Grocery"),
        ("", "", None),
        ("s", "Grocery", None),
        ("S", "Grocery", None),
        ("2", "Grocery", "Transport"),
        ("3", "Grocery", "3"),
        ("transport", "", "Transport"),
        ("Cash Machine", "", "Cash Machine"),
        ("unknown", "Grocery", None),
        ("", "Unknown", None),
    ],
)
def test_resolve_answer(answer: str, suggestion: str, expected: str | None) -> None:
    """Enter accepts, numbers select, names match or create, s skips."""
    assert resolve_answer(answer, suggestion, CLASSES) == expected
