"""Tests for parser registry dispatch."""

from __future__ import annotations

import pymupdf

from email_parser.file_parsers.base import Blob, ParseContext
from email_parser.file_parsers.registry import (
    load_parsers,
    resolve_parser,
    sniff_mime,
    unsupported_document,
)
from email_parser.models import ParseStatus


def _minimal_pdf() -> bytes:
    """Create a tiny valid PDF for magic-byte routing tests."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "registry test")
    payload = doc.tobytes()
    doc.close()
    return payload


def _sample_email() -> bytes:
    """Return minimal RFC 822 bytes with a From header."""
    return (
        b"From: sender@example.com\r\n"
        b"To: recipient@example.com\r\n"
        b"Subject: Registry test\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"Hello from the registry test.\r\n"
    )


def test_load_parsers_includes_builtins_without_entry_points() -> None:
    """Built-in parsers are always available by name."""
    names = {parser.name for parser in load_parsers()}
    assert {"email_mime", "pdf_pymupdf", "text_plain"}.issubset(names)


def test_pdf_magic_routes_to_pdf_pymupdf_despite_text_plain_declaration() -> None:
    """Mislabeled PDF bytes route to the PDF parser, not plain text."""
    pdf_bytes = _minimal_pdf()
    parser = resolve_parser(pdf_bytes, "text/plain")
    assert parser is not None
    assert parser.name == "pdf_pymupdf"


def test_pdf_magic_routes_despite_txt_filename() -> None:
    """Filename extension does not override %PDF- magic routing."""
    pdf_bytes = _minimal_pdf()
    parser = resolve_parser(pdf_bytes, "text/plain")
    assert parser is not None
    assert parser.name == "pdf_pymupdf"


def test_unknown_binary_yields_unsupported_document() -> None:
    """Random binary with null bytes is not dispatched to any parser."""
    raw = b"\x00\x01\x02\xff\xfe binary gibberish"
    parser = resolve_parser(raw, "application/octet-stream")
    assert parser is None

    blob = Blob(raw=raw, filename=" mystery.bin", mime_type="application/octet-stream")
    doc = unsupported_document(blob, ParseContext(), sniff_mime(raw, blob.mime_type))
    assert doc.provenance.status == ParseStatus.unsupported
    assert "unsupported content type" in doc.provenance.warnings[0]


def test_email_header_sniff_routes_to_email_mime() -> None:
    """RFC 822 header prefixes route to the email parser."""
    raw = _sample_email()
    parser = resolve_parser(raw, "application/octet-stream")
    assert parser is not None
    assert parser.name == "email_mime"
