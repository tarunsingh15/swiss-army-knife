"""Unit tests for accuracy metric helpers."""

from __future__ import annotations

import pytest

from email_parser.metrics.accuracy_metrics import anls, field_prf, ned, teds


def test_teds_identical_tables() -> None:
    """Identical tables should score perfect tree-edit similarity."""
    rows = [["A", "B"], ["1", "2"]]
    assert teds(rows, rows) == 1.0


def test_ned_identical_strings() -> None:
    """Identical strings have zero normalized edit distance."""
    assert ned("hello", "hello") == 0.0


def test_anls_identical_strings() -> None:
    """Identical strings score 1.0 under ANLS."""
    assert anls("hello", "hello") == 1.0


def test_anls_very_different_strings() -> None:
    """Very different strings score 0 when NED exceeds tau."""
    assert anls("abc", "zzzzzzzz") == 0.0


def test_field_prf_identical_dicts() -> None:
    """Identical field dicts yield perfect F1."""
    fields = {"from": "a@example.com", "subject": "Hi"}
    result = field_prf(fields, fields)
    assert result["f1"] == 1.0


def test_ned_kitten_sitting() -> None:
    """Hand-computed NED for kitten vs sitting is 3/7."""
    assert ned("kitten", "sitting") == pytest.approx(3 / 7)


def test_anls_kitten_sitting_below_threshold() -> None:
    """Hand-computed NED is 3/7; with tau=0.5, ANLS returns 1 - NED."""
    assert ned("kitten", "sitting") == pytest.approx(3 / 7)
    assert anls("kitten", "sitting", tau=0.5) == pytest.approx(1 - 3 / 7)


def test_anls_zero_when_ned_exceeds_tau() -> None:
    """ANLS is 0 when NED is not strictly below tau."""
    assert anls("kitten", "sitting", tau=0.3) == 0.0
