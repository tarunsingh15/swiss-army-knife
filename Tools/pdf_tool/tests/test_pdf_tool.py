"""Tests for the standalone pdf_tool package."""

from __future__ import annotations

import pymupdf

from pdf_tool import PdfBlockType, PdfParseStatus, is_pdf, parse_pdf


def _make_text_pdf(text: str = "Hello PDF") -> bytes:
    """Create a minimal born-digital PDF with one text line."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    payload = doc.tobytes()
    doc.close()
    return payload


def test_is_pdf_detects_magic_and_mime() -> None:
    """is_pdf claims PDF MIME types and %PDF- magic bytes."""
    assert is_pdf(b"", "application/pdf")
    assert is_pdf(b"%PDF-1.7\n", "application/octet-stream")
    assert not is_pdf(b"hello", "text/plain")


def test_parse_pdf_returns_generic_blocks() -> None:
    """parse_pdf returns pdf_tool models without email-parser types."""
    result = parse_pdf(_make_text_pdf("Standalone tool"), filename="sample.pdf")
    assert result.status == PdfParseStatus.ok
    assert result.metadata.filename == "sample.pdf"
    assert result.metadata.page_count == 1
    assert result.blocks
    assert result.blocks[0].block_type in {PdfBlockType.paragraph, PdfBlockType.heading}
    assert result.blocks[0].anchor is not None


def test_corrupt_pdf_returns_failed_status() -> None:
    """Corrupt PDF bytes produce a failed result with warnings."""
    result = parse_pdf(b"%PDF-1.7\nnot a real pdf")
    assert result.status == PdfParseStatus.failed
    assert result.warnings
    assert result.blocks == []
