"""Citation anchors and PDF quote resolution helpers."""

from __future__ import annotations

from pdf_tool import render_thumbnail as pdf_render_thumbnail
from pdf_tool import search_quote as pdf_search_quote

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
    return pdf_search_quote(raw_pdf, quote, page=page, clip=clip)


def render_thumbnail(
    raw_pdf: bytes,
    page: int,
    clip: tuple[float, float, float, float],
    dpi: int = 150,
) -> bytes:
    """Render a clipped PNG thumbnail for a PDF page region."""
    return pdf_render_thumbnail(raw_pdf, page, clip, dpi=dpi)
