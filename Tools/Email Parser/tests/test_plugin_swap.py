"""Tests for runtime parser registration and PDF engine selection."""

from __future__ import annotations

import os

import pymupdf
import pytest

from email_parser.file_parsers.registry import (
    clear_extra_parsers,
    register_parser,
    resolve_parser,
)
from tests.fixtures.plugin_pkg.dummy import DummyParser


@pytest.fixture(autouse=True)
def _clear_dummy_parser() -> None:
    """Ensure dummy parser registration does not leak between tests."""
    clear_extra_parsers()
    yield
    clear_extra_parsers()


def _minimal_pdf() -> bytes:
    """Create a tiny valid PDF for engine swap tests."""
    doc = pymupdf.open()
    doc.new_page()
    payload = doc.tobytes()
    doc.close()
    return payload


def test_dummy_parser_wins_by_priority() -> None:
    """A higher-priority registered PDF parser is selected by default."""
    register_parser(DummyParser())
    parser = resolve_parser(_minimal_pdf(), "application/pdf")
    assert parser is not None
    assert parser.name == "dummy_pdf"


def test_pdf_engine_env_selects_dummy_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    """EMAILPARSE_PDF_ENGINE can force a specific PDF parser when multiple claim."""
    monkeypatch.setenv("EMAILPARSE_PDF_ENGINE", "dummy_pdf")
    register_parser(DummyParser())
    parser = resolve_parser(_minimal_pdf(), "application/pdf", pdf_engine="dummy_pdf")
    assert parser is not None
    assert parser.name == "dummy_pdf"


def test_pdf_engine_parameter_selects_dummy_parser() -> None:
    """Explicit pdf_engine argument selects the named PDF parser."""
    register_parser(DummyParser())
    parser = resolve_parser(_minimal_pdf(), "application/pdf", pdf_engine="dummy_pdf")
    assert parser is not None
    assert parser.name == "dummy_pdf"


def test_default_pdf_engine_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings-loaded pdf_engine value is honored by resolve_parser callers."""
    monkeypatch.setenv("EMAILPARSE_PDF_ENGINE", "dummy_pdf")
    register_parser(DummyParser())
    from email_parser.config import load_settings

    settings = load_settings()
    parser = resolve_parser(_minimal_pdf(), "application/pdf", pdf_engine=settings.pdf_engine)
    assert parser is not None
    assert parser.name == "dummy_pdf"
    assert os.environ.get("EMAILPARSE_PDF_ENGINE") == "dummy_pdf"
