"""Tests for citation anchors and PDF quote resolution."""

from __future__ import annotations

import pymupdf

from email_parser.ai_context.citations import render_thumbnail, resolve_quote
from email_parser.file_parsers.base import Blob, ParseContext
from email_parser.file_parsers.pdf_pymupdf import PdfPymupdfParser


def _make_fee_pdf() -> bytes:
    """Create a one-page PDF containing the fee sentence."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "The fee is twenty five thousand dollars.")
    payload = doc.tobytes()
    doc.close()
    return payload


def _quad_center(quad: list[float]) -> tuple[float, float]:
    """Return the center point of an eight-point quad."""
    xs = [quad[index] for index in range(0, len(quad), 2)]
    ys = [quad[index] for index in range(1, len(quad), 2)]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _boxes_overlap(
    bbox: tuple[float, float, float, float],
    quad: list[float],
) -> bool:
    """Return True when quad center lies inside bbox or rects overlap."""
    x0, y0, x1, y1 = bbox
    cx, cy = _quad_center(quad)
    if x0 <= cx <= x1 and y0 <= cy <= y1:
        return True
    qx0 = min(quad[i] for i in range(0, len(quad), 2))
    qx1 = max(quad[i] for i in range(0, len(quad), 2))
    qy0 = min(quad[i] for i in range(1, len(quad), 2))
    qy1 = max(quad[i] for i in range(1, len(quad), 2))
    return not (qx1 < x0 or qx0 > x1 or qy1 < y0 or qy0 > y1)


def test_resolve_quote_and_thumbnail() -> None:
    """Quote search returns quads near the source block and PNG thumbnails."""
    raw = _make_fee_pdf()
    document = PdfPymupdfParser().parse(
        Blob(raw=raw, mime_type="application/pdf"),
        ParseContext(),
    ).document

    needle = "twenty five thousand dollars"
    target = next(block for block in document.blocks if block.text and needle in block.text)
    page = target.anchor.page if target.anchor and target.anchor.page is not None else 1
    clip = target.anchor.bbox if target.anchor else None

    quads = resolve_quote(raw, needle, page, clip=clip)
    assert quads

    if target.anchor and target.anchor.bbox is not None:
        assert any(_boxes_overlap(target.anchor.bbox, quad) for quad in quads)

    bbox = target.anchor.bbox if target.anchor and target.anchor.bbox else (70.0, 60.0, 500.0, 90.0)
    png = render_thumbnail(raw, page, bbox)
    assert png.startswith(b"\x89PNG")
