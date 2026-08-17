"""PDF page rasterization (sole pymupdf entry point for this package)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pymupdf


@dataclass(frozen=True)
class RasterPage:
    """One rasterized PDF page ready for OCR."""

    page_number: int
    image: np.ndarray
    page_width: float
    page_height: float


def rasterize_pdf(raw: bytes, *, dpi: int = 200) -> list[RasterPage]:
    """Rasterize every PDF page to an RGB numpy image at the given DPI."""
    doc = pymupdf.open(stream=raw, filetype="pdf")
    try:
        pages: list[RasterPage] = []
        for page in doc:
            rect = page.rect
            pixmap = page.get_pixmap(dpi=dpi, alpha=False)
            channels = pixmap.n
            image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                pixmap.height,
                pixmap.width,
                channels,
            )
            if channels == 4:
                image = image[:, :, :3]
            pages.append(
                RasterPage(
                    page_number=page.number + 1,
                    image=image,
                    page_width=float(rect.width),
                    page_height=float(rect.height),
                )
            )
        return pages
    finally:
        doc.close()


def pdf_page_count(raw: bytes) -> int:
    """Return the number of pages in a PDF without rasterizing."""
    doc = pymupdf.open(stream=raw, filetype="pdf")
    try:
        return doc.page_count
    finally:
        doc.close()


def pdf_catalog_metadata(raw: bytes) -> tuple[str | None, str | None]:
    """Return title and producer from the PDF catalog, when present."""
    doc = pymupdf.open(stream=raw, filetype="pdf")
    try:
        metadata = doc.metadata or {}
        title = metadata.get("title") or None
        producer = metadata.get("producer") or None
        return title, producer
    finally:
        doc.close()
