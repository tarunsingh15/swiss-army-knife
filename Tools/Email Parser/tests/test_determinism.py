"""Determinism tests for repeated parses of identical bytes."""

from __future__ import annotations

from pathlib import Path

from email_parser.file_parsers.base import Blob
from email_parser.pipeline import process


def _dump_without_parsed_at(document) -> dict:
    """Return model_dump excluding provenance.parsed_at when present."""
    dumped = document.model_dump(mode="json")
    provenance = dumped.get("provenance")
    if isinstance(provenance, dict) and "parsed_at" in provenance:
        dumped = {
            **dumped,
            "provenance": {k: value for k, value in provenance.items() if k != "parsed_at"},
        }
    return dumped


def test_plain_email_parse_is_deterministic() -> None:
    """Parsing the same .eml twice yields identical canonical documents."""
    eml_path = Path(__file__).parent / "fixtures" / "synthetic" / "plain_no_attachment.eml"
    raw = eml_path.read_bytes()
    blob = Blob(raw=raw, filename=eml_path.name)

    first_run = process(blob)
    second_run = process(blob)

    assert len(first_run) == len(second_run)
    first_dumped = [_dump_without_parsed_at(doc) for doc in first_run]
    second_dumped = [_dump_without_parsed_at(doc) for doc in second_run]
    assert first_dumped == second_dumped
