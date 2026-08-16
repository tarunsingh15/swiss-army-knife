"""Citation anchors and PDF quote resolution helpers."""

from __future__ import annotations

from email_parser.file_parsers.pdf_pymupdf import PdfPymupdfParser
from email_parser.models import Document


def anchors_from_document(doc: Document) -> dict[str, dict]:
    """Map block_id to page, bbox, and optional quad anchors."""
    anchors: dict[str, dict] = {}
    for block in doc.blocks:
        if block.anchor is None:
            continue
        entry: dict = {}
        if block.anchor.page is not None:
            entry["page"] = block.anchor.page
        if block.anchor.bbox is not None:
            entry["bbox"] = block.anchor.bbox
        if block.anchor.quads is not None:
            entry["quads"] = block.anchor.quads
        if entry:
            anchors[block.block_id] = entry
    return anchors


def resolve_quote(
    raw_pdf: bytes,
    quote: str,
    page: int,
    clip: tuple[float, float, float, float] | None = None,
) -> list[list[float]]:
    """Search a PDF page for quote text and return quad point lists."""
    return PdfPymupdfParser().search_quote(raw_pdf, quote, clip, page)


def render_thumbnail(
    raw_pdf: bytes,
    page: int,
    clip: tuple[float, float, float, float],
    dpi: int = 150,
) -> bytes:
    """Render a clipped PNG thumbnail for a PDF page region."""
    return PdfPymupdfParser().render_thumbnail(raw_pdf, page, clip, dpi=dpi)
