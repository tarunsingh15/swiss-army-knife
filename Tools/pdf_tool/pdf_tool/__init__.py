"""Standalone PDF extraction tool (PyMuPDF backend).

Use this package directly when you only need PDF parsing, quote search, or
thumbnails. The email parser integrates via a thin adapter in
``email_parser.file_parsers.pdf_pymupdf``.
"""

from __future__ import annotations

from pdf_tool.models import (
    EmbeddedFile,
    PdfAnchor,
    PdfBlock,
    PdfBlockType,
    PdfMetadata,
    PdfParseResult,
    PdfParseStatus,
)
from pdf_tool.pymupdf_engine import ENGINE_NAME, ENGINE_VERSION, PyMuPDFEngine, is_pdf_bytes

_default_engine = PyMuPDFEngine()


def parse_pdf(raw: bytes, *, filename: str | None = None) -> PdfParseResult:
    """Parse PDF bytes into blocks, metadata, and embedded file payloads."""
    return _default_engine.parse(raw, filename=filename)


def search_quote(
    raw: bytes,
    needle: str,
    *,
    page: int,
    clip: tuple[float, float, float, float] | None = None,
) -> list[list[float]]:
    """Search a PDF page for needle text and return quad point lists."""
    return _default_engine.search_quote(raw, needle, clip, page)


def render_thumbnail(
    raw: bytes,
    page: int,
    clip: tuple[float, float, float, float],
    *,
    dpi: int = 150,
) -> bytes:
    """Render a clipped PNG thumbnail for a PDF page region."""
    return _default_engine.render_thumbnail(raw, page, clip, dpi=dpi)


def is_pdf(raw: bytes, mime_type: str | None = None) -> bool:
    """Return True when bytes look like a PDF."""
    return is_pdf_bytes(raw, mime_type)


__all__ = [
    "ENGINE_NAME",
    "ENGINE_VERSION",
    "EmbeddedFile",
    "PdfAnchor",
    "PdfBlock",
    "PdfBlockType",
    "PdfMetadata",
    "PdfParseResult",
    "PdfParseStatus",
    "PyMuPDFEngine",
    "is_pdf",
    "parse_pdf",
    "render_thumbnail",
    "search_quote",
]
