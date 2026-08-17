"""Tests for the PyMuPDF PDF parser."""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from email_parser.file_parsers.base import Blob, ParseContext
from email_parser.file_parsers.pdf_pymupdf import PdfPymupdfParser
from email_parser.models import BlockType, ParseStatus, RelationType


def _parser() -> PdfPymupdfParser:
    """Return a fresh parser instance for tests."""
    return PdfPymupdfParser()


def _parse(raw: bytes, *, filename: str | None = None) -> tuple:
    """Parse PDF bytes and return the document plus child blobs."""
    result = _parser().parse(
        Blob(raw=raw, filename=filename, mime_type="application/pdf"),
        ParseContext(),
    )
    return result.document, result.child_blobs


def _make_text_pdf(text: str = "Hello PDF") -> bytes:
    """Create a minimal born-digital PDF with one text line."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    payload = doc.tobytes()
    doc.close()
    return payload


def _make_table_pdf() -> bytes:
    """Create a PDF containing a simple detectable table."""
    doc = pymupdf.open()
    page = doc.new_page()
    shape = page.new_shape()
    for y in (72, 116, 160):
        shape.draw_line((72, y), (300, y))
    for x in (72, 186, 300):
        shape.draw_line((x, 72), (x, 160))
    shape.finish(color=(0, 0, 0), width=1)
    shape.commit()
    page.insert_text((90, 100), "A")
    page.insert_text((210, 100), "B")
    page.insert_text((90, 144), "1")
    page.insert_text((210, 144), "2")
    payload = doc.tobytes()
    doc.close()
    return payload


def _make_embedded_file_pdf(name: str, content: bytes) -> bytes:
    """Create a PDF with one embedded file attachment."""
    doc = pymupdf.open()
    doc.new_page()
    doc.embfile_add(name, content, filename=name, desc="test attachment")
    payload = doc.tobytes()
    doc.close()
    return payload


def test_can_handle_pdf_magic_and_mime() -> None:
    """Parser claims PDF MIME types and %PDF- magic bytes."""
    parser = _parser()
    assert parser.can_handle("application/pdf", b"")
    assert parser.can_handle("application/x-pdf", b"")
    assert parser.can_handle("application/octet-stream", b"%PDF-1.7\n")
    assert not parser.can_handle("text/plain", b"hello")


def test_text_and_table_blocks_have_page_and_bbox() -> None:
    """Every emitted text/table block carries page and bbox anchors."""
    document, _ = _parse(_make_table_pdf(), filename="table.pdf")
    text_or_table = [
        block
        for block in document.blocks
        if block.type in {BlockType.paragraph, BlockType.heading, BlockType.table}
    ]
    assert text_or_table, "expected at least one text or table block"
    for block in text_or_table:
        assert block.anchor is not None
        assert block.anchor.page is not None
        assert block.anchor.bbox is not None
        assert len(block.anchor.bbox) == 4


def test_table_rows_match_expected_grid() -> None:
    """Detected table rows match the inserted grid values."""
    document, _ = _parse(_make_table_pdf())
    table_blocks = [block for block in document.blocks if block.type == BlockType.table]
    assert table_blocks, "expected a table block"
    assert table_blocks[0].rows == [["A", "B"], ["1", "2"]]


def test_embedded_file_yields_child_blob() -> None:
    """Embedded files are emitted as child blobs for downstream parsing."""
    embedded_name = "payload.txt"
    embedded_bytes = b"embedded payload"
    document, child_blobs = _parse(_make_embedded_file_pdf(embedded_name, embedded_bytes))
    assert document.provenance.status == ParseStatus.ok
    assert len(child_blobs) == 1
    child = child_blobs[0]
    assert child.raw == embedded_bytes
    assert child.filename == embedded_name
    assert child.relation_to_parent == RelationType.embedded_file


def test_born_digital_pdf_has_chars_per_page() -> None:
    """Born-digital pages report non-zero chars_per_page metadata."""
    document, _ = _parse(_make_text_pdf("Born digital text"))
    assert document.metadata.native.chars_per_page is not None
    assert all(count > 0 for count in document.metadata.native.chars_per_page)
    assert document.metadata.native.has_text_layer is True
    assert document.metadata.native.needs_ocr is False


def test_corrupt_bytes_yield_failed_status() -> None:
    """Corrupt PDF bytes produce a failed document with warnings."""
    document, child_blobs = _parse(b"%PDF-1.7\nthis is not a valid pdf stream")
    assert document.provenance.status == ParseStatus.failed
    assert document.provenance.warnings
    assert document.blocks == []
    assert child_blobs == []


def test_pymupdf_import_only_in_pdf_tool_engine() -> None:
    """PyMuPDF import statements exist only in pdf_tool/pymupdf_engine.py."""
    repo_root = Path(__file__).resolve().parents[1]
    allowed = (repo_root / ".." / "pdf_tool" / "pdf_tool" / "pymupdf_engine.py").resolve()
    import_pattern = re.compile(r"^\s*(import pymupdf|from pymupdf\b)", re.MULTILINE)
    offenders: list[str] = []
    for root_name in ("email_parser", "web"):
        for path in (repo_root / root_name).glob("**/*.py"):
            if path.resolve() == allowed.resolve():
                continue
            text = path.read_text(encoding="utf-8")
            if import_pattern.search(text):
                offenders.append(str(path.relative_to(repo_root)))
    assert offenders == []


def test_search_quote_returns_quad_points() -> None:
    """Engine search_quote returns plain float quad point lists."""
    raw = _make_text_pdf("FindMeHere")
    parser = _parser()
    quads = parser.search_quote(raw, "FindMe", clip=None, page=1)
    assert quads
    assert all(len(quad) == 8 for quad in quads)
    assert all(isinstance(value, float) for quad in quads for value in quad)


def test_render_thumbnail_returns_png_bytes() -> None:
    """Engine render_thumbnail returns PNG bytes for a clipped region."""
    raw = _make_text_pdf("Thumbnail text")
    parser = _parser()
    png_bytes = parser.render_thumbnail(raw, page=1, clip=(0.0, 0.0, 200.0, 200.0), dpi=72)
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
