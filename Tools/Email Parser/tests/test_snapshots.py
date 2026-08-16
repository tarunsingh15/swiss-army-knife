"""JSON snapshot tests for representative parsed documents."""

from __future__ import annotations

from pathlib import Path

import pytest

from email_parser.file_parsers.base import Blob
from email_parser.pipeline import process

pytest.importorskip("syrupy")

from syrupy.filters import props


def _root_document(documents):
    """Return the top-level parsed document."""
    roots = [doc for doc in documents if doc.parent_id is None]
    assert len(roots) == 1
    return roots[0]


def test_plain_email_snapshot(snapshot) -> None:
    """Plain synthetic email serializes to a stable JSON snapshot."""
    eml_path = Path(__file__).parent / "fixtures" / "synthetic" / "plain_no_attachment.eml"
    documents = process(Blob(raw=eml_path.read_bytes(), filename=eml_path.name))
    doc = _root_document(documents)
    assert doc.model_dump(mode="json") == snapshot(exclude=props("parsed_at", "parser_version"))
